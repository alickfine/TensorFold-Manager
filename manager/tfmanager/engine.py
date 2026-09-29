"""Exclusive lifecycle, real readiness, and only currently-owned process handles."""
import contextlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
from .state import APIError,clean_env

class Engine:
    def __init__(self,store,models,command=None,startup_timeout=600,stop_timeout=120):
        self.store=store; self.models=models; self.command=command; self.startup_timeout=startup_timeout; self.stop_timeout=stop_timeout
        self.lifecycle=threading.RLock(); self.lock=threading.RLock(); self.condition=threading.Condition(self.lock)
        self.active_model_id=None;self.running_model_config=None
        self.active_requests=0; self.draining=False; self.proc=None; self.reader=None; self.running_settings=None
        self.data=dict(state='stopped',pid=None,model=None,version=None,health=None,error=None,started_at=None,pending=False)
    def status(self):
        with self.lock:
            if self.proc and self.proc.poll() is not None and self.data['state'] not in ('stopped','failed'):
                self.data.update(state='failed',health=False,error='Engine supervisor exited',pid=None)
            result=self.data.copy(); result['pending']=bool(self.running_settings and (self.store.settings()!=self.running_settings or self.store.get('model_config',self.active_model_id,{})!=self.running_model_config)); return result
    def executable(self):
        if self.command:return self.command
        pointer=self.store.get('engine_active',default=None)
        if pointer:
            path=Path(pointer['python'])
            if not path.is_relative_to(self.store.root/'engines'): raise APIError('Invalid engine slot','invalid_engine',409)
        else:
            external=self.store.settings()['engine_python']
            if not external or os.environ.get('TFM_ALLOW_EXTERNAL_ENGINE')!='1': raise APIError('Install the TensorFold engine first','engine_not_installed',409)
            path=Path(external)
        if not path.is_file(): raise APIError('Engine Python is missing','engine_not_installed',409)
        return [str(path),'-m','tensorfold']
    def probe(self,command=None):
        command=command or self.executable(); env=clean_env(); env['TENSORFOLD_NO_UPDATE_CHECK']='1'
        try:
            help_result=subprocess.run(command+['serve','--help'],env=env,capture_output=True,text=True,timeout=30)
            version=subprocess.run(command+['--version'],env=env,capture_output=True,text=True,timeout=30)
        except (OSError,subprocess.TimeoutExpired) as exc: raise APIError(f'Engine CLI probe failed: {exc}','engine_probe_failed',409)
        if help_result.returncode or version.returncode: raise APIError('Engine CLI probe failed: '+(help_result.stderr+version.stderr)[-2000:],'engine_probe_failed',409)
        flags=set(re.findall(r'--[a-z][a-z0-9-]*',help_result.stdout))
        if not {'--host','--port','--snapshot-dir'}<=flags: raise APIError('Engine CLI lacks required isolation options','unsupported_engine',409)
        return {'version':version.stdout.strip(),'flags':sorted(flags)}
    def inspect_model(self,command,path):
        env=clean_env();env.update(HF_HUB_OFFLINE='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HOME=str(self.store.root/'hf-runtime'),TENSORFOLD_NO_UPDATE_CHECK='1')
        try:info=subprocess.run(command+['info',path],env=env,capture_output=True,text=True,timeout=30)
        except (OSError,subprocess.TimeoutExpired) as exc:raise APIError('Model preflight failed: '+str(exc),'model_preflight_failed',409)
        if info.returncode:raise APIError('Model preflight failed: '+(info.stderr or info.stdout)[-4000:],'unsupported_model',409)
        return info.stdout.strip()[-8000:]
    def validate_model(self,value):
        if not isinstance(value,str) or not Path(value).expanduser().is_absolute():raise APIError('An absolute local model path is required')
        row=self.models.describe(Path(value).expanduser())
        if not row or not row['installed']:raise APIError('Model weights are incomplete or missing','model_missing',409)
        command=self.executable();probe=self.probe(command);info=self.inspect_model(command,row['path'])
        validation={'scope':'cli_compatibility_only','verified_at':time.time(),'engine_version':probe['version'],'cli_info':info,'fingerprint':self.models.fingerprint(row['path']),'loaded':False,'note':'CLI compatibility was checked. Weight provenance and successful model loading have not been verified.'}
        self.store.put('model_validation',validation,row['id']);self.models.scan()
        return {'model':self.models.describe(Path(row['path'])),'validation':validation}
    def build_command(self,model,settings):
        command=self.executable(); probe=self.probe(command); flags=set(probe['flags'])
        self.inspect_model(command,model['path'])
        argv=command+['serve',model['path'],'--host','127.0.0.1','--port',str(settings['engine_port']),'--snapshot-dir',str(self.store.snapshots)]
        for key in ('context','max_tokens','temperature','top_p','top_k','parallel','prompt_cache_gib','mlx_cache_gib'):
            flag='--'+key.replace('_','-')
            if flag not in flags: raise APIError(f'Installed engine does not support {flag}','unsupported_capability',409)
            argv.extend([flag,str(settings[key])])
        thinking='--thinking' if settings['thinking'] else '--no-thinking'
        if thinking not in flags: raise APIError('Engine cannot apply the requested thinking setting','unsupported_capability',409)
        argv.append(thinking)
        if '--name' in flags: argv.extend(['--name',model['repo'] or model['name']])
        if '--no-update-check' in flags: argv.append('--no-update-check')
        return argv,probe
    def start(self,model):
        with self.lifecycle:
            if self.proc and self.proc.poll() is None: raise APIError('An owned engine is already running','engine_busy',409)
            row=self.models.resolve(model); settings=self.store.settings(); effective=settings|self.store.get('model_config',row['id'],{})
            with socket.socket() as sock:
                sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                try: sock.bind(('127.0.0.1',settings['engine_port']))
                except OSError: raise APIError('Engine port is occupied; no external service was adopted','port_conflict',409)
            argv,probe=self.build_command(row,effective)
            env=clean_env(); env.update(TENSORFOLD_NO_UPDATE_CHECK='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HOME=str(self.store.root/'hf-runtime'))
            supervisor=[sys.executable,str(Path(__file__).with_name('supervisor.py'))]
            self.proc=subprocess.Popen(supervisor,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,env=clean_env(),start_new_session=True)
            self.proc.stdin.write(json.dumps({'argv':argv,'env':env,'stop_timeout':self.stop_timeout})+'\n'); self.proc.stdin.flush()
            with self.lock:
                self.running_settings=settings;self.active_model_id=row['id'];self.running_model_config=self.store.get('model_config',row['id'],{}); self.draining=False
                self.data.update(state='starting',pid=None,model=row['repo'] or row['id'],version=probe['version'],health=False,error=None,started_at=time.time())
            self.reader=threading.Thread(target=self._events,args=(self.proc,),daemon=True); self.reader.start()
            threading.Thread(target=self._wait_ready,args=(self.proc,settings['engine_port']),daemon=True).start()
            self.store.log('info','Starting owned engine: '+row['name']); return self.status()
    def _events(self,proc):
        for line in proc.stdout:
            try: event=json.loads(line)
            except ValueError: continue
            with self.lock:
                if proc is not self.proc: continue
                if 'pid' in event: self.data['pid']=event['pid']
                if 'log' in event: self.store.log('info',event['log'])
                if 'error' in event: self.data.update(state='failed',error=event['error'],health=False)
                if 'exit' in event:
                    expected=self.data['state']=='stopping'
                    self.data.update(state='stopped' if expected else 'failed',pid=None,health=False,error=None if expected else f'Engine exited with code {event["exit"]}')
        proc.stdout.close()
    def _wait_ready(self,proc,port):
        deadline=time.monotonic()+self.startup_timeout
        while time.monotonic()<deadline:
            with self.lock:
                if proc is not self.proc or proc.poll() is not None or self.data['state']!='starting': return
                pid=self.data['pid']
            if pid:
                try:
                    self.verify_api(port)
                    with self.lock:
                        if proc.poll() is None and self.data['state']=='starting': self.data.update(state='ready',health=True)
                    return
                except (OSError,ValueError,APIError,http.client.HTTPException): pass
            time.sleep(.2)
        with self.lock:
            if proc is self.proc and self.data['state']=='starting': self.data.update(state='failed',health=False,error='Readiness timed out; inspect logs and stop before retrying')
    @staticmethod
    def verify_api(port):
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=2)
        try:
            conn.request('GET','/v1/models'); response=conn.getresponse(); payload=json.loads(response.read(1048576))
            if response.status!=200 or not isinstance(payload.get('data'),list) or not payload['data']: raise APIError('Engine API is not ready','engine_not_ready',503)
            return payload
        finally: conn.close()
    @contextlib.contextmanager
    def request(self):
        with self.condition:
            if self.draining or self.status()['state']!='ready': raise APIError('Engine is not ready','engine_not_ready',503)
            self.active_requests+=1; port=self.running_settings['engine_port']
        try: yield port
        finally:
            with self.condition: self.active_requests-=1; self.condition.notify_all()
    def drain(self,timeout=None):
        with self.condition:
            self.draining=True; deadline=time.monotonic()+(self.stop_timeout if timeout is None else timeout)
            while self.active_requests:
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    self.draining=False; raise APIError('Active requests did not drain; engine left running','drain_timeout',409)
                self.condition.wait(remaining)
    def stop(self,force=False):
        with self.lifecycle:
            if not self.proc or self.proc.poll() is not None:
                if self.proc:
                    if self.reader:self.reader.join(timeout=2)
                    self.proc.stdin.close()
                with self.lock: self.data.update(state='stopped',pid=None,health=False); self.running_settings=None
                return self.status()
            if not force:self.drain()
            with self.lock: self.data['state']='stopping'
            try:
                self.proc.stdin.write(json.dumps({'action':'force' if force else 'stop'})+'\n'); self.proc.stdin.flush()
                self.proc.wait(timeout=self.stop_timeout+2)
            except (BrokenPipeError,OSError): pass
            except subprocess.TimeoutExpired:
                with self.lock: self.data.update(state='failed',error='Graceful stop timed out; explicit force is required')
                raise APIError('Engine did not stop; explicit force is required','stop_timeout',409)
            if self.reader:self.reader.join(timeout=2)
            self.proc.stdin.close()
            with self.lock: self.data.update(state='stopped',pid=None,health=False,error=None); self.running_settings=None
            return self.status()
    def restart(self,model=None):
        with self.lifecycle:
            selected=model or self.data['model'] or self.store.settings()['selected_model']
            self.stop(); return self.start(selected)
    def await_ready(self,timeout=None):
        deadline=time.monotonic()+(timeout or self.startup_timeout)
        while time.monotonic()<deadline:
            status=self.status()
            if status['state']=='ready': return status
            if status['state'] in ('failed','stopped'): raise APIError(status['error'] or 'Engine stopped','engine_failed',409)
            time.sleep(.2)
        raise APIError('Readiness timed out','engine_failed',409)
