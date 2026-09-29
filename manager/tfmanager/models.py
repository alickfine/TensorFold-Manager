"""Read-only discovery of local weights and explicit checkpoint compatibility."""
import hashlib
import json
import re
from pathlib import Path
from .state import APIError, repo_id, ADVANCED_OPTIONS

# Tested MLX checkpoints advertised by upstream TensorFold; family match alone is not a guarantee.
CATALOG=[{'repo':repo,'name':repo.split('/')[-1],'family':family,'supported':True,'source':'huggingface'} for repo,family in [
 ('Vontra/Qwen3.8-27B-MLX-4bit','qwen3_5'),('Vontra/Qwen3.6-35B-A3B-MLX-4bit-MTP','qwen3_5_moe'),
 ('Vontra/Qwen3.8-Flash-Next-MLX-4bit-MTP','qwen4_exp'),('Vontra/GLM-5.3-Flash-MLX-4bit-MTP','glm5_next'),
 ('Vontra/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-MLX-4bit','nemotron_h'),('mlx-community/gemma-4-26b-a4b-it-4bit','gemma4')]]

class Models:
    def __init__(self,store): self.store=store; self.rows=[]; self.engine_identity=lambda:None
    def roots(self): return [Path(p).expanduser().resolve() for p in self.store.settings()['model_dirs']]
    def permitted(self,path): return any(path.is_relative_to(root) for root in self.roots())
    def describe(self,path):
        path=path.resolve()
        if not self.permitted(path): raise APIError('Model path is outside configured read roots')
        try:
            config=json.loads((path/'config.json').read_text())
            if not isinstance(config,dict): return None
        except (OSError,ValueError): return None
        repo=config.get('_name_or_path')
        names={p.name for p in path.parents}
        owned=path/'.tfmanager-manifest.json'
        if owned.is_file():
            try:
                manifest=json.loads(owned.read_text())
                if manifest.get('owner')=='tfmanager':repo=manifest.get('repo',repo)
            except (OSError,ValueError):pass
        match=next((r for r in CATALOG if r['repo']==repo or ('models--'+r['repo'].replace('/','--')) in names),None)
        # Follow HF blob links for read-only size/completeness only; never write or delete these files.
        weights=list(path.glob('*.safetensors')); installed=bool(weights) and all(p.is_file() and p.stat().st_size>0 for p in weights)
        index=path/'model.safetensors.index.json'
        if index.is_file():
            try:
                files=set(json.loads(index.read_text())['weight_map'].values())
                installed=bool(files) and all(isinstance(f,str) and not Path(f).is_absolute() and '..' not in Path(f).parts and (path/f).is_file() and (path/f).stat().st_size>0 for f in files)
            except (ValueError,KeyError,TypeError,OSError): installed=False
        shards=[re.fullmatch(r'model-(\d+)-of-(\d+)\.safetensors',f.name) for f in weights if f.name.startswith('model-')]
        if shards:
            if not all(shards):installed=False
            else:
                totals={int(m.group(2)) for m in shards};installed=installed and len(totals)==1 and {int(m.group(1)) for m in shards}==set(range(1,next(iter(totals))+1))
        validation=self.store.get('model_validation',str(path))
        if validation and (validation.get('fingerprint')!=self.fingerprint(path) or validation.get('engine_identity')!=self.engine_identity() or validation.get('backend')!='mlx'):validation=None
        size=sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        return {'id':str(path),'name':match['name'] if match else path.name,'repo':match['repo'] if match else repo,'path':str(path),'size_bytes':size,'family':config.get('model_type'),'installed':installed,'supported':bool(match or (validation and validation.get('supported'))),'startable':bool(installed and validation and validation.get('supported') and validation.get('backend')=='mlx'),'unsupported_reason':validation.get('reason') if validation and not validation.get('supported') else (None if validation else 'Current engine MLX compatibility has not been checked'),'validation':validation,'config':self.store.get('model_config',str(path),{})}
    @staticmethod
    def fingerprint(path):
        path=Path(path);digest=hashlib.sha256((path/'config.json').read_bytes())
        for file in sorted(path.glob('*.safetensors')):
            stat=file.stat();digest.update(f'{file.name}:{file.resolve()}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}'.encode())
        index=path/'model.safetensors.index.json'
        if index.is_file():digest.update(index.read_bytes())
        return digest.hexdigest()
    def scan(self):
        seen=set(); rows=[]
        for root in self.roots():
            if not root.is_dir(): continue
            candidates=[root,*root.glob('*'),*root.glob('models--*/snapshots/*')]
            for path in candidates:
                if not path.is_dir() or path.resolve() in seen or not (path/'config.json').is_file(): continue
                seen.add(path.resolve())
                try: row=self.describe(path)
                except (OSError,APIError): continue
                if row: rows.append(row)
        self.rows=rows; return rows
    def resolve(self,value):
        if not isinstance(value,str) or not value or '\x00' in value or value.startswith('-'): raise APIError('Invalid model')
        path=Path(value).expanduser()
        if not path.is_absolute():
            repo_id(value); row=next((r for r in self.scan() if r['repo']==value),None)
            if not row: raise APIError('Download this model before starting; startup never downloads weights','model_missing',409)
        else: row=self.describe(path)
        if not row or not row['installed']: raise APIError('Model weights are incomplete or missing','model_missing',409)
        if not row['supported']: raise APIError('Checkpoint is not on the tested TensorFold MLX allowlist','unsupported_model',409)
        return row
    def configure(self,data):
        model=self.resolve(data.get('model')); config=data.get('config',{})
        allowed={'context','max_tokens','temperature','top_p','top_k','parallel','thinking','prompt_cache_gib','mlx_cache_gib'} | set(ADVANCED_OPTIONS)
        if not isinstance(config,dict) or set(config)-allowed: raise APIError('Unsupported model configuration')
        self.store.validate_settings(config)
        result=self.store.put('model_config',config,model['id'])
        self.rows=[row|{'config':config} if row['id']==model['id'] else row for row in self.rows]
        return result
