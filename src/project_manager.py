"""Portable LibreCrawl project files and retention/storage helpers."""
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta

PROJECT_VERSION = 1

def _safe_json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))

def export_project(path, crawl, urls, links, issues, settings=None, include_assets=False):
    """Write a self-contained .librecrawl project archive."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    manifest = {'format': 'librecrawl-project', 'version': PROJECT_VERSION,
                'created_at': datetime.utcnow().isoformat() + 'Z',
                'credentials_included': False}
    fd, tmp = tempfile.mkstemp(suffix='.zip'); os.close(fd)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', json.dumps(manifest, indent=2))
            archive.writestr('crawl.json', json.dumps(_safe_json(crawl), indent=2))
            archive.writestr('urls.json', json.dumps(_safe_json(urls), indent=2))
            archive.writestr('links.json', json.dumps(_safe_json(links), indent=2))
            archive.writestr('issues.json', json.dumps(_safe_json(issues), indent=2))
            archive.writestr('settings.json', json.dumps(_safe_json(settings or {}), indent=2))
            if include_assets:
                for key in ('screenshot_path', 'archive_path'):
                    for row in urls:
                        asset = row.get(key)
                        if asset and os.path.isfile(asset):
                            archive.write(asset, 'assets/' + os.path.basename(asset))
        shutil.move(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
    return path

def import_project(path):
    if not zipfile.is_zipfile(path):
        raise ValueError('Invalid LibreCrawl project archive')
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if 'manifest.json' not in names or 'crawl.json' not in names:
            raise ValueError('Missing project manifest')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') != 'librecrawl-project':
            raise ValueError('Unsupported project format')
        def read(name, default):
            return json.loads(archive.read(name)) if name in names else default
        return {'manifest': manifest, 'crawl': read('crawl.json', {}),
                'urls': read('urls.json', []), 'links': read('links.json', []),
                'issues': read('issues.json', []), 'settings': read('settings.json', {})}

def restore_project(path, user_id, session_id=None):
    """Import a project archive as a real, completed crawl in the database."""
    project = import_project(path)
    from urllib.parse import urlparse
    from src.crawl_db import create_crawl, save_url_batch, save_links_batch, save_issues_batch, update_crawl_stats, get_db
    crawl = project.get('crawl') or {}
    base_url = crawl.get('base_url') or crawl.get('url') or (project.get('urls') or [{}])[0].get('url') or 'imported://project'
    parsed = urlparse(base_url)
    crawl_id = create_crawl(user_id, session_id or 'project-import', base_url, parsed.netloc, project.get('settings') or crawl.get('config_snapshot') or {})
    if not crawl_id:
        raise RuntimeError('Unable to create imported crawl')
    try:
        if not save_url_batch(crawl_id, project.get('urls', [])):
            raise RuntimeError('Unable to restore project URLs')
        if not save_links_batch(crawl_id, project.get('links', [])):
            raise RuntimeError('Unable to restore project links')
        if not save_issues_batch(crawl_id, project.get('issues', [])):
            raise RuntimeError('Unable to restore project issues')
        update_crawl_stats(crawl_id, discovered=len(project.get('urls', [])), crawled=len(project.get('urls', [])))
        with get_db() as conn:
            conn.execute("UPDATE crawls SET status='completed', completed_at=CURRENT_TIMESTAMP, can_resume=0 WHERE id=?", (crawl_id,))
    except Exception:
        with get_db() as conn:
            conn.execute('DELETE FROM crawls WHERE id=?', (crawl_id,))
        raise
    return {'crawl_id': crawl_id, 'url_count': len(project.get('urls', [])), 'link_count': len(project.get('links', [])), 'issue_count': len(project.get('issues', [])), 'status': 'completed'}

def prune_crawls(retention_days, storage_mode='full', data_dir='data'):
    """Return retention policy metadata; destructive deletion is opt-in by caller."""
    cutoff = datetime.utcnow() - timedelta(days=max(0, int(retention_days)))
    return {'retention_days': int(retention_days), 'storage_mode': storage_mode,
            'cutoff': cutoff.isoformat(), 'data_dir': os.path.abspath(data_dir),
            'policy': 'full' if storage_mode == 'full' else 'summary'}

def apply_retention(user_id, retention_days, storage_mode='full', confirm=False):
    """List or delete a user's expired crawls; deletion requires explicit confirm."""
    from src.crawl_db import get_db
    days = max(0, int(retention_days))
    with get_db() as conn:
        rows = [dict(row) for row in conn.execute("SELECT id, base_url, completed_at, status FROM crawls WHERE user_id=? AND completed_at IS NOT NULL AND completed_at < datetime('now', ?)", (user_id, f'-{days} days'))]
        if confirm and rows:
            conn.executemany('DELETE FROM crawls WHERE id=? AND user_id=?', [(row['id'], user_id) for row in rows])
    return {'retention_days': days, 'storage_mode': storage_mode, 'expired': rows, 'deleted': len(rows) if confirm else 0, 'dry_run': not confirm}
