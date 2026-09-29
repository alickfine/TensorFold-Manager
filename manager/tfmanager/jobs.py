"""Durable jobs with cooperative pause/cancel, resumable task-owned files."""
import threading
import time
import uuid
from .state import APIError,redact

class Cancelled(Exception): pass
class Job:
    def __init__(self,owner,row): self.owner=owner; self.row=row; self.condition=threading.Condition(); self.cancelled=False; self.paused=False; self.thread=None
    @property
    def params(self):return self.row['params']
    @property
    def id(self):return self.row['id']
    def save(self,**values):
        with self.condition:
            self.row.update(values,updated_at=time.time());self.owner.store.put('job',self.row,self.id)
    def checkpoint(self):
        with self.condition:
            while self.paused and not self.cancelled:self.condition.wait(.5)
            if self.cancelled:raise Cancelled()
    def progress(self,**values):self.save(progress=values)

class Jobs:
    def __init__(self,store):
        self.store=store;self.runners={};self.live={};self.lock=threading.RLock();self.closing=False
        for row in store.all('job'):
            if row['status'] in ('running','queued','paused'):
                row.update(status='interrupted',error='Manager restarted; resume explicitly');store.put('job',row,row['id'])
    def register(self,kind,runner):self.runners[kind]=runner
    def list(self):return self.store.all('job')
    def get(self,id):
        row=self.store.get('job',id)
        if row is None:raise APIError('Job not found','not_found',404)
        return row
    def create(self,kind,params):
        if kind not in self.runners:raise APIError('Task is unavailable','unsupported_capability',409)
        if self.closing:raise APIError('Manager is shutting down','shutting_down',503)
        row={'id':uuid.uuid4().hex,'kind':kind,'params':params,'status':'queued','created_at':time.time(),'updated_at':time.time(),'progress':None,'error':None,'result':None}
        self.store.put('job',row,row['id']);self._start(row);return self.get(row['id'])
    def _start(self,row):
        job=Job(self,row);self.live[job.id]=job;job.save(status='queued',error=None)
        def run():
            try:
                job.save(status='running',error=None);result=self.runners[row['kind']](job);job.checkpoint();job.save(status='completed',result=result)
            except Cancelled:job.save(status='cancelled',error='Cancelled; task files retained')
            except Exception as exc:
                job.save(status='failed',error=redact(exc));self.store.log('error',f'{row["kind"]}: {exc}')
        job.thread=threading.Thread(target=run,daemon=True,name='job-'+job.id);job.thread.start()
    def action(self,id,action):
        with self.lock:
            row=self.get(id);job=self.live.get(id)
            if action=='pause':
                if row['kind']!='download' and row['kind']!='test':raise APIError('This task cannot safely pause','unsupported_capability',409)
                if not job or row['status']!='running':raise APIError('Job is not running','invalid_state',409)
                with job.condition:job.paused=True;job.save(status='paused')
            elif action=='cancel':
                if row['kind'] in ('activate','rollback'):raise APIError('An atomic engine switch cannot be cancelled','invalid_state',409)
                if job and job.thread.is_alive():
                    with job.condition:job.cancelled=True;job.paused=False;job.condition.notify_all()
                elif row['status'] not in ('completed','cancelled'):
                    row['status']='cancelled';self.store.put('job',row,id)
            elif action in ('resume','retry'):
                if job and job.thread.is_alive():
                    if row['status']!='paused':raise APIError('Job is already running','invalid_state',409)
                    with job.condition:job.paused=False;job.save(status='running');job.condition.notify_all()
                else:
                    if row['status'] not in ('failed','interrupted','cancelled','paused'):raise APIError('Job cannot resume','invalid_state',409)
                    self._start(row)
            else:raise APIError('Unknown job action')
            return self.get(id)
    def shutdown(self):
        self.closing=True
        for job in list(self.live.values()):
            if job.thread.is_alive() and job.row['kind'] not in ('activate','rollback'):
                with job.condition:job.cancelled=True;job.paused=False;job.condition.notify_all()
        for job in list(self.live.values()):job.thread.join(timeout=35)
