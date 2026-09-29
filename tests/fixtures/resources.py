"""Deterministic resource boundary for tiny test-only engine processes."""
import time
from tfmanager.resources import ResourceGate,GIB
class Observer:
 def capture(self):return {'at':time.time(),'memory':{'physical_bytes':256*GIB,'available_bytes':240*GIB,'pressure':'normal','swap_used_bytes':0,'missing':[]},'services':[],'missing':[]}
 def identity(self,pid):return None
class FixtureGate(ResourceGate):
 def __init__(self,store):super().__init__(store,observer=Observer(),lock_dir=store.root/'test-resource-locks')
 def estimate(self,path,settings,kind='inference'):return {'required_bytes':GIB,'components':{'fixture_only_bytes':GIB},'missing':[],'kind':kind,'method':'test-fixture-only'}
