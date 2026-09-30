"""Private SQLite persistence and validation. No credentials are returned by settings."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid

ADVANCED_OPTIONS = {key: None for key in ('drafter','drafter_bits','mtp_drafts','mtp_confidence','no_drafts','checkpoint_slots','spill_gib','max_snapshots','reasoning_effort','thinking_budget','name')}

class APIError(Exception):
    def __init__(self, message, code='invalid_request', status=400):
        super().__init__(message); self.code=code; self.status=status
    def payload(self):
        return {'error':{'message':str(self),'code':self.code}}

def clean_env():
    # Allow-list avoids leaking provider keys, manager auth, Python injection or proxy credentials.
    env={k:v for k,v in os.environ.items() if k in ('HOME','USER','LOGNAME','TMPDIR','LANG','LC_ALL','SYSTEMROOT')}
    env['PATH']='/usr/bin:/bin:/usr/sbin:/sbin'
    env['PYTHONUNBUFFERED']='1';env['PYTHONNOUSERSITE']='1';env['PYTHONDONTWRITEBYTECODE']='1'
    return env

def redact(message):
    message=re.sub(r'(?i)(bearer\s+)[^\s,;]+',r'\1[REDACTED]',str(message))
    message=re.sub(r'(?:tfm_live_|hf_)[A-Za-z0-9_\-]+','[REDACTED]',message)
    return re.sub(r'(?i)((?:token|password|api[_-]?key)\s*[=:]\s*)[^\s,;]+',r'\1[REDACTED]',message)

def identifier(value, name='id'):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',value) or '..' in value:
        raise APIError(f'Invalid {name}')
    return value

def repo_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*',value) or '..' in value:
        raise APIError('Expected an exact owner/model repository id')
    return value

def bounded_number(value, low, high, name, integer=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high or (integer and not isinstance(value,int)):
        raise APIError(f'{name} must be between {low} and {high}')
    return value

class Store:
    def __init__(self, root):
        self.root=Path(root).expanduser().resolve(); self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        os.chmod(self.root,0o700)
        self.lock=threading.RLock()
        self.db=sqlite3.connect(self.root/'state.sqlite3',check_same_thread=False)
        os.chmod(self.root/'state.sqlite3',0o600)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS documents (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS keys (id TEXT PRIMARY KEY,name TEXT,hash TEXT,created_at REAL,expires_at REAL,enabled INTEGER);
        CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY,at REAL,model TEXT,body TEXT);
        CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY,at REAL,level TEXT,message TEXT);
        ''')
        self.db.commit()
        self.snapshots=self.root/'snapshots'; self.snapshots.mkdir(exist_ok=True,mode=0o700)
        marker=self.snapshots/'.tfmanager-owned'
        if not marker.exists(): marker.write_text('TensorFold Manager snapshots v1\n')
    def close(self):
        with self.lock: self.db.close()
    def get(self,kind,id='default',default=None):
        with self.lock:
            row=self.db.execute('SELECT body FROM documents WHERE kind=? AND id=?',(kind,id)).fetchone()
            return json.loads(row[0]) if row else default
    def put(self,kind,body,id='default'):
        with self.lock,self.db:
            self.db.execute('INSERT OR REPLACE INTO documents VALUES (?,?,?)',(kind,id,json.dumps(body,allow_nan=False)))
        return body
    def all(self,kind):
        with self.lock:
            return [json.loads(x[0]) for x in self.db.execute('SELECT body FROM documents WHERE kind=? ORDER BY rowid DESC',(kind,))]
    def delete(self,kind,id):
        with self.lock,self.db: self.db.execute('DELETE FROM documents WHERE kind=? AND id=?',(kind,id))
    def defaults(self):
        return dict(selected_model=None,engine_python=None,model_dirs=[str(self.root/'models'),str(Path.home()/'.cache/huggingface/hub'),str(Path.home()/'.omlx/models')],engine_port=18080,gateway_port=8080,context=32768,max_tokens=4096,temperature=0.6,top_p=0.95,top_k=20,parallel='auto',thinking=True,prompt_cache_gib=4.0,mlx_cache_gib=8.0,snapshot_dir=str(self.snapshots)) | ADVANCED_OPTIONS
    def settings(self):
        return self.defaults() | self.get('settings',default={})
    def validate_settings(self, values):
        if not isinstance(values,dict): raise APIError('Settings must be an object')
        if set(values)-set(self.defaults()): raise APIError('Unknown settings: '+', '.join(sorted(set(values)-set(self.defaults()))))
        result={}
        ranges={'engine_port':(1024,65535,True),'gateway_port':(1024,65535,True),'context':(1,2097152,True),'max_tokens':(1,2097152,True),'temperature':(0,5,False),'top_p':(0,1,False),'top_k':(0,100000,True),'prompt_cache_gib':(0,1024,False),'mlx_cache_gib':(0,1024,False),'mtp_drafts':(0,1024,True),'mtp_confidence':(0,1,False),'checkpoint_slots':(0,4096,True),'spill_gib':(0,1048576,False),'max_snapshots':(0,4096,True),'thinking_budget':(0,2097152,True)}
        for key,value in values.items():
            if key in ADVANCED_OPTIONS and value is None:
                result[key]=None;continue
            if key in ranges:
                bounded_number(value,*ranges[key][:2],key,ranges[key][2])
                if key.endswith('_port') and value==8089: raise APIError('Port 8089 is reserved for the external engine')
            elif key=='engine_python':
                if value and os.environ.get('TFM_ALLOW_EXTERNAL_ENGINE')!='1': raise APIError('External engine requires explicit developer mode','forbidden',403)
                if value and (not Path(value).is_absolute() or not Path(value).is_file()): raise APIError('Engine Python must be an existing absolute file')
            elif key=='snapshot_dir':
                if value!=str(self.snapshots): raise APIError('Only the application-owned snapshot directory is supported')
            elif key=='model_dirs':
                if not isinstance(value,list) or len(value)>32 or any(not isinstance(p,str) or not Path(p).expanduser().is_absolute() or '\x00' in p for p in value): raise APIError('Model directories must be absolute paths')
                value=[str(Path(p).expanduser().resolve()) for p in value]
            elif key=='parallel':
                if value!='auto' and (isinstance(value,bool) or not str(value).isdigit() or not 1<=int(value)<=128): raise APIError('parallel must be auto or 1–128')
            elif key in ('thinking','no_drafts'):
                if not isinstance(value,bool): raise APIError(key+' must be boolean')
            elif key=='drafter_bits':
                if type(value) is not int or value not in (0,2,3,4,5,6,8):raise APIError('drafter_bits must be one of 0,2,3,4,5,6,8')
            elif key=='reasoning_effort':
                if value not in ('low','medium','xhigh'):raise APIError('reasoning_effort must be low, medium or xhigh')
            elif key=='name':
                if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}',value):raise APIError('name must be a safe model API identifier')
            elif key=='drafter':
                if not isinstance(value,str) or not value or len(value)>4096 or any(ord(c)<32 for c in value):raise APIError('Invalid drafter')
                if value not in ('auto','none') and not Path(value).expanduser().is_absolute():repo_id(value)
            elif key=='selected_model':
                if value is not None and (not isinstance(value,str) or len(value)>4096 or '\x00' in value or value.startswith('-')): raise APIError('Invalid model')
            result[key]=value
        merged=self.settings() | result
        if merged['engine_port']==merged['gateway_port']: raise APIError('Engine and gateway ports must differ')
        return result
    def settings_update(self, values):
        with self.lock:
            result=self.settings() | self.validate_settings(values)
            return self.put('settings',result)
    def key_create(self, data):
        name=data.get('name','API key')
        if not isinstance(name,str) or not 1<=len(name)<=120: raise APIError('Invalid key name')
        days=data.get('expires_days')
        if days is not None: bounded_number(days,1,3650,'expires_days',True)
        raw='tfm_live_'+secrets.token_urlsafe(32); now=time.time(); id=uuid.uuid4().hex
        with self.lock,self.db:
            self.db.execute('INSERT INTO keys VALUES (?,?,?,?,?,?)',(id,name,hashlib.sha256(raw.encode()).hexdigest(),now,now+days*86400 if days else None,1))
        return {'id':id,'name':name,'key':raw}
    def keys(self):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT id,name,created_at,expires_at,enabled FROM keys ORDER BY created_at DESC')]
    def key_valid(self,raw):
        if not raw: return False
        with self.lock:
            return self.db.execute('SELECT 1 FROM keys WHERE hash=? AND enabled=1 AND (expires_at IS NULL OR expires_at>?)',(hashlib.sha256(raw.encode()).hexdigest(),time.time())).fetchone() is not None
    def key_delete(self,id):
        with self.lock,self.db: self.db.execute('DELETE FROM keys WHERE id=?',(id,))
    def key_toggle(self,id):
        with self.lock,self.db:
            if not self.db.execute('UPDATE keys SET enabled=1-enabled WHERE id=?',(id,)).rowcount: raise APIError('Key not found','not_found',404)
        return {'keys':self.keys()}
    def profile_save(self,data):
        name=data.get('name'); config=data.get('config',{})
        if not isinstance(name,str) or not 1<=len(name)<=120: raise APIError('Profile name required')
        allowed=set(self.defaults())-{'engine_python','model_dirs','snapshot_dir','engine_port','gateway_port'}
        if not isinstance(config,dict) or set(config)-allowed: raise APIError('Profile contains unsupported settings')
        self.validate_settings(config)
        id=identifier(data.get('id',uuid.uuid4().hex))
        return self.put('profile',dict(id=id,name=name,config=config),id)
    def profiles(self): return self.all('profile')
    def profile_delete(self,id): self.delete('profile',id)
    def history(self): return self.get('chat',default={'messages':[]})
    def history_save(self,data):
        messages=data.get('messages')
        if not isinstance(messages,list) or len(messages)>2000: raise APIError('Invalid history')
        if any(not isinstance(m,dict) or m.get('role') not in ('system','developer','user','assistant','tool') or not isinstance(m.get('content'),(str,list,type(None))) for m in messages): raise APIError('Invalid history message')
        return self.put('chat',{'messages':messages})
    def _chat_sessions_migrate(self):
        with self.lock,self.db:
            if self.db.execute("SELECT 1 FROM documents WHERE kind='chat_session_migration' AND id='default'").fetchone():return
            legacy=self.history().get('messages',[])
            if legacy:
                now=time.time();id=uuid.uuid4().hex
                first=next((m.get('content') for m in legacy if m.get('role')=='user' and isinstance(m.get('content'),str) and m.get('content').strip()),'Imported conversation')
                session=dict(id=id,title=first.strip()[:120],created_at=now,updated_at=now,revision=0,messages=legacy)
                self.db.execute('INSERT INTO documents VALUES (?,?,?)',('chat_session',id,json.dumps(session,ensure_ascii=False,allow_nan=False)))
            self.db.execute('INSERT INTO documents VALUES (?,?,?)',('chat_session_migration','default','{"complete":true}'))
    def chat_sessions(self):
        self._chat_sessions_migrate()
        rows=self.all('chat_session')
        return sorted(({k:v for k,v in row.items() if k!='messages'} for row in rows),key=lambda row:row['updated_at'],reverse=True)
    def chat_session(self,id):
        identifier(id)
        self._chat_sessions_migrate()
        result=self.get('chat_session',id)
        if result is None:raise APIError('Conversation not found','not_found',404)
        return result
    def chat_session_create(self,data):
        self._chat_sessions_migrate()
        title=data.get('title','New conversation')
        if not isinstance(title,str) or not 1<=len(title.strip())<=120 or any(ord(ch)<32 for ch in title):raise APIError('Conversation title must be 1–120 characters')
        now=time.time();id=uuid.uuid4().hex
        return self.put('chat_session',dict(id=id,title=title.strip(),created_at=now,updated_at=now,revision=0,messages=[]),id)
    def chat_session_update(self,id,data):
        identifier(id)
        with self.lock:
            current=self.chat_session(id)
            revision=data.get('revision')
            if type(revision) is not int or revision!=current['revision']:raise APIError('Conversation changed; reload before saving','conflict',409)
            if not any(key in data for key in ('title','messages')):raise APIError('No conversation changes supplied')
            if 'title' in data:
                title=data['title']
                if not isinstance(title,str) or not 1<=len(title.strip())<=120 or any(ord(ch)<32 for ch in title):raise APIError('Conversation title must be 1–120 characters')
                current['title']=title.strip()
            if 'messages' in data:
                messages=data['messages']
                if not isinstance(messages,list) or len(messages)>2000:raise APIError('Invalid conversation messages')
                if any(not isinstance(m,dict) or m.get('role') not in ('system','developer','user','assistant','tool') or not isinstance(m.get('content'),(str,list,type(None))) or isinstance(m.get('content'),str) and len(m['content'])>1000000 for m in messages):raise APIError('Invalid conversation message')
                try:serialized=json.dumps(messages,ensure_ascii=False,allow_nan=False)
                except (TypeError,ValueError):raise APIError('Invalid conversation message')
                if len(serialized.encode())>8*1024*1024:raise APIError('Conversation too large')
                current['messages']=messages
            current['revision']+=1;current['updated_at']=time.time()
            return self.put('chat_session',current,id)
    def log(self,level,message):
        with self.lock,self.db:
            self.db.execute('INSERT INTO logs (at,level,message) VALUES (?,?,?)',(time.time(),level,redact(message)[:16000]))
            self.db.execute('DELETE FROM logs WHERE id < (SELECT MAX(id)-10000 FROM logs)')
    def logs(self,level='',query='',limit=200):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT * FROM logs WHERE (?="" OR level=?) AND message LIKE ? ORDER BY id DESC LIMIT ?',(level,level,'%'+query+'%',min(max(int(limit),1),2000)))]
    def record_request(self,record):
        body=dict(id=uuid.uuid4().hex,at=time.time(),model=None,status=None,elapsed=None,ttft=None,input_tokens=None,output_tokens=None,prefill_tps=None,decode_tps=None,cache_tokens=None,prefill_seconds=None,prefill_tps_source=None,ttft_source=None,engine_version=None,parameters=None,engine_parameters=None,engine_started_at=None,error=None) | record
        with self.lock,self.db: self.db.execute('INSERT INTO requests VALUES (?,?,?,?)',(body['id'],body['at'],body['model'],json.dumps(body)))
        return body
    def stats(self,model='',range='all'):
        intervals={'hour':3600,'24h':86400,'day':86400,'7d':604800,'week':604800,'30d':2592000,'all':None}
        if range not in intervals: raise APIError('Unknown statistics range')
        after=time.time()-intervals[range] if intervals[range] else 0
        with self.lock:
            records=[json.loads(r[0]) for r in self.db.execute('SELECT body FROM requests WHERE at>=? AND (?="" OR model=?) ORDER BY at DESC',(after,model,model))]
        def aggregate(rows):
            def values(key):return [r[key] for r in rows if isinstance(r.get(key),(int,float)) and not isinstance(r[key],bool) and math.isfinite(r[key]) and r[key]>=0]
            def average(key):
                samples=values(key);return sum(samples)/len(samples) if samples else None
            def total(key):
                samples=values(key);return sum(samples) if samples else None
            return {'requests':len(rows),'errors':sum(isinstance(r.get('status'),int) and r['status']>=400 and r['status']!=499 for r in rows),'cancelled':sum(r.get('status')==499 for r in rows),'input_tokens':total('input_tokens'),'output_tokens':total('output_tokens'),'cache_tokens':total('cache_tokens'),'avg_elapsed':average('elapsed'),'avg_ttft':average('ttft'),'avg_prefill_tps':average('prefill_tps'),'avg_decode_tps':average('decode_tps'),'metric_samples':{key:len(values(key)) for key in ('ttft','prefill_tps','decode_tps','cache_tokens','elapsed')}}
        models=sorted({r.get('model') for r in records},key=lambda value:value or '')
        return {'total':aggregate(records),'models':[dict(model=m,**aggregate([r for r in records if r.get('model')==m])) for m in models],'requests':records[:2000]}
