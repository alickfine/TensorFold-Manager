import hashlib,json,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
from tfmanager.state import Store,APIError
try:
 from tfmanager.jobs import Jobs
 from tfmanager.downloads import Downloads, safe_target
 from tfmanager.updates import Updates
except ImportError: Jobs=None
class TaskTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(Jobs,'task layer missing')
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=Store(self.tmp.name);self.addCleanup(self.store.close)
  self.jobs=Jobs(self.store);self.addCleanup(self.jobs.shutdown)
 def test_job_failure_resume_and_persist(self):
  def run(job):
   for i in range(30):job.checkpoint();time.sleep(.01)
   return {'value':42}
  self.jobs.register('test',run); job=self.jobs.create('test',{})
  self.jobs.action(job['id'],'pause');time.sleep(.03);self.assertEqual(self.jobs.get(job['id'])['status'],'paused')
  self.jobs.action(job['id'],'resume')
  for _ in range(100):
   if self.jobs.get(job['id'])['status']=='completed':break
   time.sleep(.01)
  self.assertEqual(self.jobs.get(job['id'])['result'],{'value':42})
 def test_cancel_retains_partial_files(self):
  partial=Path(self.tmp.name)/'partial';partial.write_text('data')
  def run(job):
   while True:job.checkpoint();time.sleep(.01)
  self.jobs.register('test',run);job=self.jobs.create('test',{});self.jobs.action(job['id'],'cancel');time.sleep(.03)
  self.assertEqual(partial.read_text(),'data');self.assertEqual(self.jobs.get(job['id'])['status'],'cancelled')
 def test_download_rejects_traversal_symlink_and_unknown_source(self):
  root=Path(self.tmp.name)/'downloads';root.mkdir(); (root/'link').symlink_to('/tmp')
  for name in ('../escape','/tmp/file','link/file'):
   with self.assertRaises(APIError):safe_target(root,name)
  downloads=Downloads(self.store,self.jobs)
  for data in ({'repo':'x/y','source':'unknown'}, {'repo':'x/../y','source':'huggingface'}, {'repo':'x/y','directory':'/tmp/unspecified-scope'}):
   with self.assertRaises(APIError):downloads.create(data)
 def test_download_verifies_actual_content_before_publish(self):
  downloads=Downloads(self.store,self.jobs)
  good=Path(self.tmp.name)/'data';good.write_bytes(b'hello')
  downloads.verify_file(good,{'size':5,'sha256':hashlib.sha256(b'hello').hexdigest()})
  with self.assertRaises(APIError): downloads.verify_file(good,{'size':5,'sha256':'0'*64})
 def test_update_version_rejects_untrusted_inputs(self):
  for version in ('main','../main','https://evil.invalid/x','v1.0;id'):
   with self.assertRaises(APIError):Updates.validate_version(version)
  self.assertEqual(Updates.validate_version('v0.3.5.1'),'v0.3.5.1')

class DownloadFlowTests(unittest.TestCase):
 setUp=TaskTests.setUp
 def test_download_resume_pin_hash_and_private_staging(self):
  import io,os
  from unittest.mock import patch
  downloads=Downloads(self.store,self.jobs);content=b'hello actual bytes';commit='a'*40
  manifest={'sha':commit,'siblings':[{'rfilename':'config.json','size':len(content),'lfs':{'size':len(content),'sha256':hashlib.sha256(content).hexdigest()}}]}
  class Response(io.BytesIO):
   status=200;headers={}
  with patch('tfmanager.downloads.public_json',return_value=manifest),patch('tfmanager.downloads.public_open',side_effect=lambda *a,**kw:Response(content)):
   job=downloads.create({'repo':'owner/model','source':'huggingface','revision':'main'})
   for _ in range(100):
    row=self.jobs.get(job['id'])
    if row['status'] in ('completed','failed'):break
    time.sleep(.01)
  self.assertEqual(row['status'],'completed',row)
  output=Path(row['result']['path'])/'config.json';self.assertEqual(output.read_bytes(),content)
  self.assertEqual(row['result']['revision'],commit)
  self.assertEqual(output.stat().st_mode&0o777,0o600)
  self.assertEqual((downloads.root/'.tfmanager-partials').stat().st_mode&0o777,0o700)
 def test_failed_hash_never_publishes_or_removes_external_files(self):
  import io
  from unittest.mock import patch
  downloads=Downloads(self.store,self.jobs);sentinel=downloads.root/'existing.safetensors';sentinel.write_bytes(b'external')
  manifest={'sha':'b'*40,'siblings':[{'rfilename':'config.json','lfs':{'size':3,'sha256':'0'*64}}]}
  class Response(io.BytesIO):status=200;headers={}
  with patch('tfmanager.downloads.public_json',return_value=manifest),patch('tfmanager.downloads.public_open',side_effect=lambda *a,**kw:Response(b'bad')):
   job=downloads.create({'repo':'owner/model'})
   for _ in range(100):
    row=self.jobs.get(job['id'])
    if row['status']=='failed':break
    time.sleep(.01)
  self.assertEqual(row['status'],'failed');self.assertIn('identity mismatch',row['error']);self.assertEqual(sentinel.read_bytes(),b'external')
  self.assertTrue((downloads.root/'.tfmanager-partials'/job['id']/'content/config.json').exists())

class DownloadRetryTests(unittest.TestCase):
 setUp=TaskTests.setUp
 def test_retry_redownloads_owned_corrupt_partial(self):
  import io
  from unittest.mock import patch
  downloads=Downloads(self.store,self.jobs);correct=b'yes';manifest={'sha':'c'*40,'siblings':[{'rfilename':'config.json','lfs':{'size':3,'sha256':hashlib.sha256(correct).hexdigest()}}]}
  class Response(io.BytesIO):status=200;headers={}
  with patch('tfmanager.downloads.public_json',return_value=manifest),patch('tfmanager.downloads.public_open',side_effect=lambda *a,**kw:Response(b'bad')):
   job=downloads.create({'repo':'owner/model'})
   for _ in range(100):
    if self.jobs.get(job['id'])['status']=='failed':break
    time.sleep(.01)
  self.assertEqual(self.jobs.get(job['id'])['status'],'failed')
  with patch('tfmanager.downloads.public_open',side_effect=lambda *a,**kw:Response(correct)):
   self.jobs.action(job['id'],'retry')
   for _ in range(100):
    row=self.jobs.get(job['id'])
    if row['status'] in ('completed','failed'):break
    time.sleep(.01)
  self.assertEqual(row['status'],'completed',row)

class EmptyFileTests(unittest.TestCase):
 setUp=TaskTests.setUp
 def test_empty_repository_file_is_verified_and_published(self):
  from unittest.mock import patch
  downloads=Downloads(self.store,self.jobs)
  manifest={'sha':'e'*40,'siblings':[{'rfilename':'empty.txt','size':0,'blobId':hashlib.sha1(b'blob 0\0').hexdigest()}]}
  with patch('tfmanager.downloads.public_json',return_value=manifest):
   job=downloads.create({'repo':'owner/model'})
   for _ in range(100):
    row=self.jobs.get(job['id'])
    if row['status'] in ('completed','failed'):break
    time.sleep(.01)
  self.assertEqual(row['status'],'completed',row)
  self.assertEqual((Path(row['result']['path'])/'empty.txt').read_bytes(),b'')

class InstallerEnvironmentTests(unittest.TestCase):
 setUp=TaskTests.setUp
 def test_installer_cannot_read_ambient_home_credentials(self):
  from tfmanager.jobs import Job
  updates=Updates(self.store,self.jobs,None);output=Path(self.tmp.name)/'installer-environment.json'
  job=Job(self.jobs,{'id':'env-test','params':{}})
  updates._command([sys.executable,'-c','import json,os,sys;open(sys.argv[1],"w").write(json.dumps({k:os.environ.get(k) for k in ("HOME","PYTHONNOUSERSITE","PYTHONDONTWRITEBYTECODE","TFM_ADMIN_TOKEN")}))',str(output)],job)
  env=json.loads(output.read_text());self.assertTrue(Path(env['HOME']).is_relative_to(self.store.root));self.assertEqual(env['PYTHONNOUSERSITE'],'1');self.assertEqual(env['PYTHONDONTWRITEBYTECODE'],'1');self.assertIsNone(env['TFM_ADMIN_TOKEN'])


class BytecodeSafetyTests(unittest.TestCase):
 def test_clean_child_import_does_not_mutate_source_tree(self):
  import subprocess
  from tfmanager.state import clean_env
  with tempfile.TemporaryDirectory() as root:
   source=Path(root)/'bundle_module.py';source.write_text('value=42')
   result=subprocess.run([sys.executable,'-c','import sys;sys.path.insert(0,sys.argv[1]);import bundle_module;print(bundle_module.value)',root],env=clean_env(),capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr);self.assertFalse((Path(root)/'__pycache__').exists())
