import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.request
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
from tfmanager.downloads import Downloads, SafeRedirect
from tfmanager.state import Store, APIError
class Jobs:
 def register(self,*args): pass
 def create(self,kind,params): return params
class Credentials:
 def get(self,provider): return 'fixture-'+provider
class DownloadCredentialsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=Store(Path(self.tmp.name));self.addCleanup(self.store.close)
 def test_credentials_are_opt_in_and_mirror_rejects_before_job(self):
  downloads=Downloads(self.store,Jobs(),Credentials())
  self.assertFalse(downloads.create({'repo':'org/model'})['use_credentials'])
  params=downloads.create({'repo':'org/model','use_credentials':True})
  self.assertNotIn('token',json.dumps(params));self.assertTrue(params['use_credentials'])
  with self.assertRaises(APIError):downloads.create({'repo':'org/model','source':'hf-mirror','use_credentials':True})
  with self.assertRaises(APIError):downloads.create({'repo':'org/model','use_credentials':'true'})
 def test_secret_is_sent_only_to_exact_official_origin(self):
  downloads=Downloads(self.store,Jobs(),Credentials())
  params={'source':'huggingface','use_credentials':True}
  self.assertEqual(downloads.request_headers(params,'https://huggingface.co/org/model'),{'Authorization':'Bearer fixture-hf-download'})
  for url in ['https://huggingface.co.evil.test/model','https://cdn.huggingface.co/model','https://huggingface.co:443/model','https://hf-mirror.com/model']:
   with self.assertRaises(APIError):downloads.request_headers(params,url)
  self.assertEqual(downloads.request_headers({'source':'huggingface'},'https://huggingface.co/model'),{})
 def test_modelscope_cookie_is_explicit_official_and_not_redirected(self):
  downloads=Downloads(self.store,Jobs(),Credentials())
  headers=downloads.request_headers({'source':'modelscope','use_credentials':True},'https://modelscope.cn/api/v1/models/org/model')
  self.assertEqual(headers.get('Cookie'),'m_session_id=fixture-modelscope-download')
 def test_modelscope_branch_snapshot_pins_every_file_commit(self):
  downloads=Downloads(self.store,Jobs())
  payload={'Data':{'Files':[{'Path':'config.json','Size':2,'Sha256':'b'*64,'Revision':'a'*40,'Type':'blob'},{'Path':'weights.safetensors','Size':3,'Sha256':'d'*64,'Revision':'c'*40,'Type':'blob'}]}}
  with patch('tfmanager.downloads.public_json',return_value=payload):
   manifest=downloads.metadata({'repo':'org/model','source':'modelscope','revision':'master'})
  self.assertEqual(manifest['revision_kind'],'file_manifest_sha256')
  self.assertEqual(manifest['files'][0]['revision'],'a'*40)
  self.assertIn('Revision='+('c'*40),manifest['files'][1]['url'])
  self.assertNotIn('Revision=master',str(manifest))
 def test_redirect_strips_credentials_even_same_origin(self):
  req=urllib.request.Request('https://huggingface.co/model',headers={'Authorization':'Bearer fixture-secret','Cookie':'private','Range':'bytes=2-'})
  result=SafeRedirect().redirect_request(req,None,302,'',{},'https://huggingface.co/other')
  self.assertIsNone(result.get_header('Authorization'));self.assertIsNone(result.get_header('Cookie'));self.assertEqual(result.get_header('Range'),'bytes=2-')
 def test_metadata_uses_opt_in_secret_without_persisting_it(self):
  downloads=Downloads(self.store,Jobs(),Credentials())
  payload={'sha':'a'*40,'siblings':[{'rfilename':'config.json','size':2,'blobId':'b'*40}]}
  with patch('tfmanager.downloads.public_json',return_value=payload) as get:
   manifest=downloads.metadata({'repo':'org/model','source':'huggingface','revision':'main','use_credentials':True})
  self.assertEqual(get.call_args.kwargs['headers'],{'Authorization':'Bearer fixture-hf-download'})
  self.assertNotIn('fixture-hf-download',json.dumps(manifest))
if __name__=='__main__':unittest.main()
