"""Explicit external stop/switch using kernel-bound instances, never bare PID signals."""
import ctypes
import errno
import os
import platform
import secrets
import signal
import socket
import threading
import time
from .state import APIError
from .resources import ResourceBlocked

class AuditToken(ctypes.Structure):
    _fields_=[('val',ctypes.c_uint32*8)]

class NativeInstances:
    """All token data is private memory. No token or process environment is serialized."""
    def __init__(self):
        self.reason=None
        try:
            if platform.system()!='Darwin':raise OSError('Instance-bound signals require macOS')
            self.lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
            self.lib.task_name_for_pid.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.POINTER(ctypes.c_uint32)];self.lib.task_name_for_pid.restype=ctypes.c_int
            self.lib.task_info.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_uint32)];self.lib.task_info.restype=ctypes.c_int
            self.lib.mach_port_deallocate.argtypes=[ctypes.c_uint32,ctypes.c_uint32];self.lib.mach_port_deallocate.restype=ctypes.c_int
            self.lib.proc_signal_with_audittoken.argtypes=[ctypes.POINTER(AuditToken),ctypes.c_int];self.lib.proc_signal_with_audittoken.restype=ctypes.c_int
            self.lib.proc_pidpath_audittoken.argtypes=[ctypes.POINTER(AuditToken),ctypes.c_void_p,ctypes.c_uint32];self.lib.proc_pidpath_audittoken.restype=ctypes.c_int
            self.self_port=ctypes.c_uint32.in_dll(self.lib,'mach_task_self_').value
        except (OSError,AttributeError,ValueError):self.reason='Kernel instance binding is unavailable; external stop is disabled'
    def bind(self,pid):
        if self.reason:raise APIError(self.reason,'external_control_unavailable',409)
        port=ctypes.c_uint32();token=AuditToken();count=ctypes.c_uint32(8)
        if self.lib.task_name_for_pid(self.self_port,pid,ctypes.byref(port))!=0:raise APIError('Cannot obtain a process-instance name right','external_control_unavailable',409)
        try:
            result=self.lib.task_info(port.value,15,token.val,ctypes.byref(count))
            if result or count.value!=8:raise APIError('Cannot bind the OS process instance','external_control_unavailable',409)
            # XNU audit token fields: effective UID, real UID, PID, PID version.
            if token.val[1]!=os.getuid() or token.val[3]!=os.getuid() or token.val[5]!=pid:raise APIError('Process identity is outside this user','external_control_unavailable',409)
            return tuple(token.val)
        finally:self.lib.mach_port_deallocate(self.self_port,port.value)
    @staticmethod
    def _token(values):return AuditToken((ctypes.c_uint32*8)(*values))
    def alive(self,values):
        token=self._token(values);buffer=ctypes.create_string_buffer(4096);ctypes.set_errno(0)
        result=self.lib.proc_pidpath_audittoken(ctypes.byref(token),buffer,len(buffer))
        if result>0:return True
        error=ctypes.get_errno()
        if error in (errno.ESRCH,errno.ENOENT):return False
        raise APIError('Cannot prove the original process instance exited','instance_exit_unknown',409)
    def terminate(self,values):
        token=self._token(values);ctypes.set_errno(0)
        if self.lib.proc_signal_with_audittoken(ctypes.byref(token),signal.SIGTERM)!=0:
            raise APIError('Kernel refused the instance-bound SIGTERM; no PID fallback was attempted','instance_signal_failed',409)

class Services:
    TTL=30
    def __init__(self,store,jobs,engine,resources,native=None,clock=time.monotonic,timeout=120):
        self.store=store;self.jobs=jobs;self.engine=engine;self.resources=resources;self.native=native or NativeInstances();self.clock=clock;self.timeout=timeout
        self.lock=threading.RLock();self.snapshots={};jobs.register('service_switch',self.run_switch)
    @staticmethod
    def same(left,right):
        return bool(right) and all(left.get(k)==right.get(k) for k in ('pid','uid','kind','executable','start_time','command_signature','model_path','listening_ports','port','model_ids')) and bool(right.get('argv_verified')) and (left.get('health') or {}).get('model')==(right.get('health') or {}).get('model') and (right.get('health') or {}).get('warming') is not True and (right.get('health') or {}).get('status') in ('ok','ready','healthy')
    def _prune(self):
        now=self.clock()
        for key,value in list(self.snapshots.items()):
            if value['expires']<=now:self.snapshots.pop(key,None)
        while len(self.snapshots)>128:self.snapshots.pop(next(iter(self.snapshots)))
    def list(self):
        snapshot=self.resources.snapshot(fresh=True);rows=[]
        for service in snapshot.get('services',[]):
            row={k:service.get(k) for k in ('pid','uid','kind','executable','start_time','model_path','port','listening_ports','health','model_ids')};reason=None;token=None
            if service.get('uid')!=os.getuid() or service.get('kind') not in ('tensorfold','omlx'):reason='Only recognized same-user inference services can be controlled'
            elif not service.get('argv_verified') or not service.get('listening_ports') or (service.get('health') or {}).get('status') not in ('ok','ready','healthy') or (service.get('health') or {}).get('warming') is True:reason='Current arguments, listening endpoint and health must be verified'
            elif self.engine.data.get('control_owner')=='manager' and self.engine.data.get('pid')==service['pid']:reason='Use the owned engine lifecycle controls'
            else:
                try:
                    token=self.native.bind(service['pid']);current=self.resources.observer.identity(service['pid'])
                    if not self.same(service,current) or self.native.bind(service['pid'])!=token:raise APIError('Service identity changed while binding snapshot')
                except APIError as exc:reason=str(exc)
            row['control']={'supported':reason is None,'action':'stop_and_switch' if reason is None else None,'reason':reason};row['snapshot_id']=None;row['expires_in_seconds']=None
            if reason is None:
                key=secrets.token_urlsafe(24)
                with self.lock:
                    self._prune();self.snapshots[key]={'service':service,'token':token,'expires':self.clock()+self.TTL}
                row.update(snapshot_id=key,expires_in_seconds=self.TTL)
            rows.append(row)
        return {'services':rows,'resources':snapshot,'confirmation_required':True}
    def switch(self,data):
        if not isinstance(data,dict) or set(data)!={'snapshot_id','model','confirm'} or data.get('confirm') is not True or not isinstance(data.get('snapshot_id'),str) or not isinstance(data.get('model'),str):raise APIError('Explicit snapshot, target model and confirmation required')
        with self.lock:
            self._prune();snapshot=self.snapshots.get(data['snapshot_id'])
            if not snapshot:raise APIError('Service snapshot expired; refresh and confirm again','service_snapshot_expired',409)
            if snapshot.get('claimed'):raise APIError('This service snapshot was already confirmed','service_snapshot_used',409)
            self.engine.models.resolve(data['model']);snapshot['claimed']=True
        return self.jobs.create('service_switch',{'snapshot_id':data['snapshot_id'],'model':data['model']})
    @staticmethod
    def endpoints_down(service):
        for port in service['listening_ports']:
            with socket.socket() as sock:
                sock.settimeout(.25)
                if sock.connect_ex(('127.0.0.1',port))==0:return False
        return True
    def run_switch(self,job):
        with self.lock:
            snapshot=self.snapshots.pop(job.params['snapshot_id'],None)
        if not snapshot or snapshot['expires']<=self.clock():raise APIError('Service snapshot expired; no signal sent','service_snapshot_expired',409)
        service=snapshot['service'];token=snapshot['token'];lease=None;handed=False
        with self.engine.lifecycle:
            try:
                row,settings,effective=self.engine.prepare_start(job.params['model'])
                estimate=self.resources.estimate(row['path'],effective)
                if estimate['missing'] or estimate['required_bytes'] is None:raise ResourceBlocked({'allowed':False,'estimate':estimate,'missing':estimate['missing'],'blockers':['unknown_target_budget']},'Target model has no defensible memory budget; current service left running')
                self.engine.build_command(row,effective) # Verify actual CLI/model before stopping a working service.
                if self.engine.proc and self.engine.proc.poll() is None:raise APIError('Stop the manager-owned engine before switching an external service','engine_busy',409)
                if self.engine.attachment and self.engine.attachment['pid']!=service['pid']:raise APIError('Detach the other external service first','engine_busy',409)
                self.engine.drain()
                if self.engine.attachment:self.engine.detach()
                lease=self.resources.acquire_switch()
                current=self.resources.observer.identity(service['pid'])
                if self.clock()>=snapshot['expires'] or not self.same(service,current) or self.native.bind(service['pid'])!=token:raise APIError('Service changed or confirmation expired; no signal sent','service_identity_changed',409)
                job.checkpoint();job.progress(phase='stopping_confirmed_instance',service_pid=service['pid'])
                if self.clock()>=snapshot['expires'] or not self.same(service,self.resources.observer.identity(service['pid'])) or self.native.bind(service['pid'])!=token:raise APIError('Service identity or confirmation changed before signal','service_identity_changed',409)
                self.native.terminate(token)
                deadline=self.clock()+self.timeout;report=None
                while self.clock()<deadline:
                    job.checkpoint()
                    exited=not self.native.alive(token);down=self.endpoints_down(service)
                    if exited and down:
                        report=self.resources.preflight_start(row['path'],effective)
                        if report['allowed'] and report['attachment'] is None:break
                    job.progress(phase='waiting_for_release',original_instance_exited=exited,endpoints_down=down,resources=report)
                    time.sleep(.2)
                else:raise APIError('Timed out waiting for the original instance, endpoints and memory to release; no force signal or replacement process was targeted','resource_release_timeout',409)
                job.checkpoint();job.progress(phase='starting_target',resources=report)
                self.engine.start(job.params['model'],allow_attach=False,_lease=lease);handed=True
                self.engine.await_ready();return {'engine':self.engine.status(),'previous_instance_exited':True,'resources':report}
            finally:
                if lease and not handed:lease.release()
                if not handed:self.engine.draining=False
