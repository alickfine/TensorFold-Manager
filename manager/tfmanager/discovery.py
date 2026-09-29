"""Cancellable read-only discovery of model metadata on accessible local disks."""
import json
import os
from pathlib import Path
import time
import platform
import re
import subprocess

class ModelDiscovery:
    SKIP_NAMES={'.git','.Trash','.Trashes','node_modules','.ssh','.gnupg','Mail','Messages','Safari','Cookies'}
    SKIP_PATHS={Path('/System'),Path('/dev'),Path('/proc'),Path('/Network'),Path('/private/var')}
    SKIP_SUFFIXES=('.app','.photoslibrary','.photolibrary','.backupdb','.sparsebundle')
    def __init__(self,models,roots=None,max_dirs=200000,max_seconds=180,excluded_mounts=None):
        self.models=models;self.roots=[Path(p) for p in (roots if roots is not None else ['/'])]
        self.max_dirs=max_dirs;self.max_seconds=max_seconds
        self.mount_limits=[]
        self.excluded_mounts=set(Path(p) for p in (excluded_mounts or []))
        if excluded_mounts is None and roots is None and platform.system()=='Darwin':
            try:
                listing=subprocess.run(['/sbin/mount'],capture_output=True,text=True,timeout=5,check=True).stdout
                for line in listing.splitlines():
                    match=re.search(r' on (.+) \((.+)\)$',line)
                    if match and 'local' not in {item.strip() for item in match[2].split(',')}:
                        self.excluded_mounts.add(Path(match[1]))
            except (OSError,subprocess.SubprocessError):
                self.excluded_mounts.add(Path('/Volumes'));self.mount_limits.append('mount_inventory_unavailable')
    def run(self,job):
        start=time.monotonic();count=0;found=[];seen=set();skipped=0;limits=self.mount_limits.copy()
        def error(_):
            nonlocal skipped
            skipped+=1
        def accessible_directory(path):
            nonlocal skipped
            if any(path.is_relative_to(mount) for mount in self.excluded_mounts):return False
            try:return not path.is_symlink()
            except OSError:skipped+=1;return False
        for root in self.roots:
            job.checkpoint()
            if not accessible_directory(root):continue
            for directory,children,files in os.walk(root,topdown=True,followlinks=False,onerror=error):
                job.checkpoint()
                if count>=self.max_dirs:limits.append('directory_limit');break
                if time.monotonic()-start>=self.max_seconds:limits.append('time_limit');break
                count+=1;path=Path(directory)
                children[:]=[name for name in children if name not in self.SKIP_NAMES and not name.endswith(self.SKIP_SUFFIXES) and path/name not in self.SKIP_PATHS and accessible_directory(path/name)]
                if count%100==0:job.progress(phase='scanning',scanned_dirs=count,found=len(found))
                if 'config.json' not in files or not any(name.endswith('.safetensors') for name in files):continue
                try:
                    config_file=path/'config.json'
                    fd=os.open(config_file,os.O_RDONLY|os.O_NOFOLLOW)
                    with os.fdopen(fd,'r') as stream:
                        if os.fstat(stream.fileno()).st_size>1024*1024:skipped+=1;continue
                        config=json.loads(stream.read(1024*1024+1))
                    if not isinstance(config,dict):continue
                    text=config.get('text_config') or config
                    if not isinstance(text,dict) or not isinstance(text.get('model_type'),str):continue
                    resolved=path.resolve()
                    if resolved not in seen:found.append(resolved);seen.add(resolved)
                except (OSError,ValueError):skipped+=1
            if limits:break
        job.checkpoint()
        # Commit discovered read roots only after successful, non-cancelled traversal.
        current=self.models.store.settings()['model_dirs'];added=[]
        for path in found:
            if any(path.is_relative_to(Path(root)) for root in current+added):continue
            if len(current)+len(added)>=32:limits.append('directory_registration_limit');break
            added.append(str(path))
        job.checkpoint()
        if added:self.models.store.settings_update({'model_dirs':current+added})
        rows=self.models.scan()
        job.progress(phase='completed',scanned_dirs=count,found=len(found))
        return {'models':rows,'added_dirs':added,'scanned_dirs':count,'skipped':skipped,'partial':bool(limits or skipped),'limits':list(dict.fromkeys(limits)),'scope':'accessible_local_disks_excluding_system_packages_and_private_app_data'}
