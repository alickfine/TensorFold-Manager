"""Public HF/mirror/ModelScope downloads: pinned identity, private staging, no ambient credentials."""
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
        # There are no credential headers on these public downloads. Strip defensively anyway.
        result=super().redirect_request(req,fp,code,msg,headers,newurl)
        if result:
            for key in ('Authorization','Cookie','Proxy-Authorization'):result.remove_header(key)
        return result

def public_open(url,headers=None,timeout=30):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password:raise APIError('HTTPS public URL required')
    request=urllib.request.Request(url,headers={'User-Agent':'TensorFold-Manager/0.1','Accept':'application/json'}|(headers or {}))
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),SafeRedirect()).open(request,timeout=timeout)

def public_json(url):
    with public_open(url) as response:return json.load(response)

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
    def __init__(self,store,jobs):
        self.store=store;self.jobs=jobs;self.root=store.root/'models';self.root.mkdir(exist_ok=True,mode=0o700);jobs.register('download',self.run)
    def catalog(self):
        from .models import CATALOG
        return {'models':CATALOG,'sources':[{'id':id,'url':url,'third_party':id=='hf-mirror','credentials_supported':False} for id,url in self.SOURCES.items()],'default_directory':str(self.root),'revision_policy':'Resolve once to immutable commit; verify each file identity before publish'}
    def create(self,data):
        repo=repo_id(data.get('repo'));source=data.get('source','huggingface')
        if source not in self.SOURCES:raise APIError('Unknown download source')
        revision=data.get('revision') or 'main'
        if not isinstance(revision,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',revision) or '..' in revision:raise APIError('Invalid revision')
        directory=Path(data.get('directory') or self.root).expanduser()
        # A directory field is not sufficient authority to create hidden staging in arbitrary external paths.
        # Explicit write scope is recorded by /api/downloads/scope (native picker or user confirmation).
        scopes=self.store.get('download_scopes',default=[str(self.root)])
        if str(directory.resolve()) not in scopes:raise APIError('Grant explicit write scope to this download directory first','write_scope_required',409)
        if directory.is_symlink():raise APIError('Download destination cannot be a symlink')
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        return self.jobs.create('download',{'repo':repo,'source':source,'revision':revision,'directory':str(directory.resolve())})
    def grant_scope(self,data):
        if data.get('confirm') is not True:raise APIError('Explicit directory write confirmation required')
        raw=data.get('directory')
        if not isinstance(raw,str) or not Path(raw).expanduser().is_absolute():raise APIError('Absolute directory required')
        path=Path(raw).expanduser()
        if path.is_symlink() or path.resolve()==Path('/') or self.store.root in path.resolve().parents:raise APIError('Choose a separate model directory')
        scopes=self.store.get('download_scopes',default=[str(self.root)]);scopes=list(dict.fromkeys(scopes+[str(path.resolve())]));self.store.put('download_scopes',scopes)
        return {'directories':scopes}
    def metadata(self,params):
        repo=params['repo'];base=self.SOURCES[params['source']];rev=urllib.parse.quote(params['revision'],safe='')
        if params['source']=='modelscope':
            payload=public_json(f'{base}/api/v1/models/{repo}/repo/files?Revision={rev}&Recursive=true')
            data=payload.get('Data',{});revision=data.get('Revision') or params['revision']
            if not re.fullmatch(r'[0-9a-f]{40,64}',revision):raise APIError('ModelScope requires an immutable commit revision','revision_not_pinned',409)
            files=[{'path':f['Path'],'size':f['Size'],'sha256':f.get('Sha256'),'url':f'{base}/api/v1/models/{repo}/repo?Revision={revision}&FilePath='+urllib.parse.quote(f['Path'],safe='')} for f in data.get('Files',[]) if f.get('Type')!='tree']
        else:
            payload=public_json(f'{base}/api/models/{repo}/revision/{rev}?blobs=true');revision=payload.get('sha','')
            if not re.fullmatch(r'[0-9a-f]{40,64}',revision):raise APIError('Source did not return an immutable commit','revision_not_pinned',502)
            files=[]
            for f in payload.get('siblings',[]):
                lfs=f.get('lfs') or {};name=f['rfilename']
                files.append({'path':name,'size':lfs.get('size',f.get('size')),'sha256':lfs.get('sha256'),'git_sha1':f.get('blobId') if not lfs else None,'url':f'{base}/{repo}/resolve/{revision}/'+urllib.parse.quote(name,safe='/')})
        if not files:raise APIError('Source returned no files','empty_repository',502)
        for f in files:
            safe_target(self.root,f['path'])
            if not isinstance(f['size'],int) or f['size']<0 or not (re.fullmatch('[0-9a-f]{64}',f.get('sha256') or '') or re.fullmatch('[0-9a-f]{40}',f.get('git_sha1') or '')):raise APIError('Source does not provide verifiable file identity','identity_unavailable',409)
        return {'repo':repo,'source':params['source'],'revision':revision,'files':files}
    @staticmethod
    def verify_file(path,entry):
        if path.stat().st_size!=entry['size']:raise APIError('Downloaded size mismatch','integrity_error',409)
        digest=hashlib.sha256() if entry.get('sha256') else hashlib.sha1()
        if not entry.get('sha256'):digest.update(f'blob {entry["size"]}\0'.encode())
        with path.open('rb') as f:
            while chunk:=f.read(1048576):digest.update(chunk)
        if digest.hexdigest()!=(entry.get('sha256') or entry.get('git_sha1')):raise APIError('Downloaded content identity mismatch','integrity_error',409)
    def run(self,job):
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
                headers={'Range':f'bytes={offset}-'} if offset else {}
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
        return {'path':str(destination),'revision':manifest['revision'],'verified_files':len(manifest['files'])}
