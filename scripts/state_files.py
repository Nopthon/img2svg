"""Staged state updates with rollback on ordinary I/O errors.

This is not a crash-safe transaction or a concurrent-writer protocol. Callers
must serialize updates to a work directory. A failed rollback retains backups.
"""
import os
import tempfile
from pathlib import Path


def replace_files(files):
    staged={};backups={};committed=[];retain_backups=False
    def stage(path,content):
        fd,name=tempfile.mkstemp(prefix='.img2svg-',dir=path.parent)
        temp=Path(name)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        return temp
    try:
        for destination,content in files.items():
            path=Path(destination).resolve()
            if path in staged:raise ValueError('Duplicate state output: '+str(path))
            path.parent.mkdir(parents=True,exist_ok=True)
            backups[path]=stage(path,path.read_bytes()) if path.exists() else None
            staged[path]=stage(path,content)
        for path,temp in staged.items():
            os.replace(temp,path)
            committed.append(path)
    except BaseException as error:
        failures=[]
        for path in reversed(committed):
            try:
                if backups[path] is None:path.unlink(missing_ok=True)
                else:os.replace(backups[path],path)
            except OSError as rollback_error:failures.append(str(rollback_error))
        if failures:
            retain_backups=True
            recovery=[str(p) for p in backups.values() if p and p.exists()]
            raise RuntimeError(f'State rollback failed; recovery backups: {recovery}; errors: {failures}') from error
        raise
    finally:
        for temp in staged.values():temp.unlink(missing_ok=True)
        if not retain_backups:
            for temp in backups.values():
                if temp:temp.unlink(missing_ok=True)
