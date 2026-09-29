import http.client
import json,os,socket,sys,threading,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
from tfmanager.state import APIError
try:
 from tfmanager.peer import BoundHTTPConnection,accepted_tuple
except ImportError:BoundHTTPConnection=None;accepted_tuple=None
class PeerTests(unittest.TestCase):
 def test_lsof_parser_requires_pid_established_and_full_reverse_tuple(self):
  self.assertIsNotNone(accepted_tuple)
  raw=b'p42\0\nf8\0tIPv4\0n127.0.0.1:9000->127.0.0.1:54321\0TST=ESTABLISHED\0\n'
  self.assertTrue(accepted_tuple(raw,42,('127.0.0.1',9000),('127.0.0.1',54321)))
  for bad in (raw.replace(b'p42',b'p43'),raw.replace(b'ESTABLISHED',b'LISTEN'),raw.replace(b'54321',b'54322')):self.assertFalse(accepted_tuple(bad,42,('127.0.0.1',9000),('127.0.0.1',54321)))
 def capture_server(self):
  listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();received=[];accepted=threading.Event()
  def run():
   connection,_=listener.accept();accepted.set();connection.settimeout(1)
   try:received.append(connection.recv(8192))
   except OSError:received.append(b'')
   finally:connection.close()
  worker=threading.Thread(target=run);worker.start();self.addCleanup(listener.close);self.addCleanup(lambda:worker.join(timeout=2))
  return listener,received,accepted
 def test_identity_replacement_after_connect_sends_zero_http_bytes(self):
  self.assertIsNotNone(BoundHTTPConnection);listener,received,event=self.capture_server();native=Mock();native.bind.side_effect=[('old',),('new',)]
  conn=BoundHTTPConnection(listener.getsockname()[1],42,('old',),native=native,probe=lambda *a:True)
  with self.assertRaises(APIError):conn.request('POST','/v1/chat/completions',b'PRIVATE PROMPT')
  conn.close();event.wait(1);time.sleep(.02);self.assertEqual(b''.join(received),b'')
 def test_probe_failure_sends_zero_bytes_for_stream_and_nonstream(self):
  for stream in (False,True):
   self.assertIsNotNone(BoundHTTPConnection);listener,received,event=self.capture_server();native=Mock();native.bind.return_value=('old',)
   conn=BoundHTTPConnection(listener.getsockname()[1],42,('old',),native=native,probe=lambda *a:False,verify_timeout=.03)
   with self.assertRaises(APIError):conn.request('POST','/v1/chat/completions',json.dumps({'stream':stream,'messages':['PRIVATE']}))
   conn.close();event.wait(1);time.sleep(.02);self.assertEqual(b''.join(received),b'')
 def test_verified_connection_never_reconnects(self):
  self.assertIsNotNone(BoundHTTPConnection);listener,received,event=self.capture_server();native=Mock();native.bind.return_value=('old',)
  conn=BoundHTTPConnection(listener.getsockname()[1],42,('old',),native=native,probe=lambda *a:True);conn.connect();conn.close()
  with self.assertRaises(APIError):conn.request('POST','/v1/chat/completions',b'PRIVATE')
  event.wait(1);time.sleep(.02);self.assertEqual(b''.join(received),b'')

 def test_old_peer_exit_and_new_listener_never_receives_prompt(self):
  listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
  peer=[];accepted=threading.Event()
  def accept():peer.append(listener.accept()[0]);accepted.set()
  thread=threading.Thread(target=accept);thread.start();native=Mock();native.bind.return_value=('old',)
  connection=BoundHTTPConnection(port,42,('old',),native=native,probe=lambda *a:True);connection.connect();accepted.wait(1);thread.join()
  peer[0].shutdown(socket.SHUT_RDWR);peer[0].close();listener.close()
  replacement=socket.socket();replacement.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);replacement.bind(('127.0.0.1',port));replacement.listen();replacement.settimeout(.1)
  try:
   try:connection.request('POST','/v1/chat/completions',b'PRIVATE PROMPT');connection.getresponse()
   except (OSError,APIError,http.client.HTTPException):pass
   with self.assertRaises(socket.timeout):replacement.accept()
   connection.close()
   with self.assertRaises(APIError):connection.request('POST','/v1/chat/completions',b'PRIVATE PROMPT')
   with self.assertRaises(socket.timeout):replacement.accept()
  finally:connection.close();replacement.close()

 def test_missing_audit_capability_sends_nothing(self):
  native=Mock();native.bind.side_effect=APIError('OS audit unavailable')
  connection=BoundHTTPConnection(9999,42,('old',),native=native)
  with patch('http.client.HTTPConnection.connect') as connect:
   with self.assertRaises(APIError):connection.request('POST','/v1/chat/completions',b'PRIVATE')
   connect.assert_not_called()
