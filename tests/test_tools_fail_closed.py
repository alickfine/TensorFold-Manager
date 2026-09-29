import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'manager'))
import test_tools as fixtures
from tfmanager.tools import Tools
from tfmanager.state import APIError
class ToolGateTests(unittest.TestCase):
 setUp=fixtures.ToolTests.setUp
 def test_missing_resource_coordinator_cannot_create_quantize_job(self):
  tools=Tools(self.store,self.jobs,self.engine,self.models,fixtures.FakeCredentials())
  with self.assertRaisesRegex(APIError,'coordinator'):
   tools.quantize({'model':str(self.model),'bits':4,'group_size':64,'mode':'affine'})
  self.assertFalse(self.jobs.list())
 def test_missing_os_lease_descriptor_cannot_enter_heavy_runner(self):
  resources=SimpleNamespace(preflight_quantize=lambda *a,**kw:{'allowed':True},acquire_quantize=lambda *a,**kw:self.engine.lifecycle)
  tools=Tools(self.store,self.jobs,self.engine,self.models,fixtures.FakeCredentials(),resources=resources)
  with self.assertRaisesRegex(APIError,'lease'):
   tools._quantize_lease(str(self.model),{})
if __name__=='__main__':unittest.main()
