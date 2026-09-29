"""Controlled upstream CLI fixture; never shipped in the application."""
import argparse,json,os,sys,time
from http.server import BaseHTTPRequestHandler,HTTPServer
if '--version' in sys.argv:
 print('tensorfold 0.0.1'); sys.exit()
if '--help' in sys.argv:
 print('--host --port --name --context --max-tokens --temperature --top-p --top-k --parallel --thinking --no-thinking --snapshot-dir --prompt-cache-gib --mlx-cache-gib --no-update-check --drafter --drafter-bits --mtp-drafts --mtp-confidence --no-drafts --checkpoint-slots --spill-gib --max-snapshots --reasoning-effort --thinking-budget'); sys.exit()
if len(sys.argv)>2 and sys.argv[1]=='info':
 from pathlib import Path
 marker=Path(sys.argv[2])/'reject-info'
 if marker.exists():
  print(marker.read_text(),file=sys.stderr);sys.exit(2)
 backend=Path(sys.argv[2])/'fixture-readers'
 print('runs on      '+(backend.read_text() if backend.exists() else 'Apple Silicon (MLX)'));sys.exit()
parser=argparse.ArgumentParser(); parser.add_argument('serve'); parser.add_argument('model'); parser.add_argument('--port',type=int); parser.add_argument('--name',default='fixture'); args,_=parser.parse_known_args()
if 'fail-model' in args.model: sys.exit(7)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def record_request(self):
  from pathlib import Path
  log=Path(args.model)/'fixture-request-log'
  if log.is_file():
   with log.open('a') as stream:stream.write(self.command+' '+self.path+'\n')
 def do_GET(self):
  self.record_request()
  if self.path=='/health':
   from pathlib import Path
   marker=Path(args.model)/'fixture-health-model'
   model=marker.read_text() if marker.is_file() else args.name
   data=json.dumps({'status':'ok','model':model,'model_ids':[model],'warming':False,'max_batch_size':2,'memory':{'active':1048576,'cache':2097152,'peak':3145728}}).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
  data=json.dumps({'object':'list','data':[{'id':args.name,'object':'model'}],'fixture_mtp_source':os.environ.get('TF_NEMOTRON_MTP')}).encode(); self.send_response(200); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
 def do_POST(self):
  self.record_request()
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  if body.get('stream'):
   prompt=str(body.get('messages'))
   self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
   if 'slow' in prompt: time.sleep(5)
   if 'error-event' in prompt:
    self.wfile.write(b'data: {"error":{"message":"engine inference failed"}}\n\ndata: [DONE]\n\n');return
   for item in [{'choices':[{'delta':{'content':'ok'}}]}, {'choices':[],'usage':{'prompt_tokens':2,'completion_tokens':1}}]:
    self.wfile.write(('data: '+json.dumps(item)+'\n\n').encode()); self.wfile.flush(); time.sleep(.02)
   if 'incomplete' not in prompt:self.wfile.write(b'data: [DONE]\n\n')
  else:
   data=json.dumps({'id':'fixture','choices':[{'message':{'role':'assistant','content':'ok'}}],'usage':{'prompt_tokens':2,'completion_tokens':1}}).encode(); self.send_response(200); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
from pathlib import Path
exit_marker=Path(args.model)/'fixture-exit-after'
if exit_marker.is_file():
 import threading
 threading.Timer(float(exit_marker.read_text()),lambda:os._exit(0)).start()
if (Path(args.model)/'fixture-no-listen').is_file():time.sleep(10);sys.exit()
HTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
