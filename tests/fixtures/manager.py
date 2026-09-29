import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'manager'))
from tfmanager.server import Application
from resources import FixtureGate
app=Application(sys.argv[1],sys.argv[1],'fixture-token',engine_command=[sys.executable,str(Path(__file__).with_name('engine.py'))],resource_factory=FixtureGate)
app.store.settings_update({'engine_port':int(sys.argv[2]),'gateway_port':int(sys.argv[3])})
app.start(0,check_updates=False)
print(json.dumps({'port':app.http.server_port}),flush=True)
app.closed.wait()
