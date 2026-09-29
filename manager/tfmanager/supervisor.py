"""Own an engine Popen group and watch the manager pipe. Standalone stdlib helper."""
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time

def main():
    config=json.loads(sys.stdin.readline())
    child=subprocess.Popen(config['argv'],env=config['env'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True,bufsize=1)
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
    emit({'pid':child.pid}); stopping=None
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
