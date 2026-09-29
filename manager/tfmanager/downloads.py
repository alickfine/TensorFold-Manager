"""Pinned downloads with explicit app-owned credentials and private staging."""
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import urllib.parse
import urllib.request
from .state import APIError,repo_id

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        target=urllib.parse.urlsplit(newurl)
        if target.scheme!='https' or target.username or target.password:raise APIError('Unsafe download redirect','unsafe_redirect',502)
        # Credentials never follow redirects, including same-origin signed download redirects.
        result=super().redirect_request(req,fp,code,msg,headers,newurl)
        if result:
            for key in ('Authorization','Cookie','Proxy-Authorization'):result.remove_header(key)
        return result

def public_open(url,headers=None,timeout=30):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password:raise APIError('HTTPS public URL required')
    request=urllib.request.Request(url,headers={'User-Agent':'TensorFold-Manager/0.1','Accept':'application/json'}|(headers or {}))
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),SafeRedirect()).open(request,timeout=timeout)

def public_json(url,headers=None):
    with public_open(url,headers) as response:return json.load(response)

def safe_target(root,name):
    if not isinstance(name,str) or '\\' in name or '\x00' in name:raise APIError('Unsafe repository filename')
    relative=PurePosixPath(name)
    if relative.is_absolute() or any(part in ('..','') for part in relative.parts) or not relative.parts:raise APIError('Unsafe repository filename')
    root=Path(root)
    if root.is_symlink():raise APIError('Download root is a symlink')
    current=root
    for part in relative.parts:
        current=current/part
        if current.is_symlink():raise APIError('Symlinks are forbidden in writable task directories')
    if not current.resolve().is_relative_to(root.resolve()):raise APIError('Download path escapes owned root')
    return current

class Downloads:
    SOURCES={'huggingface':'https://huggingface.co','hf-mirror':'https://hf-mirror.com','modelscope':'https://modelscope.cn'}
    def __init__(self,store,jobs,credentials=None,on_complete=None):
        self.credentials=credentials;self.on_complete=on_complete
        self.store=store;self.jobs=jobs;self.root=store.root/'models';self.root.mkdir(exist_ok=True,mode=0o700);jobs.register('download',self.run)
    def catalog(self):
        from .models import CATALOG
        return {'models':[row|{'download_sources':['huggingface','hf-mirror']} for row in CATALOG],'sources':[{'id':id,'url':url,'third_party':id=='hf-mirror','credentials_supported':id!='hf-mirror'} for id,url in self.SOURCES.items()],'default_directory':str(self.root),'revision_policy':'Resolve once to immutable commit; verify each file identity before publish'}
    @staticmethod
    def require_catalog(repo,source):
        from .models import CATALOG
        row=next((r for r in CATALOG if r['repo']==repo and r.get('supported')),None)
        if row is None:raise APIError('Model is not in the supported download catalog','unsupported_model',409)
        if source not in ('huggingface','hf-mirror'):raise APIError('This catalog checkpoint has no verified repository on the selected source','source_unavailable',409)
    def create(self,data):
        repo=repo_id(data.get('repo'));source=data.get('source','huggingface')
        if source not in self.SOURCES:raise APIError('Unknown download source')
        self.require_catalog(repo,source)
        use_credentials=data.get('use_credentials',False)
        if not isinstance(use_credentials,bool):raise APIError('use_credentials must be a boolean')
        if use_credentials and source=='hf-mirror':raise APIError('Credentials cannot be sent to a third-party mirror','credential_origin_forbidden',409)
        if use_credentials and self.credentials is None:raise APIError('App credential helper unavailable','credential_helper_unavailable',409)
        revision=data.get('revision') or ('master' if source=='modelscope' else 'main')
        if not isinstance(revision,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',revision) or '..' in revision:raise APIError('Invalid revision')
        directory=Path(data.get('directory') or self.root).expanduser()
        # A directory field is not sufficient authority to create hidden staging in arbitrary external paths.
        # Explicit write scope is recorded by /api/downloads/scope (native picker or user confirmation).
        scopes=self.store.get('download_scopes',default=[str(self.root)])
        if str(directory.resolve()) not in scopes:raise APIError('Grant explicit write scope to this download directory first','write_scope_required',409)
        if directory.is_symlink():raise APIError('Download destination cannot be a symlink')
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        return self.jobs.create('download',{'repo':repo,'source':source,'revision':revision,'directory':str(directory.resolve()),'use_credentials':use_credentials})
    def grant_scope(self,data):
        if data.get('confirm') is not True:raise APIError('Explicit directory write confirmation required')
        raw=data.get('directory')
        if not isinstance(raw,str) or not Path(raw).expanduser().is_absolute():raise APIError('Absolute directory required')
        path=Path(raw).expanduser()
        if path.is_symlink() or path.resolve()==Path('/') or self.store.root in path.resolve().parents:raise APIError('Choose a separate model directory')
        scopes=self.store.get('download_scopes',default=[str(self.root)]);scopes=list(dict.fromkeys(scopes+[str(path.resolve())]));self.store.put('download_scopes',scopes)
        return {'directories':scopes}
    def request_headers(self,params,url):
        if not params.get('use_credentials'):return {}
        source=params['source'];parsed=urllib.parse.urlsplit(url)
        expected={'huggingface':'huggingface.co','modelscope':'modelscope.cn'}.get(source)
        if not expected or parsed.scheme!='https' or parsed.netloc!=expected or parsed.username or parsed.password:
            raise APIError('Credential destination is not the exact official source','credential_origin_forbidden',409)
        if self.credentials is None:raise APIError('App credential helper unavailable','credential_helper_unavailable',409)
        provider='hf-download' if source=='huggingface' else 'modelscope-download'
        token=self.credentials.get(provider)
        headers={'Authorization':'Bearer '+token}
        if source=='modelscope':
            if any(ord(c)<33 or ord(c)>126 or ord(c) in (34,44,59,92) for c in token):raise APIError('ModelScope token cannot be encoded safely as a session cookie','invalid_credential',409)
            headers['Cookie']='m_session_id='+token
        return headers
    def metadata(self,params):
        repo=params['repo'];base=self.SOURCES[params['source']];rev=urllib.parse.quote(params['revision'],safe='')
        if params['source']=='modelscope':
            url=f'{base}/api/v1/models/{repo}/repo/files?Revision={rev}&Recursive=true'
            payload=public_json(url,headers=self.request_headers(params,url))
            data=payload.get('Data',{});entries=data.get('Files',[]) if isinstance(data,dict) else data
            if not isinstance(entries,list) or len(entries)>=3000:raise APIError('ModelScope file tree is missing or may be truncated','incomplete_file_tree',409)
            pinned=data.get('Revision') if isinstance(data,dict) else None
            pinned=pinned or (params['revision'] if re.fullmatch(r'[0-9a-f]{40,64}',params['revision']) else None)
            files=[]
            for f in entries:
                if f.get('Type')=='tree':continue
                commit=pinned or f.get('Revision')
                if not isinstance(commit,str) or not re.fullmatch(r'[0-9a-f]{40,64}',commit):raise APIError('ModelScope file lacks an immutable commit revision','revision_not_pinned',409)
                files.append({'path':f['Path'],'size':f['Size'],'sha256':f.get('Sha256'),'revision':commit,'url':f'{base}/api/v1/models/{repo}/repo?Revision={commit}&FilePath='+urllib.parse.quote(f['Path'],safe='')})
            # Legacy API supplies each file's immutable last-change commit, not the branch HEAD.
            # A content manifest identifies this captured tree without inventing a repository commit.
            revision=pinned or hashlib.sha256(json.dumps(sorted((f['path'],f['size'],f['sha256'],f['revision']) for f in files),separators=(',',':')).encode()).hexdigest()
            revision_kind='repository_commit' if pinned else 'file_manifest_sha256'
        else:
            url=f'{base}/api/models/{repo}/revision/{rev}?blobs=true'
            payload=public_json(url,headers=self.request_headers(params,url));revision=payload.get('sha','')
            if not re.fullmatch(r'[0-9a-f]{40,64}',revision):raise APIError('Source did not return an immutable commit','revision_not_pinned',502)
            files=[]
            for f in payload.get('siblings',[]):
                lfs=f.get('lfs') or {};name=f['rfilename']
                files.append({'path':name,'size':lfs.get('size',f.get('size')),'sha256':lfs.get('sha256'),'git_sha1':f.get('blobId') if not lfs else None,'url':f'{base}/{repo}/resolve/{revision}/'+urllib.parse.quote(name,safe='/')})
        if not files:raise APIError('Source returned no files','empty_repository',502)
        for f in files:
            safe_target(self.root,f['path'])
            if not isinstance(f['size'],int) or f['size']<0 or not (re.fullmatch('[0-9a-f]{64}',f.get('sha256') or '') or re.fullmatch('[0-9a-f]{40}',f.get('git_sha1') or '')):raise APIError('Source does not provide verifiable file identity','identity_unavailable',409)
        return {'repo':repo,'source':params['source'],'revision':revision,'revision_kind':revision_kind if params['source']=='modelscope' else 'repository_commit','files':files}
    @staticmethod
    def verify_file(path,entry):
        if path.stat().st_size!=entry['size']:raise APIError('Downloaded size mismatch','integrity_error',409)
        digest=hashlib.sha256() if entry.get('sha256') else hashlib.sha1()
        if not entry.get('sha256'):digest.update(f'blob {entry["size"]}\0'.encode())
        with path.open('rb') as f:
            while chunk:=f.read(1048576):digest.update(chunk)
        if digest.hexdigest()!=(entry.get('sha256') or entry.get('git_sha1')):raise APIError('Downloaded content identity mismatch','integrity_error',409)
    def run(self,job):
        self.require_catalog(job.params['repo'],job.params['source'])
        params=job.params;root=Path(params['directory']);stage=safe_target(root,'.tfmanager-partials/'+job.id);stage.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(stage.parent,0o700)
        manifest_path=safe_target(stage,'manifest.json')
        if manifest_path.exists():manifest=json.loads(manifest_path.read_text())
        else:
            manifest=self.metadata(params);manifest.update(owner='tfmanager',job_id=job.id);manifest_path.write_text(json.dumps(manifest));os.chmod(manifest_path,0o600)
        if manifest.get('owner')!='tfmanager' or manifest.get('job_id')!=job.id:raise APIError('Staging manifest ownership mismatch')
        content=safe_target(stage,'content');content.mkdir(exist_ok=True,mode=0o700);done=0;total=sum(f['size'] for f in manifest['files'])
        for entry in manifest['files']:
            job.checkpoint();target=safe_target(content,entry['path']);target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if entry['size']==0 and not target.exists():target.touch(mode=0o600)
            offset=target.stat().st_size if target.exists() else 0
            if offset>entry['size']:raise APIError('Partial file exceeds expected size','integrity_error',409)
            if offset==entry['size'] and target.exists():
                try:self.verify_file(target,entry)
                except APIError:offset=0 # Explicit retry rewrites only this task-owned corrupt partial.
            if offset<entry['size']:
                headers=self.request_headers(params,entry['url'])
                if offset:headers['Range']=f'bytes={offset}-'
                with public_open(entry['url'],headers) as response:
                    append=bool(offset and response.status==206)
                    if append and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise APIError('Invalid resume response','integrity_error',502)
                    if not append:offset=0
                    with target.open('ab' if append else 'wb') as out:
                        os.chmod(target,0o600)
                        while True:
                            job.checkpoint();chunk=response.read(1048576)
                            if not chunk:break
                            out.write(chunk);offset+=len(chunk)
                            if offset>entry['size']:raise APIError('Download exceeds declared size','integrity_error',502)
                            job.progress(downloaded_bytes=done+offset,total_bytes=total,file=entry['path'],revision=manifest['revision'])
            self.verify_file(target,entry);done+=entry['size'];job.progress(downloaded_bytes=done,total_bytes=total,file=entry['path'],revision=manifest['revision'])
        job.checkpoint();destination=safe_target(root,params['repo'].replace('/','--')+'-'+manifest['revision'][:12])
        if destination.exists():raise APIError('Destination already exists; refusing to overwrite model','destination_exists',409)
        (content/'.tfmanager-manifest.json').write_text(json.dumps(manifest));os.rename(content,destination)
        dirs=self.store.settings()['model_dirs']
        if str(root) not in dirs:self.store.settings_update({'model_dirs':dirs+[str(root)]})
        if self.on_complete:
            try:self.on_complete()
            except Exception as error:self.store.log('warning','Download published; model refresh needs retry: '+str(error))
        return {'path':str(destination),'revision':manifest['revision'],'verified_files':len(manifest['files'])}
