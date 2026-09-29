"""Own an engine Popen group and watch the manager pipe. Standalone stdlib helper."""
import json
import os
import queue
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from tfmanager.services import NativeInstances

def main():
    config=json.loads(sys.stdin.readline())
    lease_fd=config.get('lease_fd')
    if type(lease_fd) is not int or lease_fd<3:raise ValueError('An inherited resource lease is required')
    info=os.fstat(lease_fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('Invalid resource lease descriptor')
    live_fd=config.get('liveness_fd')
    if type(live_fd) is not int or live_fd<3 or not stat.S_ISFIFO(os.fstat(live_fd).st_mode):raise ValueError('Inherited liveness pipe required')
    child=subprocess.Popen(config['argv'],env=config['env'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True,bufsize=1,pass_fds=(lease_fd,live_fd))
    os.close(live_fd)
    events=queue.Queue()
    def emit(data):
        try: print(json.dumps(data),flush=True)
        except (BrokenPipeError,OSError): pass
    def logs():
        for line in child.stdout: emit({'log':line.rstrip()})
    def control():
        for line in sys.stdin:
            try: events.put(json.loads(line))
            except ValueError: continue
        events.put({'action':'stop'})
    threading.Thread(target=logs,daemon=True).start(); threading.Thread(target=control,daemon=True).start()
    try:
        native=NativeInstances();token=None;stable_since=time.monotonic();deadline=stable_since+2
        while time.monotonic()<deadline:
            if child.poll() is not None:raise RuntimeError('Engine exited before instance binding')
            current=native.bind(child.pid)
            if child.poll() is not None:raise RuntimeError('Engine exited during instance binding')
            if current!=token:token=current;stable_since=time.monotonic()
            elif time.monotonic()-stable_since>=.1:break
            time.sleep(.02)
        else:raise RuntimeError('Engine instance did not stabilize')
        emit({'pid':child.pid,'identity':token})
    except Exception:emit({'pid':child.pid,'error':'Engine instance binding unavailable; readiness is disabled'})
    stopping=None
    while child.poll() is None:
        try: event=events.get(timeout=.1)
        except queue.Empty: event={}
        if event.get('action') in ('stop','force'):
            try: os.killpg(child.pid, signal.SIGKILL if event['action']=='force' else signal.SIGTERM)
            except ProcessLookupError: pass
            if stopping is None: stopping=time.monotonic()
        if stopping is not None and time.monotonic()-stopping>config.get('stop_timeout',120):
            emit({'error':'Engine did not exit within graceful timeout; explicit force is required'})
            stopping=None # Keep supervising/reaping; never silently force-kill an engine.
    emit({'exit':child.returncode}); child.stdout.close()
if __name__=='__main__': main()
