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
from .state import APIError,clean_env,ADVANCED_OPTIONS
from .resources import ResourceGate,ResourceBlocked,GIB,Lease
from .peer import BoundHTTPConnection
from .services import NativeInstances

class Engine:
    def __init__(self,store,models,command=None,startup_timeout=600,stop_timeout=120,resources=None):
        self.resources=resources or ResourceGate(store);self.lease=None;self.attachment=None
        self.native=NativeInstances();self.peer_token=None;self.child_liveness=None;self.child_exit_confirmed=True
        self.store=store; self.models=models; self.command=command; self.models.engine_identity=self.validation_identity; self.startup_timeout=startup_timeout; self.stop_timeout=stop_timeout
        self.lifecycle=threading.RLock(); self.lock=threading.RLock(); self.condition=threading.Condition(self.lock)
        self.active_model_id=None;self.running_model_config=None;self.running_parameters=None
        self.active_requests=0; self.draining=False; self.proc=None; self.reader=None; self.running_settings=None
        self.data=dict(control_owner=None,state='stopped',pid=None,model=None,version=None,health=None,error=None,started_at=None,pending=False)
    def status(self):
        with self.lock:
            if self.attachment and not self.resources.verify_attachment(self.attachment):self.data.update(state='failed',health=False,error='External service identity or health changed; detach and revalidate')
            if self.proc and self.proc.poll() is not None:
                self.data['child_exit_confirmed']=not self._child_alive()
                if self.data['state'] not in ('stopped','failed'):self.data.update(state='failed',health=False,error='Engine supervisor exited; child exit must be confirmed')
            self._sample_health()
            result=self.data.copy();result['active_requests']=self.active_requests;result['draining']=self.draining; result['pending']=bool(self.running_settings and (self.store.settings()!=self.running_settings or self.store.get('model_config',self.active_model_id,{})!=self.running_model_config)); return result
    def _sample_health(self):
        if self.data['state'] not in ('ready','attached'):
            self.data.update(health_detail=None,last_health_at=None,health_error=None)
            self._health_sample_key=None;return
        port=int(self.attachment['flags']['port']) if self.attachment else self.running_settings['engine_port']
        key=(port,self.data['started_at'],self.data.get('served_name'))
        now=time.monotonic()
        if getattr(self,'_health_sample_key',None)==key and now-getattr(self,'_health_checked',0)<2:return
        self._health_sample_key=key;self._health_checked=now
        connection=self.connection(port,timeout=.5)
        try:
            connection.request('GET','/health');response=connection.getresponse();raw=response.read(1048577)
            if response.status!=200 or len(raw)>1048576:raise ValueError('health response unavailable')
            payload=json.loads(raw)
            if not isinstance(payload,dict) or payload.get('status') not in ('ok','ready','healthy') or payload.get('model')!=self.data.get('served_name') or payload.get('warming') is not False:
                raise ValueError('health model identity differs from the selected service')
            memory=payload.get('memory') or {}
            if not isinstance(memory,dict):raise ValueError('health memory response is invalid')
            safe_memory={k:v for k,v in memory.items() if k in ('active','cache','peak','budget','mlx_budget','footprint') and type(v) is int and v>=0}
            detail={k:payload.get(k) for k in ('status','model','warming','max_batch_size')}
            detail['memory']=safe_memory
            self.data.update(health=True,health_detail=detail,last_health_at=time.time(),health_error=None,error=None)
        except (TimeoutError,subprocess.TimeoutExpired):
            # A slow endpoint is not proof that the owned process has failed.
            # Fail requests closed, but keep sampling so a healthy endpoint can recover.
            self.data.update(health=False,health_detail=None,health_error='Health sampling timed out; retrying',error='Health sampling timed out; retrying')
        except (OSError,ValueError,APIError,http.client.HTTPException,subprocess.TimeoutExpired):
            self.data.update(state='failed',health=False,health_detail=None,health_error='Current health model identity or endpoint could not be verified',error='Current health model identity or endpoint could not be verified')
        finally:connection.close()
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
        return [str(path),'-B','-m','tensorfold']
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
        if command[-2:]==['-m','tensorfold']:
            helper="from pathlib import Path; import sys; from tensorfold import families; p=Path(sys.argv[1]); f=families.detect(p); c=families.read_config(p); b=families.backends_of(f); (('mlx' in b) or (_ for _ in ()).throw(ValueError('No MLX reader for this checkpoint'))); families.require_readable(f,c,'mlx'); check=getattr(f.package,'check',None); check(p) if check else None; print('MLX_READABLE')"
            try:checked=subprocess.run(command[:-2]+['-c',helper,path],env=env,capture_output=True,text=True,timeout=30)
            except (OSError,subprocess.TimeoutExpired) as exc:raise APIError('MLX compatibility probe failed: '+str(exc),'model_preflight_failed',409)
            if checked.returncode or 'MLX_READABLE' not in checked.stdout:raise APIError('MLX compatibility probe failed: '+(checked.stderr or checked.stdout)[-4000:],'unsupported_model',409)
        elif not re.search(r'^runs on\s+.*Apple Silicon \(MLX\)',info.stdout,re.M):
            raise APIError('CLI info did not verify a readable MLX checkpoint','unsupported_model',409)
        return info.stdout.strip()[-8000:]
    def validation_identity(self):
        if self.command:return {'command':self.command}
        active=self.store.get('engine_active')
        return {key:active.get(key) for key in ('version','commit','python')} if active else None
    def validate_model(self,value):
        if not isinstance(value,str) or not Path(value).expanduser().is_absolute():raise APIError('An absolute local model path is required')
        row=self.models.describe(Path(value).expanduser())
        if not row or not row['installed']:raise APIError('Model weights are incomplete or missing','model_missing',409)
        identity=self.validation_identity();fingerprint=self.models.fingerprint(row['path'])
        command=self.executable();probe=self.probe(command);info=self.inspect_model(command,row['path'])
        if identity!=self.validation_identity() or fingerprint!=self.models.fingerprint(row['path']):raise APIError('Engine or model changed during detection; retry','model_changed',409)
        validation={'scope':'cli_compatibility_only','backend':'mlx','supported':True,'engine_identity':identity,'verified_at':time.time(),'engine_version':probe['version'],'cli_info':info,'fingerprint':self.models.fingerprint(row['path']),'loaded':False,'note':'CLI compatibility was checked. Weight provenance and successful model loading have not been verified.'}
        self.store.put('model_validation',validation,row['id']);self.models.scan()
        return {'model':self.models.describe(Path(row['path'])),'validation':validation}
    def build_command(self,model,settings,command=None):
        command=command or self.executable(); probe=self.probe(command); flags=set(probe['flags'])
        self.inspect_model(command,model['path'])
        argv=command+['serve',model['path'],'--host','127.0.0.1','--port',str(settings['engine_port']),'--snapshot-dir',str(self.store.snapshots)]
        for key in ('context','max_tokens','temperature','top_p','top_k','parallel','prompt_cache_gib','mlx_cache_gib'):
            flag='--'+key.replace('_','-')
            if flag not in flags: raise APIError(f'Installed engine does not support {flag}','unsupported_capability',409)
            argv.extend([flag,str(settings[key])])
        thinking='--thinking' if settings['thinking'] else '--no-thinking'
        if thinking not in flags: raise APIError('Engine cannot apply the requested thinking setting','unsupported_capability',409)
        argv.append(thinking)
        for key in ADVANCED_OPTIONS:
            value=settings.get(key)
            if value is None or key=='name':continue
            flag='--'+key.replace('_','-')
            if flag not in flags:raise APIError(f'Installed engine does not support {flag}','unsupported_capability',409)
            if key=='mtp_confidence':raise APIError('--mtp-confidence is a CUDA-only option; TensorFold MLX does not implement it','unsupported_capability',409)
            if key=='drafter' and value not in ('auto','none'):
                path=Path(value).expanduser()
                if path.is_absolute():draft=self.models.describe(path)
                else:draft=next((row for row in self.models.scan() if row['repo']==value),None)
                if not draft or not draft['installed']:raise APIError('Drafter weights must already exist in configured model roots','drafter_missing',409)
                value=draft['path']
            if key=='no_drafts':
                if value:argv.append(flag)
            else:argv.extend([flag,str(value)])
        if settings.get('name') is not None and '--name' not in flags:raise APIError('Installed engine does not support --name','unsupported_capability',409)
        if '--name' in flags:argv.extend(['--name',settings.get('name') or model['repo'] or model['name']])
        if '--no-update-check' in flags: argv.append('--no-update-check')
        return argv,probe
    @staticmethod
    def runtime_config(settings):
        keys=set(ADVANCED_OPTIONS)|{'context','max_tokens','temperature','top_p','top_k','parallel','thinking','prompt_cache_gib','mlx_cache_gib','engine_port','engine_python'}
        return {key:(settings or {}).get(key) for key in keys}
    def prepare_start(self,model):
        row=self.models.resolve(model);settings=self.store.settings();effective=settings|self.store.get('model_config',row['id'],{})
        if effective.get('drafter') not in (None,'auto','none'):
            draft=effective['drafter'];path=Path(draft).expanduser()
            candidate=self.models.describe(path) if path.is_absolute() else next((r for r in self.models.scan() if r['repo']==draft),None)
            if not candidate or not candidate['installed']:raise APIError('Drafter must be installed in configured roots','drafter_missing',409)
            effective=effective|{'drafter':candidate['path']}
        return row,settings,effective
    def start(self,model,allow_attach=True,_lease=None,_prepared=None,_model_config=None):
        with self.lifecycle:
            row,settings,effective=_prepared or self.prepare_start(model)
            if self.proc and self.proc.poll() is not None and self._child_alive():raise APIError('Prior engine child exit is not confirmed','child_exit_unconfirmed',409)
            if self.attachment or (self.proc and self.proc.poll() is None):
                if self.active_model_id==row['id'] and self.runtime_config(self.running_parameters)==self.runtime_config(effective):return self.status()
                raise APIError('Stop the current engine and wait for release before changing model or configuration','engine_busy',409)
            lease=_lease or self.resources.acquire_start(row['path'],effective)
            try:
                if _lease:
                    lease.report=self.resources.preflight_start(row['path'],effective)
                    if not lease.report['allowed']:raise ResourceBlocked(lease.report)
                if lease.attachment:
                    if not allow_attach:raise ResourceBlocked(lease.report,'Upgrade validation requires an owned candidate; external service is active')
                    return self._attach(row,settings,effective,lease)
                with socket.socket() as sock:
                    sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                    try:sock.bind(('127.0.0.1',settings['engine_port']))
                    except OSError:raise APIError('Engine port is occupied; no external service was adopted','port_conflict',409)
                argv,probe=self.build_command(row,effective)
                report=self.resources.preflight_start(row['path'],effective)
                if not report['allowed'] or report['attachment']:raise ResourceBlocked(report,'Resources changed during CLI preflight; retry with fresh evidence')
                lease.report=report
                env=clean_env();env.update(TENSORFOLD_NO_UPDATE_CHECK='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HOME=str(self.store.root/'hf-runtime'),TENSORFOLD_MEMORY_LIMIT_GB=str(lease.memory_limit_bytes/GIB))
                # Nemotron's upstream fallback searches ~/.cache/tensorfold outside HF_HOME.
                # Pin MTP to a budgeted sibling or explicitly disable it; never adopt hidden draft weights.
                mtp=Path(row['path'])/'mtp-4bit.safetensors'
                env['TF_NEMOTRON_MTP']=str(mtp) if mtp.is_file() and not effective.get('no_drafts') and effective.get('mtp_drafts')!=0 else '0'
                supervisor=[sys.executable,'-B',str(Path(__file__).with_name('supervisor.py'))]
                if self.child_liveness is not None:os.close(self.child_liveness)
                live_read,live_write=os.pipe();os.set_blocking(live_read,False)
                self.child_liveness=live_read;self.child_exit_confirmed=False;self.peer_token=None
                try:
                    self.proc=subprocess.Popen(supervisor,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1,env=clean_env(),start_new_session=True,pass_fds=(lease.fd,live_write))
                    self.lease=lease
                    self.proc.stdin.write(json.dumps({'argv':argv,'env':env,'stop_timeout':self.stop_timeout,'lease_fd':lease.fd,'liveness_fd':live_write})+'\n');self.proc.stdin.flush()
                finally:os.close(live_write)
                with self.lock:
                    self.running_parameters=effective.copy();self.running_settings=settings;self.active_model_id=row['id'];self.running_model_config=_model_config if _model_config is not None else self.store.get('model_config',row['id'],{});self.draining=False
                    self.data.update(cache_ownership='manager',external_snapshot_dir=None,child_exit_confirmed=False,control_owner='manager',state='starting',pid=None,model=row['repo'] or row['id'],version=probe['version'],served_name=effective.get('name') or row['repo'] or row['name'],health=False,error=None,started_at=time.time(),resource_admission=lease.report)
                self.reader=threading.Thread(target=self._events,args=(self.proc,lease),daemon=True);self.reader.start()
                threading.Thread(target=self._wait_ready,args=(self.proc,settings['engine_port']),daemon=True).start()
                self.store.log('info','Starting owned engine: '+row['name']);return self.status()
            except Exception:
                if not self.proc or self.proc.poll() is not None:lease.release()
                elif self.lease is not lease:lease.release()
                raise
    def _attach(self,row,settings,effective,lease):
        service=lease.attachment
        if not self.resources.verify_attachment(service):lease.release();raise ResourceBlocked(lease.report,'External identity changed before attachment')
        token=self.native.bind(service['pid'])
        if not self.resources.verify_attachment(service) or self.native.bind(service['pid'])!=token:raise ResourceBlocked(lease.report,'External instance changed during attachment')
        self.peer_token=token;self.attachment=service;self.lease=lease;self.proc=None;self.draining=False
        self.running_settings=settings;self.running_parameters=effective.copy();self.active_model_id=row['id'];self.running_model_config=self.store.get('model_config',row['id'],{})
        self.data.update(control_owner='external',state='attached',pid=service['pid'],model=row['repo'] or row['id'],version=None,served_name=service['flags']['name'],health=True,error=None,started_at=service.get('started_at'),port=int(service['flags']['port']),resource_admission=lease.report,cache_ownership='external',external_snapshot_dir=service['flags'].get('snapshot-dir'))
        self.store.log('info','Attached read-only to verified same-user TensorFold service');return self.status()
    def detach(self):
        with self.lifecycle:
            if not self.attachment:return self.status()
            self.drain();self.attachment=None;self.peer_token=None
            if self.lease:self.lease.release();self.lease=None
            self.running_settings=None;self.running_parameters=None;self.draining=False
            self.data.update(cache_ownership=None,external_snapshot_dir=None,control_owner=None,state='stopped',pid=None,health=False,error=None)
            return self.status()
    def _events(self,proc,lease):
        for line in proc.stdout:
            try: event=json.loads(line)
            except ValueError: continue
            with self.lock:
                if proc is not self.proc: continue
                if 'pid' in event: self.data['pid']=event['pid']
                if 'identity' in event:self.peer_token=tuple(event['identity'])
                if 'log' in event: self.store.log('info',event['log'])
                if 'error' in event: self.data.update(state='failed',error=event['error'],health=False)
                if 'exit' in event:
                    self.child_exit_confirmed=True
                    expected=self.data['state']=='stopping'
                    self.data.update(state='stopped' if expected else 'failed',pid=None,health=False,error=None if expected else f'Engine exited with code {event["exit"]}')
        proc.stdout.close();proc.wait();lease.release()
    def _wait_ready(self,proc,port):
        deadline=time.monotonic()+self.startup_timeout
        while time.monotonic()<deadline:
            with self.lock:
                if proc is not self.proc or proc.poll() is not None or self.data['state']!='starting': return
                pid=self.data['pid'] if self.peer_token else None
            if pid:
                try:
                    self.verify_api(port)
                    with self.lock:
                        if proc.poll() is None and self.data['state']=='starting': self.data.update(state='ready',health=True)
                    return
                except (OSError,ValueError,APIError,http.client.HTTPException,subprocess.TimeoutExpired): pass
            time.sleep(.2)
        with self.lock:
            if proc is self.proc and self.data['state']=='starting': self.data.update(state='failed',health=False,error='Readiness timed out; inspect logs and stop before retrying')
    def connection(self,port,timeout=600):
        if not self.peer_token or not self.data.get('pid'):raise APIError('No verified engine instance','peer_unverified',503)
        return BoundHTTPConnection(port,self.data['pid'],self.peer_token,timeout=timeout,native=self.native)
    def verify_api(self,port):
        payload=None
        for path in ('/health','/v1/models'):
            conn=self.connection(port,timeout=2)
            try:
                conn.request('GET',path);response=conn.getresponse();raw=response.read(1048577)
                if response.status!=200 or len(raw)>1048576:raise APIError('Engine API is not ready','engine_not_ready',503)
                result=json.loads(raw)
                if not isinstance(result,dict):raise APIError('Invalid engine identity response','engine_not_ready',503)
                if path=='/health':
                    if result.get('status') not in ('ok','ready','healthy') or result.get('model')!=self.data.get('served_name') or result.get('warming') is not False:raise APIError('Health model identity is not ready','engine_not_ready',503)
                else:
                    if not isinstance(result.get('data'),list) or self.data.get('served_name') not in [r.get('id') for r in result['data'] if isinstance(r,dict)]:raise APIError('Model API identity differs','engine_not_ready',503)
                    payload=result
            finally:conn.close()
        return payload
    def _child_alive(self):
        if self.child_exit_confirmed:
            if self.child_liveness is not None:os.close(self.child_liveness);self.child_liveness=None
            return False
        if self.child_liveness is not None:
            try:
                if os.read(self.child_liveness,1)==b'':os.close(self.child_liveness);self.child_liveness=None
                else:return True
            except BlockingIOError:return True
        if self.peer_token:
            try:
                if self.native.alive(self.peer_token):return True
            except APIError:return True
        self.child_exit_confirmed=True;return False
    def request_metadata(self):
        with self.lock:
            return {'engine_version':self.data['version'],'engine_started_at':self.data['started_at'],'engine_parameters':{k:v for k,v in (self.running_parameters or {}).items() if k in set(ADVANCED_OPTIONS)|{'context','max_tokens','temperature','top_p','top_k','thinking','parallel','prompt_cache_gib','mlx_cache_gib'}},'model':self.data.get('served_name') or self.data['model']}
    @contextlib.contextmanager
    def request(self):
        with self.condition:
            status=self.status()
            if self.draining or status['state'] not in ('ready','attached') or status.get('health') is not True: raise APIError('Engine is not ready','engine_not_ready',503)
            port=int(self.attachment['flags']['port']) if self.attachment else self.running_settings['engine_port']
            connection=self.connection(port);self.active_requests+=1
        try:yield connection
        finally:
            connection.close()
            with self.condition:self.active_requests-=1;self.condition.notify_all()
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
            if self.attachment:raise APIError('External engine is read-only; detach without stopping it','external_control_forbidden',409)
            if not self.proc or self.proc.poll() is not None:
                if self.proc:
                    if self.reader:self.reader.join(timeout=2)
                    self.proc.stdin.close()
                if self._child_alive():
                    self.data.update(state='failed',health=False,error='Supervisor exited but child exit is unconfirmed',child_exit_confirmed=False)
                    raise APIError('Supervisor exited but child exit is unconfirmed; no PID signal fallback','child_exit_unconfirmed',409)
                with self.lock: self.data.update(state='stopped',pid=None,health=False,child_exit_confirmed=True); self.running_settings=None
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
            if self._child_alive():raise APIError('Engine child exit is not confirmed','child_exit_unconfirmed',409)
            with self.lock: self.data.update(state='stopped',pid=None,health=False,error=None,child_exit_confirmed=True); self.running_settings=None
            return self.status()
    def preflight_switch(self,model):
        row,settings,effective=self.prepare_start(model)
        report=self.resources.preflight_capacity(row['path'],effective)
        if not report['allowed']:raise ResourceBlocked(report,'Target exceeds verified physical capacity; current engine left running')
        return report
    @contextlib.contextmanager
    def transition_lease(self):
        # A duplicate shares the flock's open file description. Child exit and
        # the event reader can close their descriptors without opening a gap.
        current=self.lease
        guard=Lease(current.path,os.dup(current.fd),current.report.copy()) if current and not current.released else self.resources.acquire_switch()
        try:yield guard
        finally:guard.release()
    @staticmethod
    def transition_child_lease(guard):
        return Lease(guard.path,os.dup(guard.fd),guard.report.copy())
    def start_transition(self,model,guard,prepared=None,model_config=None):
        lease=self.transition_child_lease(guard)
        try:return self.start(model,allow_attach=False,_lease=lease,_prepared=prepared,_model_config=model_config)
        finally:
            if self.lease is not lease:lease.release()
    def restart(self,model=None):
        with self.lifecycle:
            selected=model or self.data['model'] or self.store.settings()['selected_model']
            self.preflight_switch(selected)
            with self.transition_lease() as guard:
                self.stop(); return self.start_transition(selected,guard)
    def await_ready(self,timeout=None):
        deadline=time.monotonic()+(timeout or self.startup_timeout)
        while time.monotonic()<deadline:
            status=self.status()
            if status['state'] in ('ready','attached'): return status
            if status['state'] in ('failed','stopped'): raise APIError(status['error'] or 'Engine stopped','engine_failed',409)
            time.sleep(.2)
        raise APIError('Readiness timed out','engine_failed',409)
