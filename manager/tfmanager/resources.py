"""Fail-closed memory admission, same-user inference discovery, and OS-backed leases.

Process identities and lock records are evidence only; this module never signals a PID.
RSS is deliberately absent: macOS shared/Metal allocation is not process RSS.
"""
import ctypes
import struct
import fcntl
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import stat
import subprocess
import threading
import time
from .state import APIError,ADVANCED_OPTIONS,clean_env
GIB=1024**3

class ResourceBlocked(APIError):
    def __init__(self,report,message='Resource admission blocked; inspect blockers and missing evidence'):
        super().__init__(message,'resource_blocked',409);self.report=report
    def payload(self):return super().payload() | {'resources':self.report}

def parse_memory(physical,vm,query,pressure,swap):
    result={'physical_bytes':None,'available_bytes':None,'pressure':None,'swap_used_bytes':None,'missing':[],'source':'macOS vm_stat + memory_pressure + sysctl (not RSS)'}
    try:result['physical_bytes']=int(physical.strip())
    except ValueError:result['missing'].append('physical_memory')
    result['pressure']={'1':'normal','2':'warning','4':'critical'}.get(pressure.strip())
    if result['pressure'] is None:result['missing'].append('memory_pressure_level')
    page=re.search(r'page size of (\d+) bytes',vm);percent=re.search(r'memory free percentage:\s*(\d+)%',query)
    counts=[re.search(r'^'+label+r':\s*(\d+)',vm,re.M) for label in ('Pages free','Pages inactive','Pages speculative')]
    if page and percent and all(counts) and result['physical_bytes']:
        reclaimable=sum(int(x.group(1)) for x in counts)*int(page.group(1))
        result['available_bytes']=min(reclaimable,int(result['physical_bytes']*int(percent.group(1))/100))
        result['free_percent']=int(percent.group(1));result['reclaimable_bytes']=reclaimable
    else:result['missing'].append('available_memory')
    used=re.search(r'used\s*=\s*([\d.]+)([KMGT])',swap)
    if used:result['swap_used_bytes']=int(float(used.group(1))*1024**('KMGT'.index(used.group(2))+1))
    else:result['missing'].append('swap_usage')
    return result

# A command is recognized by its executable/module position, never by a model/name substring.
def parse_command(command,executable=None,argv=None):
    reliable=argv is not None or executable is None
    try:
        if argv is None:
            argv=([executable]+shlex.split(command[len(executable):])) if executable and command.startswith(executable+' ') else shlex.split(command)
    except ValueError:return None
    if not argv:return None
    exe=Path(argv[0]).name.lower();offset=1;kind=None
    if exe in ('tensorfold','omlx'):kind=exe
    elif exe.startswith('python'):
        while offset<len(argv) and argv[offset] in ('-B','-I','-s','-S','-u','-E'):offset+=1
        if offset+1<len(argv) and argv[offset]=='-m' and argv[offset+1] in ('tensorfold','tensorfold.cli','omlx','omlx.server'):
            kind='tensorfold' if argv[offset+1].startswith('tensorfold') else 'omlx';offset+=2
        elif offset<len(argv) and Path(argv[offset]).name in ('tensorfold','omlx'):
            kind=Path(argv[offset]).name;offset+=1
    if kind is None:return None
    if kind=='tensorfold' and (offset>=len(argv) or argv[offset]!='serve'):return None
    if offset<len(argv) and argv[offset]=='serve':offset+=1
    model=None
    if offset<len(argv) and not argv[offset].startswith('-'):model=argv[offset];offset+=1
    allowed={'host','port','name','alias','context','max-tokens','temperature','top-p','top-k','parallel','snapshot-dir','prompt-cache-gib','mlx-cache-gib','backend','lane-kernels','ssd-experts','kv-dtype','tp','rank','master','master-port'}|{k.replace('_','-') for k in ADVANCED_OPTIONS}
    switches={'thinking','no-thinking','no-drafts','no-update-check','ple-on-ssd'};flags={};complete=reliable
    while offset<len(argv):
        token=argv[offset];offset+=1
        if not token.startswith('--'):complete=False;continue
        key,sep,value=token[2:].partition('=')
        if key in switches:
            if sep:complete=False;continue
            if key=='no-thinking':key='thinking';value=False
            else:value=True
        else:
            if not sep:
                if offset>=len(argv):complete=False;break
                value=argv[offset];offset+=1
            if key not in allowed:complete=False;continue # Unknown arguments (including secrets) are never retained.
        if key in flags:complete=False
        flags[key]=value
    return {'kind':kind,'model_path':str(Path(model).resolve()) if model and Path(model).is_absolute() else None,'flags':flags,'argv_verified':argv is not None and reliable,'identity_complete':complete and bool(model and Path(model).is_absolute()),'command_signature':hashlib.sha256(json.dumps(argv,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()}

def parse_procargs(raw):
    # KERN_PROCARGS2 layout: argc, executable NUL, padding NUL, argc argv strings.
    # Stop at argc: environment values are never parsed, retained or returned.
    if len(raw)<5 or len(raw)>1048576:raise ValueError('Invalid argument buffer')
    argc=struct.unpack_from('i',raw)[0]
    if not 1<=argc<=4096:raise ValueError('Invalid argc')
    pos=raw.index(b'\0',4)+1
    while pos<len(raw) and raw[pos]==0:pos+=1
    argv=[]
    for _ in range(argc):
        end=raw.index(b'\0',pos)
        if end-pos>65536:raise ValueError('Oversized argument')
        argv.append(raw[pos:end].decode('utf-8','strict'));pos=end+1
    return argv

class MacObserver:
    def _argv(self,pid):
        # Caller has already established same UID via ps. No environment API is used.
        libc=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
        mib=(ctypes.c_int*3)(1,49,pid);size=ctypes.c_size_t(1048576)
        buffer=ctypes.create_string_buffer(size.value)
        try:
            if libc.sysctl(mib,3,buffer,ctypes.byref(size),None,0)!=0:raise OSError('Argument probe unavailable')
            return parse_procargs(buffer.raw[:size.value])
        finally:ctypes.memset(buffer,0,len(buffer))

    def _run(self,argv,acceptable=(0,)):
        env=clean_env();env['LC_ALL']='C'
        result=subprocess.run(argv,env=env,capture_output=True,text=True,timeout=8)
        if result.returncode not in acceptable:raise OSError('Resource probe failed: '+Path(argv[0]).name)
        return result.stdout
    @staticmethod
    def _json(port,path,pid,token):
        from .peer import BoundHTTPConnection
        connection=BoundHTTPConnection(port,pid,token,timeout=.5)
        try:
            connection.request('GET',path);response=connection.getresponse()
            if response.status!=200:return None
            return json.loads(response.read(1048576))
        except (OSError,ValueError,APIError,http.client.HTTPException,subprocess.TimeoutExpired):return None
        finally:connection.close()
    def identity(self,pid):
        try:
            info=self._run(['/bin/ps','-p',str(pid),'-o','uid=,lstart=,comm=']).strip().split(maxsplit=6)
            if len(info)!=7 or int(info[0])!=os.getuid():return None
            executable=info[6];name=Path(executable).name.lower()
            if not(name.startswith('python') or name in ('tensorfold','omlx')):return None
            command=self._run(['/bin/ps','-ww','-p',str(pid),'-o','command=']).strip()
            if parse_command(command,executable=executable) is None:return None
            try:argv=self._argv(pid)
            except (OSError,ValueError):argv=None
            parsed=parse_command(command,executable=executable,argv=argv)
            if parsed is None:return None
            start=' '.join(info[1:6]);started=time.mktime(time.strptime(start,'%a %b %d %H:%M:%S %Y'))
            try:output=self._run(['/usr/sbin/lsof','-nP','-a','-p',str(pid),'-iTCP','-sTCP:LISTEN','-Fn'],acceptable=(0,1))
            except (OSError,subprocess.TimeoutExpired):output='';parsed['identity_complete']=False
            ports=sorted({int(m.group(1)) for line in output.splitlines() if line.startswith('n') and (m:=re.search(r':(\d+)$',line))})
            service=parsed|{'pid':pid,'uid':int(info[0]),'start_time':start,'started_at':started,'executable':executable,'listening_ports':ports,'health':None,'model_ids':[]}
            port=parsed['flags'].get('port')
            if port is None and len(ports)==1:port=ports[0]
            if str(port).isdigit() and int(port) in ports:
                service['port']=int(port)
                from .services import NativeInstances
                try:token=NativeInstances().bind(pid)
                except APIError:token=None
                health=self._json(int(port),'/health',pid,token);models=self._json(int(port),'/v1/models',pid,token)
                if isinstance(health,dict):service['health']={k:health.get(k) for k in ('status','model','warming','memory','max_batch_size')}
                if isinstance(models,dict) and isinstance(models.get('data'),list):service['model_ids']=[r['id'] for r in models['data'] if isinstance(r,dict) and isinstance(r.get('id'),str)]
            return service
        except (OSError,ValueError,subprocess.TimeoutExpired):return None
    def capture(self):
        missing=[];memory={'physical_bytes':None,'available_bytes':None,'pressure':None,'swap_used_bytes':None,'missing':['macOS_required']};services=[]
        if platform.system()!='Darwin':return {'at':time.time(),'memory':memory,'services':services,'missing':['macOS_resource_observer_unavailable']}
        try:
            memory=parse_memory(self._run(['/usr/sbin/sysctl','-n','hw.memsize']),self._run(['/usr/bin/vm_stat']),self._run(['/usr/bin/memory_pressure','-Q']),self._run(['/usr/sbin/sysctl','-n','kern.memorystatus_vm_pressure_level']),self._run(['/usr/sbin/sysctl','vm.swapusage']))
        except (OSError,subprocess.TimeoutExpired):missing.append('system_memory_probe')
        try:
            rows=self._run(['/bin/ps','-U',str(os.getuid()),'-o','pid=,comm='])
            for line in rows.splitlines():
                pieces=line.strip().split(maxsplit=1)
                if len(pieces)!=2:continue
                name=Path(pieces[1]).name.lower()
                if name.startswith('python') or name in ('tensorfold','omlx'):
                    service=self.identity(int(pieces[0]))
                    if service:services.append(service)
        except (OSError,ValueError,subprocess.TimeoutExpired):missing.append('same_uid_process_discovery')
        return {'at':time.time(),'memory':memory,'services':services,'missing':missing}

def estimate_model(path,settings,kind='inference'):
    path=Path(path).resolve();missing=[];parts={};config={}
    try:config=json.loads((path/'config.json').read_text());text=config.get('text_config',config)
    except (OSError,ValueError,AttributeError):return {'required_bytes':None,'components':{},'missing':['readable_model_config'],'method':'conservative-v1'}
    if not isinstance(config,dict) or not isinstance(text,dict):return {'required_bytes':None,'components':{},'missing':['object_model_config'],'method':'conservative-v1'}
    weights=list(path.glob('*.safetensors'))
    if not weights or any(not p.is_file() or p.stat().st_size<=0 for p in weights):missing.append('complete_nonempty_weights')
    index=path/'model.safetensors.index.json'
    if index.is_file():
        try:
            names=set(json.loads(index.read_text())['weight_map'].values())
            if not names or any(not isinstance(n,str) or Path(n).is_absolute() or '..' in Path(n).parts or not (path/n).is_file() or (path/n).stat().st_size<=0 for n in names):missing.append('complete_weight_index')
        except (ValueError,KeyError,TypeError,OSError):missing.append('complete_weight_index')
    size=sum(p.stat().st_size for p in weights if p.is_file());parts['weight_file_bytes']=size
    model_type=text.get('model_type') or config.get('model_type')
    if not isinstance(model_type,str) or not model_type.startswith(('qwen','gemma','llama','mistral','glm5_next','nemotron_h')):missing.append('supported_memory_architecture')
    if kind=='quantize':
        bits=[]
        def walk(value):
            if isinstance(value,dict):
                if type(value.get('bits')) is int and 2<=value['bits']<=16:bits.append(value['bits'])
                for item in value.values():walk(item)
        walk(config.get('quantization',{}));minimum=min(bits) if bits else 16
        parts.update(conversion_resident_bytes=math.ceil(size*max(1,16/minimum)*2),workspace_bytes=8*GIB)
    else:
        def number(key,default=None):
            value=text.get(key,default)
            if type(value) is not int or value<=0:missing.append(key);return 1
            return value
        layers=number('num_hidden_layers');hidden=number('hidden_size');intermediate=number('intermediate_size',hidden*4)
        context=settings.get('context');parallel=settings.get('parallel')
        if type(context) is not int or context<=0:missing.append('bounded_context');context=1
        if parallel=='auto':parallel=8 # Upstream cli._parallel caps auto at eight lanes.
        try:parallel=int(parallel)
        except (TypeError,ValueError):missing.append('bounded_parallel');parallel=1
        if parallel<1 or parallel>128:missing.append('bounded_parallel');parallel=1
        state=0;kv_bytes=0;capacity=math.ceil(context/2048)*2048
        if model_type in ('gemma4','gemma4_text'):
            types=text.get('layer_types',[])
            if not isinstance(types,list) or len(types)!=layers or any(t not in ('sliding_attention','full_attention') for t in types):missing.append('gemma_layer_types');types=[]
            sliding=types.count('sliding_attention');full=types.count('full_attention')
            kv=number('num_key_value_heads');dim=number('head_dim');global_dim=number('global_head_dim')
            global_kv=number('num_global_key_value_heads') if text.get('attention_k_eq_v') is True and text.get('num_global_key_value_heads') is not None else kv
            window=number('sliding_window')
            # RingKVCache holds window+128 rows with two spares; global cache grows with context.
            kv_bytes=(sliding*kv*dim*(window+128)+full*global_kv*global_dim*context)*4*parallel
            parts['sliding_prefill_kv_bytes']=sliding*kv*dim*min(context,8192)*4*parallel
        elif model_type in ('glm5_next','glm5_next_text'):
            # TensorFold glm5_next/caches.py stores latent + index keys/gates + pooled index.
            types=text.get('layer_types',[])
            if not isinstance(types,list) or len(types)!=layers or any(t not in ('linear_attention','deepseek_sparse_attention') for t in types):missing.append('glm_layer_types');types=[]
            full=types.count('deepseek_sparse_attention');recurrent=types.count('linear_attention')
            latent=number('kv_lora_rank');index=number('index_head_dim');pool=number('index_kpool')
            linear=text.get('linear_attn_config',{})
            def linear_number(key):
                value=linear.get(key) if isinstance(linear,dict) else None
                if type(value) is not int or value<=0:missing.append('linear_attn_config.'+key);return 1
                return value
            heads=linear_number('num_heads');dim=linear_number('head_dim');conv=linear_number('short_conv_kernel_size')
            # Include the draft attention cache when embedded MTP is enabled.
            mtp=0 if settings.get('no_drafts') or settings.get('mtp_drafts')==0 else number('num_nextn_predict_layers')
            kv_bytes=math.ceil((full+mtp)*(latent+2*index+index/pool)*2*context*parallel)
            state=2*recurrent*parallel*(heads*dim*dim*4+3*heads*dim*conv*4)
            capacity=math.ceil(context/256)*256
        else:
            heads=number('num_attention_heads');kv=number('num_key_value_heads');dim=number('head_dim',hidden//heads if hidden%heads==0 else None)
            # Gemma has separate global and sliding head shapes. Full context at both maxima is an upper bound.
            if str(model_type).startswith('gemma'):
                if text.get('global_head_dim') is not None:dim=max(dim,number('global_head_dim'))
                if text.get('num_global_key_value_heads') is not None:kv=max(kv,number('num_global_key_value_heads'))
            full=layers;recurrent=0;types=text.get('layer_types')
            if model_type=='nemotron_h':
                pattern=text.get('hybrid_override_pattern')
                if pattern is None and isinstance(text.get('layers_block_type'),list):pattern=[{'mamba':'M','attention':'*','moe':'E','mlp':'-'}.get(t,'?') for t in text['layers_block_type']]
                if isinstance(pattern,str):pattern=list(pattern)
                if not isinstance(pattern,list) or len(pattern)!=layers or any(t not in ('M','*','E','-') for t in pattern):missing.append('nemotron_hybrid_pattern');pattern=[]
                full=pattern.count('*');recurrent=pattern.count('M')
                mh=number('mamba_num_heads');md=number('mamba_head_dim');ssm=number('ssm_state_size');conv=number('conv_kernel');groups=number('n_groups')
                state=2*recurrent*parallel*(mh*md*ssm*4+conv*(mh*md+2*groups*ssm)*4)
                if not settings.get('no_drafts') and settings.get('mtp_drafts')!=0 and (path/'mtp-4bit.safetensors').is_file():full+=1
            else:
                if types is not None:
                    if not isinstance(types,list) or len(types)!=layers or any(t not in ('full_attention','sliding_attention','linear_attention') for t in types):missing.append('known_layer_types')
                    else:full=sum(t!='linear_attention' for t in types);recurrent=layers-full
                elif model_type in ('qwen3_5','qwen3_5_text','qwen3_5_moe') and text.get('full_attention_interval'):
                    interval=number('full_attention_interval');full=math.ceil(layers/interval);recurrent=layers-full
                if recurrent:
                    kh=number('linear_num_key_heads');vh=number('linear_num_value_heads');kd=number('linear_key_head_dim');vd=number('linear_value_head_dim');conv=number('linear_conv_kernel_dim')
                    state=2*recurrent*parallel*(vh*kd*vd*4+(2*kh*kd+vh*vd)*conv*4)
            kv_bytes=full*kv*dim*2*2*context*parallel
        # Current + spare + growth/predecessor: reserve three rounded capacities at allocation boundaries.
        headroom=math.ceil(kv_bytes*(3*capacity/context-1))
        parts.update(resident_weight_bytes=math.ceil(size*1.35),kv_bytes=kv_bytes,kv_allocation_headroom_bytes=headroom,recurrent_state_bytes=state,activation_bytes=max(2*GIB,intermediate*min(context,8192)*parallel*16),workspace_bytes=3*GIB)
        for key in ('prompt_cache_gib','mlx_cache_gib'):
            value=settings.get(key)
            if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<0:missing.append(key)
            else:parts[key+'_bytes']=int(value*GIB)
        drafter=settings.get('drafter')
        if not settings.get('no_drafts') and drafter not in (None,'auto','none'):
            if not Path(str(drafter)).is_absolute():missing.append('resolved_drafter_budget')
            else:
                draft=estimate_model(drafter,settings|{'drafter':'none','no_drafts':True,'parallel':1})
                if draft['missing']:missing.append('drafter_memory_architecture')
                else:parts['drafter_bytes']=draft['required_bytes']
    required=sum(value for key,value in parts.items() if key!='weight_file_bytes') if not missing else None
    return {'required_bytes':required,'components':parts,'missing':list(dict.fromkeys(missing)),'method':'conservative-v2','kind':kind,'model_path':str(path),'architecture':model_type,'notes':['Weight residency, bf16 KV, explicit hybrid state, full configured context/lanes and cache caps reserved.','This is a conservative admission estimate, not a measured peak or RSS.']}

class Lease:
    def __init__(self,path,fd,report):self.path=path;self.fd=fd;self.report=report;self.released=False
    @property
    def attachment(self):return self.report.get('attachment')
    @property
    def memory_limit_bytes(self):return self.report.get('memory_limit_bytes')
    def release(self):
        if not self.released:
            self.released=True
            # Do not LOCK_UN: an inherited supervisor descriptor must retain its lease after manager death.
            os.close(self.fd)
    def __enter__(self):return self
    def __exit__(self,*_):self.release()

class ResourceGate:
    def __init__(self,store,observer=None,lock_dir=None):
        self.store=store;self.observer=observer or MacObserver();self.lock_dir=Path(lock_dir) if lock_dir else Path.home()/'Library/Application Support/TensorFold Manager/ResourceLocks'
        self.lock_dir.mkdir(parents=True,exist_ok=True,mode=0o700);self._cache=None;self._cache_lock=threading.Lock()
    def snapshot(self,fresh=False):
        with self._cache_lock:
            if fresh or self._cache is None or time.monotonic()-self._cache[0]>2:self._cache=(time.monotonic(),self.observer.capture())
            return self._cache[1]
    @staticmethod
    def _lock(path,report):
        path=Path(path);fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
        try:
            info=os.fstat(fd)
            if info.st_uid!=os.getuid() or not stat.S_ISREG(info.st_mode):raise ResourceBlocked(report,'Unsafe resource lock ownership')
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ResourceBlocked(report|{'allowed':False,'blockers':['another_heavy_task_or_manager_holds_lease']})
            payload=json.dumps({'pid':os.getpid(),'uid':os.getuid(),'at':time.time(),'kind':report.get('kind')}).encode();os.ftruncate(fd,0);os.write(fd,payload);os.fsync(fd)
            return Lease(path,fd,report)
        except Exception:os.close(fd);raise
    @classmethod
    def lock_data(cls,data_dir):
        root=Path(data_dir).expanduser().resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
        return cls._lock(root/'manager-state.lock',{'kind':'manager_state'})
    def acquire_state(self):return self._lock(self.store.root/'manager-state.lock',{'kind':'manager_state'})
    def estimate(self,path,settings,kind='inference'):
        result=estimate_model(path,settings,kind)
        # Auto is cache-only upstream. Its private offline HF cache must not hide unbudgeted draft weights.
        if kind=='inference' and not settings.get('no_drafts') and settings.get('drafter') in (None,'auto'):
            private=self.store.root/'hf-runtime'
            if private.exists() and any(private.rglob('*.safetensors')):result['missing'].append('auto_drafter_cache_requires_explicit_selection');result['required_bytes']=None
        return result
    def compatible(self,service,path,settings):
        if service.get('kind')!='tensorfold' or service.get('uid')!=os.getuid() or not service.get('identity_complete') or not service.get('start_time') or not service.get('command_signature'):return False
        if service.get('model_path')!=str(Path(path).resolve()):return False
        flags=service.get('flags',{});health=service.get('health') or {}
        if health.get('status') not in ('ok','ready','healthy') or health.get('warming') is True:return False
        if flags.get('host')!='127.0.0.1' or not str(flags.get('port','')).isdigit() or int(flags['port']) not in service.get('listening_ports',[]):return False
        snapshot=flags.get('snapshot-dir')
        if not isinstance(snapshot,str) or not Path(snapshot).is_absolute():return False
        expected={'thinking':settings['thinking']}
        for key in ('context','max_tokens','temperature','top_p','top_k','parallel','prompt_cache_gib','mlx_cache_gib'):expected[key.replace('_','-')]=settings[key]
        for key,value in settings.items():
            if key in ADVANCED_OPTIONS and value is not None:expected[key.replace('_','-')]=value
        for key,value in expected.items():
            actual=flags.get(key)
            if isinstance(value,bool):
                if bool(actual)!=value:return False
            elif isinstance(value,(int,float)):
                try:
                    if float(actual)!=value:return False
                except (TypeError,ValueError):return False
            elif str(actual)!=str(value):return False
        # Unknown extra inference options cannot silently change a supposedly matching configuration.
        permitted=set(expected)|{'port','host','no-update-check','name','snapshot-dir'}
        if set(flags)-permitted:return False
        if flags.get('name') not in service.get('model_ids',[]):return False
        return True
    def _preflight(self,path,settings,kind):
        snapshot=self.snapshot(fresh=True);estimate=self.estimate(path,settings,kind);memory=snapshot['memory'];missing=list(snapshot.get('missing',[]))+list(memory.get('missing',[]));blockers=[]
        services=snapshot.get('services',[]);matches=[s for s in services if kind=='inference' and self.compatible(s,path,settings)]
        attachment=matches[0] if len(matches)==1 and len(services)==1 else None
        if services and attachment is None:blockers.append('existing_inference_service_must_be_reused_or_stopped_first')
        if memory.get('pressure')!='normal':blockers.append('memory_pressure_not_normal')
        available=memory.get('available_bytes');physical=memory.get('physical_bytes');reserve=max(8*GIB,int(physical*.1)) if isinstance(physical,int) and physical>0 else None
        if available is None or reserve is None:missing.append('verified_available_memory')
        limit=max(0,available-reserve) if available is not None and reserve is not None else None
        if not attachment:
            missing+=estimate['missing'];required=estimate['required_bytes']
            if required is None:missing.append('bounded_model_peak_estimate')
            elif limit is not None and required>limit:blockers.append('insufficient_available_memory_for_conservative_estimate')
        elif limit is not None and limit<=0:blockers.append('insufficient_headroom_for_attached_service')
        return {'allowed':not blockers and not missing,'kind':kind,'snapshot':snapshot,'estimate':estimate,'missing':list(dict.fromkeys(missing)),'blockers':blockers,'attachment':attachment,'system_reserve_bytes':reserve,'memory_limit_bytes':limit}
    def preflight_capacity(self,path,settings):
        snapshot=self.snapshot(fresh=True);estimate=self.estimate(path,settings);memory=snapshot.get('memory') or {};physical=memory.get('physical_bytes')
        missing=list(snapshot.get('missing',[]))+list(memory.get('missing',[]))+list(estimate['missing']);blockers=[]
        reserve=max(8*GIB,int(physical*.1)) if type(physical) is int and physical>0 else None
        if reserve is None:missing.append('verified_physical_memory')
        limit=max(0,physical-reserve) if reserve is not None else None
        required=estimate['required_bytes']
        if required is None:missing.append('bounded_model_peak_estimate')
        elif limit is not None and required>limit:blockers.append('target_exceeds_physical_capacity_after_system_reserve')
        return {'allowed':not missing and not blockers,'kind':'switch_capacity','snapshot':snapshot,'estimate':estimate,'missing':missing,'blockers':blockers,'physical_capacity_bytes':limit,'system_reserve_bytes':reserve}
    def preflight_start(self,path,settings):return self._preflight(path,settings,'inference')
    def preflight_quantize(self,source_path,options=None):return self._preflight(source_path,options or {},'quantize')
    def _acquire(self,path,settings,kind):
        lease=self._lock(self.lock_dir/'heavy-work.lock',{'kind':kind})
        try:
            report=self._preflight(path,settings,kind)
            if not report['allowed']:raise ResourceBlocked(report)
            lease.report=report;return lease
        except Exception:lease.release();raise
    def acquire_switch(self):return self._lock(self.lock_dir/'heavy-work.lock',{'kind':'external_switch'})
    def acquire_start(self,path,settings):return self._acquire(path,settings,'inference')
    def acquire_quantize(self,source_path,options=None):return self._acquire(source_path,options or {},'quantize')
    def verify_attachment(self,service):
        current=self.observer.identity(service['pid'])
        if not current:return False
        return all(current.get(key)==service.get(key) for key in ('uid','start_time','command_signature','model_path','listening_ports')) and bool(current.get('health')) and (current['health'].get('status') in ('ok','ready','healthy'))
