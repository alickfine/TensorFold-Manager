"""Loopback-only management API and API-key protected OpenAI gateway."""
import argparse
import csv
import hmac
import io
import json
import mimetypes
import os
from pathlib import Path
import platform
import secrets
import shutil
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,unquote,urlsplit
from . import __version__
from .state import APIError,Store,bounded_number
from .models import Models
from .engine import Engine
from .jobs import Jobs
from .downloads import Downloads
from .updates import Updates
from .gateway import proxy,completion

class Server(ThreadingHTTPServer):
    daemon_threads=True;allow_reuse_address=True

class Application:
    def __init__(self,data_dir,web_dir,token,engine_command=None):
        if not token:raise ValueError('Admin token required')
        self.app_version=os.environ.get('TFM_APP_VERSION') or __version__
        self.token=token;self.instance_id=secrets.token_hex(16);self.web_dir=Path(web_dir).resolve();self.store=Store(data_dir)
        self.models=Models(self.store);self.engine=Engine(self.store,self.models,command=engine_command);self.jobs=Jobs(self.store)
        self.downloads=Downloads(self.store,self.jobs);self.updates=Updates(self.store,self.jobs,self.engine)
        self.jobs.register('benchmark',self.benchmark)
        self.http=None;self.gateway=None;self.gateway_error=None;self.closed=threading.Event();self.shutdown_lock=threading.Lock();self.update_thread=None
    def start(self,port=0,check_updates=True):
        self.models.scan();self.http=Server(('127.0.0.1',port),self.handler(False));threading.Thread(target=self.http.serve_forever,daemon=True).start()
        try:
            self.gateway=Server(('127.0.0.1',self.store.settings()['gateway_port']),self.handler(True));threading.Thread(target=self.gateway.serve_forever,daemon=True).start()
        except OSError as exc:self.gateway_error=f'Gateway port conflict: {exc}';self.store.log('error',self.gateway_error)
        if check_updates:
            self.update_thread=threading.Thread(target=self.updates.check,daemon=True);self.update_thread.start()
    def system(self):
        try:memory=os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
        except (ValueError,OSError):memory=None
        return {'platform':platform.system(),'architecture':platform.machine(),'memory_total_bytes':memory,'memory_used_bytes':None,'gpu_utilization':None,'gpu_memory_bytes':None,'cpu_percent':None}
    def capabilities(self):
        result={name:{'supported':False,'reason':reason} for name,reason in {
            'quantize':'The installed TensorFold CLI has no stable quantization command adapter. Use a separately verified upstream conversion workflow.',
            'upload':'Credential storage and authenticated publishing are not configured; no upload will be attempted.',
            'images':'TensorFold integration supports text inference only.','audio':'No upstream audio adapter.','video':'No upstream video adapter.',
            'embeddings':'No upstream embeddings adapter.','multi_model':'One owned model process is supported.',
            'ane':'No verified upstream ANE execution capability.','omlx_kernels':'oMLX-specific kernels and cache policies are not TensorFold APIs.',
            'accuracy_queue':'No reference dataset or scoring adapter configured.'}.items()}
        for name in ('chat','streaming','benchmark','downloads','profiles','keys','cache','updates'):result[name]={'supported':True,'reason':None}
        return result
    def state(self):
        return {'app_version':self.app_version,'instance_id':self.instance_id,'settings':self.store.settings(),'engine':self.engine.status(),'system':self.system(),'models':self.models.rows,'stats':self.store.stats(),'jobs':self.jobs.list(),'keys':self.store.keys(),'capabilities':self.capabilities(),'update':self.updates.status(),'profiles':self.store.profiles(),'gateway':{'port':self.gateway.server_port if self.gateway else None,'error':self.gateway_error,'pending':bool(self.gateway and self.gateway.server_port!=self.store.settings()['gateway_port'])}}
    def cache(self):
        root=self.store.snapshots;owned=not root.is_symlink() and root.resolve()==self.store.root/'snapshots' and (root/'.tfmanager-owned').is_file() and not (root/'.tfmanager-owned').is_symlink()
        files=[p for p in root.rglob('*') if p.is_file() and p.name!='.tfmanager-owned' and not p.is_symlink()] if owned else []
        stopped=self.engine.status()['state']=='stopped'
        return {'path':str(root),'size_bytes':sum(p.stat().st_size for p in files),'files':len(files),'owned':owned,'can_clear':owned and stopped,'reason':None if owned and stopped else 'Owned snapshot manifest and stopped engine required'}
    def clear_cache(self,data):
        if data.get('confirm') is not True:raise APIError('Explicit confirmation required')
        with self.engine.lifecycle:
            if not self.cache()['can_clear']:raise APIError('Owned snapshot manifest and stopped engine required','cache_locked',409)
            for path in self.store.snapshots.iterdir():
                if path.name=='.tfmanager-owned':continue
                if path.is_symlink() or path.is_file():path.unlink()
                elif path.is_dir():shutil.rmtree(path)
            return self.cache()
    def benchmark(self,job):
        data=job.params;results=[];snapshot=self.engine.request_metadata()
        result={'id':job.id,**data,'model':snapshot['model'],'engine_version':snapshot['engine_version'],'engine_parameters':snapshot['engine_parameters'],'parameters':{'max_tokens':data['max_tokens'],'temperature':0,'stream':True},'results':results,'created_at':time.time(),'status':'running'}
        self.store.put('benchmark',result,job.id)
        try:
            for i in range(data['runs']):
                job.checkpoint();job.progress(run=i+1,total=data['runs'])
                if self.engine.request_metadata()['engine_started_at']!=snapshot['engine_started_at']:raise APIError('Engine changed during benchmark; completed runs retained','engine_changed',409)
                _,metrics=completion(self.engine,self.store,{'model':snapshot['model'],'messages':[{'role':'user','content':data['prompt']}],'max_tokens':data['max_tokens'],'temperature':0},observe_stream=True,job=job)
                results.append(metrics)
                if metrics['engine_started_at']!=snapshot['engine_started_at']:raise APIError('Engine changed during benchmark; per-run source retained','engine_changed',409)
                self.store.put('benchmark',result,job.id)
            result['status']='completed';return result
        except Exception as exc:
            result.update(status='cancelled' if job.cancelled else 'failed',error=str(exc));raise
        finally:self.store.put('benchmark',result,job.id)
    def shutdown(self):
        if not self.shutdown_lock.acquire(blocking=False):return
        try:
            if self.closed.is_set():return
            self.jobs.shutdown()
            try:self.engine.stop()
            except APIError as exc:self.store.log('error',str(exc));return
            for server in (self.http,self.gateway):
                if server:server.shutdown();server.server_close()
            if self.update_thread:self.update_thread.join(timeout=32)
            self.store.close();self.closed.set()
        finally:self.shutdown_lock.release()
    def handler(self,gateway):
        app=self
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1';server_version='TensorFoldManager'
            def log_message(self,*args):pass
            def setup(self):super().setup();self.connection.settimeout(30)
            def security_headers(self):
                self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
                self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
            def respond(self,payload,status=200,content_type='application/json; charset=utf-8'):
                raw=payload if isinstance(payload,bytes) else json.dumps(payload,allow_nan=False).encode()
                self.send_response(status);self.security_headers();self.send_header('Content-Type',content_type);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def authenticate(self,required=True):
                expected=f'127.0.0.1:{self.server.server_port}'
                if self.headers.get_all('Host')!=[expected]:raise APIError('Host rejected','forbidden_host',403)
                origins=self.headers.get_all('Origin')
                if origins is not None and origins!=['http://'+expected]:raise APIError('Origin rejected','forbidden_origin',403)
                if required:
                    auth=self.headers.get_all('Authorization') or []
                    token=auth[0][7:] if len(auth)==1 and auth[0].startswith('Bearer ') else ''
                    valid=app.store.key_valid(token) if gateway else bool(token) and hmac.compare_digest(token,app.token)
                    if not valid:raise APIError('Authorization required','unauthorized',401)
            def body(self):
                if self.headers.get('Transfer-Encoding'):raise APIError('Transfer encoding unsupported')
                lengths=self.headers.get_all('Content-Length') or []
                if len(lengths)!=1 or not lengths[0].isdigit():raise APIError('Content-Length required')
                length=int(lengths[0])
                if length>8*1024*1024:raise APIError('Request too large','request_too_large',413)
                try:data=json.loads(self.rfile.read(length))
                except ValueError:raise APIError('Invalid JSON')
                if not isinstance(data,dict):raise APIError('JSON object required')
                return data
            def handle_request(self):
                parsed=urlsplit(self.path);path=unquote(parsed.path);query={k:v[-1] for k,v in parse_qs(parsed.query).items()};method=self.command
                self.authenticate(required=gateway or path.startswith('/api/'))
                if gateway:
                    if (method=='GET' and path=='/v1/models') or (method=='POST' and path in ('/v1/chat/completions','/v1/completions')):
                        proxy(self,app,path,self.body() if method=='POST' else None);return
                    raise APIError('Endpoint not found','not_found',404)
                if not path.startswith('/api/'):
                    if method!='GET':raise APIError('Method not allowed','method_not_allowed',405)
                    name=path.lstrip('/') or 'index.html';target=(app.web_dir/name).resolve()
                    if not target.is_relative_to(app.web_dir) or not target.is_file():raise APIError('Resource not found','not_found',404)
                    self.respond(target.read_bytes(),content_type=mimetypes.guess_type(target)[0] or 'application/octet-stream');return
                data=self.body() if method in ('POST','PUT') else {}
                result=None
                if method=='GET':
                    if path=='/api/state':result=app.state()
                    elif path=='/api/models':result={'models':app.models.rows}
                    elif path=='/api/profiles':result={'profiles':app.store.profiles()}
                    elif path=='/api/keys':result={'keys':app.store.keys()}
                    elif path=='/api/jobs':result={'jobs':app.jobs.list()}
                    elif path=='/api/capabilities':result=app.capabilities()
                    elif path=='/api/chat/history':result=app.store.history()
                    elif path=='/api/benchmark/results':result={'results':app.store.all('benchmark')}
                    elif path=='/api/downloads/catalog':result=app.downloads.catalog()
                    elif path=='/api/updates':result=app.updates.status()
                    elif path=='/api/cache':result=app.cache()
                    elif path=='/api/logs':result={'logs':app.store.logs(query.get('level',''),query.get('query',''),query.get('limit',200))}
                    elif path=='/api/stats':result=app.store.stats(query.get('model',''),query.get('range','all'))
                    elif path=='/api/stats/export':
                        rows=app.store.stats(query.get('model',''),query.get('range','all'))['requests'];out=io.StringIO();fields=['id','at','model','status','elapsed','ttft','input_tokens','output_tokens','prefill_tps','decode_tps','cache_tokens','prefill_seconds','prefill_tps_source','engine_version','parameters','engine_parameters','error'];writer=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');writer.writeheader()
                        for row in rows:writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in row.items()})
                        self.respond(out.getvalue().encode('utf-8-sig'),content_type='text/csv; charset=utf-8');return
                elif method=='PUT':
                    if path=='/api/settings':result={'settings':app.store.settings_update(data),'pending':app.engine.status()['pending']}
                    elif path=='/api/models/config':result={'config':app.models.configure(data)}
                elif method=='POST':
                    if path=='/api/engine/start':result=app.engine.start(data.get('model') or app.store.settings()['selected_model'])
                    elif path=='/api/engine/stop':result=app.engine.stop(force=data.get('force') is True)
                    elif path=='/api/engine/restart':result=app.engine.restart(data.get('model'))
                    elif path=='/api/models/scan':result={'models':app.models.scan()}
                    elif path=='/api/models/validate':result=app.engine.validate_model(data.get('model'))
                    elif path=='/api/profiles':result=app.store.profile_save(data)
                    elif path=='/api/keys':result=app.store.key_create(data)
                    elif path.startswith('/api/keys/') and path.endswith('/toggle'):result=app.store.key_toggle(path.split('/')[3])
                    elif path=='/api/downloads':result=app.downloads.create(data)
                    elif path=='/api/downloads/scope':result=app.downloads.grant_scope(data)
                    elif path.startswith('/api/jobs/') and len(path.split('/'))==5:result=app.jobs.action(*path.split('/')[3:5])
                    elif path=='/api/updates/check':result=app.updates.check()
                    elif path in ('/api/updates/install','/api/engine/install'):result=app.updates.create(data,bootstrap=path=='/api/engine/install')
                    elif path=='/api/updates/activate':result=app.updates.activate(data)
                    elif path=='/api/updates/rollback':result=app.updates.rollback()
                    elif path=='/api/cache/clear':result=app.clear_cache(data)
                    elif path=='/api/chat/history':result=app.store.history_save(data)
                    elif path=='/api/chat/completions':proxy(self,app,'/v1/chat/completions',data);return
                    elif path=='/api/benchmark':
                        prompt=data.get('prompt');runs=data.get('runs',1);tokens=data.get('max_tokens',128)
                        if not isinstance(prompt,str) or not 1<=len(prompt)<=100000:raise APIError('Benchmark prompt required')
                        bounded_number(runs,1,100,'runs',True);bounded_number(tokens,1,65536,'max_tokens',True)
                        result=app.jobs.create('benchmark',{'prompt':prompt,'runs':runs,'max_tokens':tokens})
                    elif path in ('/api/tools/quantize','/api/tools/upload'):
                        raise APIError(app.capabilities()[path.rsplit('/',1)[1]]['reason'],'unsupported_capability',409)
                    elif path=='/api/admin/shutdown':
                        self.respond({'shutting_down':True});threading.Thread(target=app.shutdown,daemon=True).start();return
                elif method=='DELETE':
                    if path.startswith('/api/profiles/'):app.store.profile_delete(path.rsplit('/',1)[1]);result={'profiles':app.store.profiles()}
                    elif path.startswith('/api/keys/'):app.store.key_delete(path.rsplit('/',1)[1]);result={'keys':app.store.keys()}
                if result is None:raise APIError('Endpoint not found','not_found',404)
                self.respond(result)
            def dispatch(self):
                try:self.handle_request()
                except APIError as exc:
                    self.close_connection=True
                    try:self.respond(exc.payload(),exc.status)
                    except OSError:pass
                except (ValueError,TypeError,KeyError) as exc:
                    self.close_connection=True
                    try:self.respond(APIError('Invalid request: '+str(exc)).payload(),400)
                    except OSError:pass
                except (BrokenPipeError,ConnectionResetError):self.close_connection=True
                except Exception as exc:
                    app.store.log('error',str(exc));self.close_connection=True
                    try:self.respond(APIError('Internal error; inspect application logs','internal_error',500).payload(),500)
                    except OSError:pass
            do_GET=do_POST=do_PUT=do_DELETE=do_OPTIONS=dispatch
        return Handler

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',required=True);parser.add_argument('--web-dir',required=True);parser.add_argument('--port',type=int,default=0);parser.add_argument('--parent-pipe',action='store_true');parser.add_argument('--dev',action='store_true');args=parser.parse_args(argv)
    if not args.parent_pipe and not args.dev:parser.error('A parent liveness pipe is required; --dev is for explicit development only')
    token=os.environ.pop('TFM_ADMIN_TOKEN','');nonce=os.environ.pop('TFM_BOOTSTRAP_NONCE','')
    app=Application(args.data_dir,args.web_dir,token);app.start(args.port,check_updates=os.environ.get('TFM_DISABLE_UPDATE_CHECK')!='1')
    def shutdown(*_):threading.Thread(target=app.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
    if args.parent_pipe:
        def parent():
            while sys.stdin.buffer.read(1):pass
            shutdown()
        threading.Thread(target=parent,daemon=True).start()
    print(json.dumps({'protocol':1,'event':'ready','ready':True,'port':app.http.server_port,'pid':os.getpid(),'instance_id':app.instance_id,'bootstrap_nonce':nonce}),flush=True)
    app.closed.wait()
if __name__=='__main__':main()
