"""Connect without HTTP bytes, prove accepted socket ownership, then permit one connection."""
import http.client
import subprocess
import time
from .state import APIError,clean_env

def accepted_tuple(raw,pid,server,client):
    expected=f'{server[0]}:{server[1]}->{client[0]}:{client[1]}'.encode();owner=None;record={}
    def matches():return owner==pid and record.get(b'n')==expected and record.get(b'T')==b'ST=ESTABLISHED'
    for field in raw.split(b'\0'):
        field=field.lstrip(b'\n')
        if not field:continue
        kind,value=field[:1],field[1:]
        if kind in (b'p',b'f'):
            if matches():return True
            record={}
            if kind==b'p':
                try:owner=int(value)
                except ValueError:owner=None
        if kind in (b'n',b'T'):
            if kind==b'T' and not value.startswith(b'ST='):continue
            record[kind]=value
    return matches()

def owns_accepted_socket(pid,server,client):
    result=subprocess.run(['/usr/sbin/lsof','-nP','-a','-p',str(pid),'-iTCP','-sTCP:ESTABLISHED','-F0pfnT'],capture_output=True,timeout=.5,env=clean_env())
    if result.returncode not in (0,1):raise APIError('Accepted socket ownership probe failed','peer_unverified',503)
    return accepted_tuple(result.stdout,pid,server,client)

class BoundHTTPConnection(http.client.HTTPConnection):
    def __init__(self,port,pid,token,*,timeout=600,native=None,probe=None,verify_timeout=1):
        super().__init__('127.0.0.1',port,timeout=timeout)
        if native is None:
            from .services import NativeInstances
            native=NativeInstances()
        self.pid=pid;self.token=token;self.native=native;self.probe=probe or owns_accepted_socket;self.verify_timeout=verify_timeout;self.connected_once=False
    def connect(self):
        if self.connected_once:raise APIError('Verified upstream connection cannot reconnect','peer_unverified',503)
        self.connected_once=True
        try:
            if not self.token or self.native.bind(self.pid)!=self.token:raise APIError('Upstream process instance changed','peer_unverified',503)
            super().connect() # TCP handshake only: no health, headers or prompts have been sent.
            client=self.sock.getsockname()[:2];server=self.sock.getpeername()[:2];deadline=time.monotonic()+self.verify_timeout
            while True:
                if self.probe(self.pid,server,client):break
                if time.monotonic()>=deadline:raise APIError('Target process has not accepted this exact connection','peer_unverified',503)
                time.sleep(.02)
            if self.native.bind(self.pid)!=self.token or self.sock.getsockname()[:2]!=client or self.sock.getpeername()[:2]!=server:raise APIError('Upstream identity changed during connection verification','peer_unverified',503)
        except Exception:
            self.close();raise
