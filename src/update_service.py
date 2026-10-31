"""Signed-by-checksum application update helper.

Updates are opt-in: checking and downloading are harmless, while installation
requires an explicit ``apply`` request and a SHA-256 match from the manifest.
"""
import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile

CURRENT_VERSION = '1.0.0'


def _version(value):
    return tuple(int(part) if part.isdigit() else 0 for part in str(value).lstrip('v').split('.'))


def check_update(manifest_url, current_version=CURRENT_VERSION):
    if not manifest_url:
        raise ValueError('manifest_url is required')
    with urllib.request.urlopen(manifest_url, timeout=20) as response:
        manifest = json.loads(response.read().decode('utf-8'))
    version = manifest.get('version')
    if not version or not manifest.get('url') or not manifest.get('sha256'):
        raise ValueError('manifest requires version, url and sha256')
    return {'current_version': current_version, 'available_version': version, 'update_available': _version(version) > _version(current_version), 'manifest': manifest}


def download_update(manifest, updates_dir='data/updates'):
    os.makedirs(updates_dir, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix='.zip', dir=updates_dir)
    os.close(fd)
    try:
        with urllib.request.urlopen(manifest['url'], timeout=120) as response, open(temporary, 'wb') as target:
            shutil.copyfileobj(response, target)
        digest = hashlib.sha256()
        with open(temporary, 'rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest().lower() != manifest['sha256'].lower():
            raise ValueError('update checksum mismatch')
        final = os.path.join(updates_dir, f"librecrawl-{manifest['version']}.zip")
        os.replace(temporary, final)
        return {'path': os.path.abspath(final), 'version': manifest['version'], 'sha256': digest.hexdigest(), 'verified': True}
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_update(archive_path, project_root, confirm=False):
    if not confirm:
        return {'applied': False, 'requires_confirmation': True, 'archive': archive_path}
    if not zipfile.is_zipfile(archive_path):
        raise ValueError('update archive is not a zip file')
    staging = tempfile.mkdtemp(prefix='librecrawl-update-')
    try:
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(staging)
        backup = project_root.rstrip(os.sep) + '.backup'
        if os.path.exists(backup):
            raise ValueError('backup path already exists; remove it before applying update')
        shutil.copytree(project_root, backup)
        for name in os.listdir(staging):
            source = os.path.join(staging, name)
            destination = os.path.join(project_root, name)
            if os.path.isdir(source):
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)
        return {'applied': True, 'backup': backup, 'archive': archive_path}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def rollback_update(project_root):
    """Restore the backup created by the last applied update."""
    backup = project_root.rstrip(os.sep) + '.backup'
    if not os.path.isdir(backup):
        raise FileNotFoundError('no update backup found')
    marker = os.path.join(project_root, '.librecrawl-update-rollback')
    if os.path.exists(marker):
        raise ValueError('rollback already in progress')
    open(marker, 'w', encoding='utf-8').close()
    previous = project_root.rstrip(os.sep) + '.pre-rollback'
    try:
        shutil.copytree(project_root, previous, dirs_exist_ok=True)
        for name in os.listdir(backup):
            source = os.path.join(backup, name)
            destination = os.path.join(project_root, name)
            if os.path.isdir(source):
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)
        return {'rolled_back': True, 'backup': backup, 'safety_copy': previous}
    finally:
        try:
            os.unlink(marker)
        except FileNotFoundError:
            pass
