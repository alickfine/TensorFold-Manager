"""Pinned official releases in final isolated slots; transactional pointer and API-proven recovery."""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
from .downloads import public_json
from .state import APIError,clean_env

class Updates:
    API='https://api.github.com/repos/ashhart/TensorFold'
    def __init__(self,store,jobs,engine):
        self.store=store;self.jobs=jobs;self.engine=engine;self.install_lock=threading.Lock()
        jobs.register('engine_install',self.run_install);jobs.register('activate',self.run_activate);jobs.register('rollback',self.run_rollback)
    @staticmethod
    def validate_version(version):
        if not isinstance(version,str) or not re.fullmatch(r'v?\d+\.\d+\.\d+(?:\.\d+)?',version):raise APIError('Only exact official release versions are accepted')
        return 'v'+version.lstrip('v')
    def status(self):
        return self.store.get('update',default={'checked_at':None,'latest':None,'error':None}) | {'active':self.store.get('engine_active'),'staged':self.store.get('engine_staged'),'previous':self.store.get('engine_previous')}
    def check(self):
        try:
            payload=public_json(self.API+'/releases/latest');tag=self.validate_version(payload['tag_name'])
            status={'checked_at':time.time(),'latest':tag,'release_url':payload.get('html_url'),'notes':payload.get('body',''),'error':None}
        except Exception as exc:
            status=self.store.get('update',default={}) | {'checked_at':time.time(),'error':str(exc)}
        self.store.put('update',status);return self.status()
    def create(self,data,bootstrap=False):
        version=data.get('version') or self.status().get('latest')
        if not version:
            self.check();version=self.status().get('latest')
        version=self.validate_version(version)
        return self.jobs.create('engine_install',{'version':version,'bootstrap':bootstrap})
    def resolve_commit(self,version):
        release=public_json(self.API+'/releases/tags/'+version)
        if release.get('tag_name')!=version or release.get('draft') or release.get('prerelease'):raise APIError('Expected a published stable official release','untrusted_release',409)
        obj=public_json(self.API+'/git/ref/tags/'+version)['object']
        for _ in range(4):
            if obj.get('type')=='commit':break
            if obj.get('type')!='tag' or not re.fullmatch('[0-9a-f]{40}',obj.get('sha','')):raise APIError('Invalid official tag target')
            obj=public_json(self.API+'/git/tags/'+obj['sha'])['object']
        if obj.get('type')!='commit' or not re.fullmatch('[0-9a-f]{40}',obj.get('sha','')):raise APIError('Official tag did not resolve to commit')
        return obj['sha']
    def _command(self,argv,job):
        home=self.store.root/'installer-home';home.mkdir(exist_ok=True,mode=0o700)
        env=clean_env();env['HOME']=str(home);env.update(UV_CACHE_DIR=str(self.store.root/'uv-cache'),UV_NO_CONFIG='1',UV_NO_PYTHON_DOWNLOADS='1',GIT_TERMINAL_PROMPT='0',HF_HUB_DISABLE_IMPLICIT_TOKEN='1')
        log=self.store.root/('install-'+job.id+'.log')
        with log.open('a') as output:
            os.chmod(log,0o600)
            process=subprocess.Popen(argv,stdout=output,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            try:
                while process.poll() is None:job.checkpoint();time.sleep(.2)
                if process.returncode:raise APIError(f'Engine installer exited {process.returncode}; see logs','install_failed',409)
            finally:
                if process.poll() is None:
                    import signal
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                self.store.log('info',log.read_text(errors='replace')[-16000:])
    def run_install(self,job):
        if not self.install_lock.acquire(blocking=False):raise APIError('Another engine install is running','update_busy',409)
        try:
            uv=Path(os.environ.get('TFM_UV',''));runtime=Path(os.environ.get('TFM_RUNTIME_PYTHON',''))
            if not uv.is_absolute() or not uv.is_file() or not runtime.is_absolute() or not runtime.is_file():raise APIError('Bundled uv and stable runtime Python are required','runtime_unavailable',409)
            version=self.validate_version(job.params['version']);commit=self.resolve_commit(version);job.checkpoint()
            slot=self.store.root/'engines'/(version+'-'+commit[:12]+'-'+uuid.uuid4().hex[:8]);slot.parent.mkdir(exist_ok=True,mode=0o700)
            job.progress(phase='create_environment',version=version,commit=commit)
            self._command([str(uv),'venv','--no-python-downloads','--python',str(runtime),str(slot)],job)
            python=slot/'bin/python';job.progress(phase='install',version=version,commit=commit)
            self._command([str(uv),'pip','install','--no-python-downloads','--python',str(python),'https://github.com/ashhart/TensorFold/archive/'+commit+'.tar.gz'],job)
            job.checkpoint();probe=self.engine.probe([str(python),'-B','-m','tensorfold'])
            candidate={'version':version,'commit':commit,'python':str(python),'installed_at':time.time(),'cli':probe,'api_verified':False}
            (slot/'tfmanager-provenance.json').write_text(json.dumps(candidate));self.store.put('engine_staged',candidate)
            if job.params.get('bootstrap') and not self.store.get('engine_active'):
                # First installation is explicitly CLI-verified only. Starting a model provides API validation.
                self.store.put('engine_active',candidate)
            return candidate
        finally:self.install_lock.release()
    def activate(self,data=None):return self.jobs.create('activate',data or {})
    def rollback(self):return self.jobs.create('rollback',{})
    def _switch(self,candidate,job):
        if not candidate:raise APIError('No candidate environment is available','no_candidate',409)
        with self.engine.lifecycle:
            previous=self.store.get('engine_active');old_settings=self.store.settings();old_state=self.engine.status()
            model=job.params.get('model') or old_state['model'] or old_settings['selected_model']
            if not model:raise APIError('Select an installed model to validate the candidate API','model_required',409)
            self.engine.models.resolve(model)
            self.engine.drain();self.engine.stop()
            self.store.put('engine_recovery',{'active':previous,'settings':old_settings,'model':model})
            self.store.put('engine_active',candidate)
            try:
                job.progress(phase='validating_candidate');self.engine.start(model);self.engine.await_ready()
                # Health alone does not prove inference compatibility. Perform a tiny actual completion.
                from .gateway import completion
                response,_=completion(self.engine,self.store,{'model':self.engine.status().get('served_name') or self.engine.status()['model'],'messages':[{'role':'user','content':'Reply OK'}],'max_tokens':1,'temperature':0},record=True)
                if not isinstance(response.get('choices'),list) or not response['choices']:raise APIError('Candidate did not complete a real request','candidate_failed',409)
                candidate=candidate|{'api_verified':True};self.store.put('engine_active',candidate)
                if previous:self.store.put('engine_previous',previous)
                self.store.delete('engine_staged','default');return {'active':candidate,'recovered':False}
            except Exception as error:
                # Never load the old model while an unresponsive candidate still owns resources.
                self.engine.stop()
                if previous:self.store.put('engine_active',previous)
                else:self.store.delete('engine_active','default')
                self.store.settings_update(old_settings)
                if previous:
                    job.progress(phase='recovering_previous');self.engine.start(model);self.engine.await_ready()
                    from .gateway import completion
                    completion(self.engine,self.store,{'model':self.engine.status().get('served_name') or self.engine.status()['model'],'messages':[{'role':'user','content':'Reply OK'}],'max_tokens':1},record=True)
                    self.store.put('update_recovery',{'at':time.time(),'api_verified':True,'error':str(error)})
                    raise APIError('Candidate failed; previous engine API restored: '+str(error),'candidate_failed_recovered',409)
                raise APIError('Candidate failed; no previous environment existed: '+str(error),'candidate_failed',409)
    def run_activate(self,job):return self._switch(self.store.get('engine_staged'),job)
    def run_rollback(self,job):return self._switch(self.store.get('engine_previous'),job)
