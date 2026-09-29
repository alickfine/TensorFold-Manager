"""Launch trusted bundled management package with isolated Python (-I)."""
from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'manager'))
runpy.run_module('tfmanager.server', run_name='__main__')
