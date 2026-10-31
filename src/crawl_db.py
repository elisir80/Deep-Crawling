"""
Crawl data persistence module
Handles database operations for storing and retrieving crawl data
Enables crash recovery and historical crawl access
"""
import sqlite3
import json
import time
from datetime import datetime
from contextlib import contextmanager

# Database file location (same as auth database) - stored in data/ for Docker volume persistence
import os
import secrets
DB_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'users.db')

@contextmanager
def get_db():
    """Context manager for database connections"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_crawl_tables():
    """Initialize crawl persistence tables"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Main crawls table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crawls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                session_id TEXT NOT NULL,
                base_url TEXT NOT NULL,
                base_domain TEXT,
                status TEXT DEFAULT 'running',

                config_snapshot TEXT,

                urls_discovered INTEGER DEFAULT 0,
                urls_crawled INTEGER DEFAULT 0,
                max_depth_reached INTEGER DEFAULT 0,

                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                last_saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                peak_memory_mb REAL,
                estimated_size_mb REAL,

                can_resume BOOLEAN DEFAULT 1,
                resume_checkpoint TEXT,

                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')

        # Crawled URLs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crawled_urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                crawl_id INTEGER NOT NULL,
                url TEXT NOT NULL,

                status_code INTEGER,
                content_type TEXT,
                size INTEGER,
                is_internal BOOLEAN,
                depth INTEGER,

                title TEXT,
                meta_description TEXT,
                h1 TEXT,
                h2 TEXT,
                h3 TEXT,
                word_count INTEGER,

                canonical_url TEXT,
                lang TEXT,
                charset TEXT,
                viewport TEXT,
                robots TEXT,

                meta_tags TEXT,
                og_tags TEXT,
                twitter_tags TEXT,
                json_ld TEXT,
                analytics TEXT,
                images TEXT,
                resources TEXT,
                accessibility TEXT,
                custom_extractions TEXT,
                directives TEXT,
                content_fingerprint TEXT,
                duplicate_group TEXT,
                duplicate_similarity REAL,
                advanced_data TEXT,
                hreflang TEXT,
                schema_org TEXT,
                redirects TEXT,
                linked_from TEXT,

                external_links INTEGER,
                internal_links INTEGER,

                response_time REAL,
                javascript_rendered BOOLEAN DEFAULT 0,
                error_type TEXT,

                crawled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (crawl_id) REFERENCES crawls(id) ON DELETE CASCADE
            )
        ''')

        # Migration: add error_type column to existing crawled_urls tables
        try:
            cursor.execute('ALTER TABLE crawled_urls ADD COLUMN error_type TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE crawled_urls ADD COLUMN resources TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists
        for column, column_type in (
            ('accessibility', 'TEXT'), ('custom_extractions', 'TEXT'),
            ('directives', 'TEXT'), ('content_fingerprint', 'TEXT'),
            ('duplicate_group', 'TEXT'), ('duplicate_similarity', 'REAL')
        ):
            try:
                cursor.execute(f'ALTER TABLE crawled_urls ADD COLUMN {column} {column_type}')
            except sqlite3.OperationalError:
                pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE crawled_urls ADD COLUMN advanced_data TEXT')
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Links table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crawl_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                crawl_id INTEGER NOT NULL,

                source_url TEXT NOT NULL,
                target_url TEXT NOT NULL,
                anchor_text TEXT,

                is_internal BOOLEAN,
                target_domain TEXT,
                target_status INTEGER,
                placement TEXT,

                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (crawl_id) REFERENCES crawls(id) ON DELETE CASCADE
            )
        ''')

        # Issues table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crawl_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                crawl_id INTEGER NOT NULL,

                url TEXT NOT NULL,
                type TEXT,
                category TEXT,
                issue TEXT,
                details TEXT,

                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (crawl_id) REFERENCES crawls(id) ON DELETE CASCADE
            )
        ''')

        # Queue table for crash recovery
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crawl_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                crawl_id INTEGER NOT NULL,

                url TEXT NOT NULL,
                depth INTEGER,
                priority INTEGER DEFAULT 0,

                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (crawl_id) REFERENCES crawls(id) ON DELETE CASCADE,
                UNIQUE(crawl_id, url)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crawl_shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                crawl_id INTEGER NOT NULL,
                owner_user_id INTEGER,
                share_token TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (crawl_id) REFERENCES crawls(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crawl_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT NOT NULL,
                url TEXT NOT NULL, mode TEXT DEFAULT 'spider', interval_seconds INTEGER DEFAULT 86400,
                next_run_at TIMESTAMP, timezone TEXT DEFAULT 'UTC', recipients TEXT, enabled INTEGER DEFAULT 1,
                settings_snapshot TEXT, last_run_at TIMESTAMP, last_status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        try:
            cursor.execute("ALTER TABLE crawl_schedules ADD COLUMN timezone TEXT DEFAULT 'UTC'")
        except sqlite3.OperationalError:
            pass
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crawl_projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT NOT NULL,
                path TEXT NOT NULL, retention_days INTEGER DEFAULT 90, storage_mode TEXT DEFAULT 'full',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS seo_rank_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, crawl_id INTEGER,
                keyword TEXT NOT NULL, url TEXT, position INTEGER, country TEXT DEFAULT 'global',
                device TEXT DEFAULT 'desktop', serp_features TEXT, captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (crawl_id) REFERENCES crawls(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS seo_cwv_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, crawl_id INTEGER,
                url TEXT NOT NULL, lcp REAL, inp REAL, cls REAL, ttfb REAL, fcp REAL,
                passed INTEGER, captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (crawl_id) REFERENCES crawls(id) ON DELETE CASCADE
            )
        ''')

        # Forward-compatible migration for competitor rank tracking.
        rank_columns = {row[1] for row in cursor.execute('PRAGMA table_info(seo_rank_snapshots)').fetchall()}
        if 'competitor' not in rank_columns:
            cursor.execute('ALTER TABLE seo_rank_snapshots ADD COLUMN competitor TEXT')

        # Create indexes for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawls_user_status ON crawls(user_id, status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawls_session ON crawls(session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawled_urls_crawl ON crawled_urls(crawl_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawled_urls_url ON crawled_urls(crawl_id, url)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawled_urls_status ON crawled_urls(crawl_id, status_code)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawl_links_crawl ON crawl_links(crawl_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawl_links_source ON crawl_links(crawl_id, source_url)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawl_links_target ON crawl_links(crawl_id, target_url)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawl_issues_crawl ON crawl_issues(crawl_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawl_issues_url ON crawl_issues(crawl_id, url)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawl_issues_category ON crawl_issues(crawl_id, category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crawl_queue_crawl ON crawl_queue(crawl_id)')

        print("Crawl persistence tables initialized successfully")

def create_crawl(user_id, session_id, base_url, base_domain, config_snapshot):
    """
    Create a new crawl record
    Returns the crawl_id
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO crawls (user_id, session_id, base_url, base_domain, config_snapshot, status)
                VALUES (?, ?, ?, ?, ?, 'running')
            ''', (user_id, session_id, base_url, base_domain, json.dumps(config_snapshot)))

            crawl_id = cursor.lastrowid
            print(f"Created new crawl record: ID={crawl_id}, URL={base_url}")
            return crawl_id
    except Exception as e:
        print(f"Error creating crawl: {e}")
        return None

def update_crawl_stats(crawl_id, discovered=None, crawled=None, max_depth=None, peak_memory_mb=None, estimated_size_mb=None):
    """Update crawl statistics"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            updates = []
            params = []

            if discovered is not None:
                updates.append("urls_discovered = ?")
                params.append(discovered)
            if crawled is not None:
                updates.append("urls_crawled = ?")
                params.append(crawled)
            if max_depth is not None:
                updates.append("max_depth_reached = ?")
                params.append(max_depth)
            if peak_memory_mb is not None:
                updates.append("peak_memory_mb = ?")
                params.append(peak_memory_mb)
            if estimated_size_mb is not None:
                updates.append("estimated_size_mb = ?")
                params.append(estimated_size_mb)

            updates.append("last_saved_at = CURRENT_TIMESTAMP")
            params.append(crawl_id)

            query = f"UPDATE crawls SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)

            return True
    except Exception as e:
        print(f"Error updating crawl stats: {e}")
        return False

def save_url_batch(crawl_id, urls):
    """
    Batch save crawled URLs
    urls: list of URL result dictionaries from crawler
    """
    if not urls:
        return True

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Prepare batch insert
            rows = []
            for url_data in urls:
                row = (
                    crawl_id,
                    url_data.get('url'),
                    url_data.get('status_code'),
                    url_data.get('content_type'),
                    url_data.get('size'),
                    url_data.get('is_internal'),
                    url_data.get('depth'),
                    url_data.get('title'),
                    url_data.get('meta_description'),
                    url_data.get('h1'),
                    json.dumps(url_data.get('h2', [])),
                    json.dumps(url_data.get('h3', [])),
                    url_data.get('word_count'),
                    url_data.get('canonical_url'),
                    url_data.get('lang'),
                    url_data.get('charset'),
                    url_data.get('viewport'),
                    url_data.get('robots'),
                    json.dumps(url_data.get('meta_tags', {})),
                    json.dumps(url_data.get('og_tags', {})),
                    json.dumps(url_data.get('twitter_tags', {})),
                    json.dumps(url_data.get('json_ld', [])),
                json.dumps(url_data.get('analytics', {})),
                json.dumps(url_data.get('images', [])),
                json.dumps(url_data.get('resources', [])),
                json.dumps(url_data.get('accessibility', {})),
                json.dumps(url_data.get('custom_extractions', {})),
                json.dumps(url_data.get('directives', {})),
                url_data.get('content_fingerprint'),
                url_data.get('duplicate_group'),
                url_data.get('duplicate_similarity'),
                json.dumps({key: url_data.get(key) for key in (
                    'pagination', 'amp_url', 'meta_refresh', 'srcset', 'http_headers',
                    'cookies', 'security', 'html_validation', 'content_analysis',
                    'pdf_pages', 'pdf_text', 'pdf_metadata', 'pdf_error',
                    'screenshot_path', 'rendered_archive_path', 'javascript_errors',
                    'media_type', 'media_metadata', 'swf_detected', 'custom_search', 'mobile_alternate', 'duplicate_md5', 'duplicate_simhash',
                    'source_html', 'rendered_html', 'extracted_text', 'snapshot_type', 'snapshot_captured_at', 'render_diagnostics'
                ) if key in url_data}, ensure_ascii=False, default=str),
                json.dumps(url_data.get('hreflang', [])),
                    json.dumps(url_data.get('schema_org', [])),
                    json.dumps(url_data.get('redirects', [])),
                    json.dumps(url_data.get('linked_from', [])),
                    url_data.get('external_links'),
                    url_data.get('internal_links'),
                    url_data.get('response_time'),
                    url_data.get('javascript_rendered', False),
                    url_data.get('error_type')
                )
                rows.append(row)

            placeholders = ', '.join('?' for _ in rows[0])
            cursor.executemany(f'''
                INSERT INTO crawled_urls (
                    crawl_id, url, status_code, content_type, size, is_internal, depth,
                    title, meta_description, h1, h2, h3, word_count,
                    canonical_url, lang, charset, viewport, robots,
                    meta_tags, og_tags, twitter_tags, json_ld, analytics, images, resources,
                    accessibility, custom_extractions, directives, content_fingerprint,
                    duplicate_group, duplicate_similarity,
                    advanced_data,
                    hreflang, schema_org, redirects, linked_from,
                    external_links, internal_links, response_time, javascript_rendered,
                    error_type
            ) VALUES ({placeholders})
            ''', rows)

            print(f"Saved {len(urls)} URLs to database for crawl {crawl_id}")
            return True

    except Exception as e:
        print(f"Error saving URL batch: {e}")
        import traceback
        traceback.print_exc()
        return False

def save_links_batch(crawl_id, links):
    """Batch save links"""
    if not links:
        return True

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            rows = []
            for link in links:
                row = (
                    crawl_id,
                    link.get('source_url'),
                    link.get('target_url'),
                    link.get('anchor_text'),
                    link.get('is_internal'),
                    link.get('target_domain'),
                    link.get('target_status'),
                    link.get('placement', 'body')
                )
                rows.append(row)

            cursor.executemany('''
                INSERT INTO crawl_links (
                    crawl_id, source_url, target_url, anchor_text,
                    is_internal, target_domain, target_status, placement
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', rows)

            print(f"Saved {len(links)} links to database for crawl {crawl_id}")
            return True

    except Exception as e:
        print(f"Error saving links batch: {e}")
        return False

def save_issues_batch(crawl_id, issues):
    """Batch save SEO issues"""
    if not issues:
        return True

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            rows = []
            for issue in issues:
                row = (
                    crawl_id,
                    issue.get('url'),
                    issue.get('type'),
                    issue.get('category'),
                    issue.get('issue'),
                    issue.get('details')
                )
                rows.append(row)

            cursor.executemany('''
                INSERT INTO crawl_issues (
                    crawl_id, url, type, category, issue, details
                ) VALUES (?, ?, ?, ?, ?, ?)
            ''', rows)

            print(f"Saved {len(issues)} issues to database for crawl {crawl_id}")
            return True

    except Exception as e:
        print(f"Error saving issues batch: {e}")
        return False

def save_checkpoint(crawl_id, checkpoint_data):
    """Save queue checkpoint for crash recovery"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE crawls
                SET resume_checkpoint = ?, last_saved_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (json.dumps(checkpoint_data), crawl_id))

            return True
    except Exception as e:
        print(f"Error saving checkpoint: {e}")
        return False

def set_crawl_status(crawl_id, status):
    """
    Update crawl status
    status: 'running', 'paused', 'completed', 'failed', 'stopped', 'archived'
    """
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            if status in ['completed', 'failed', 'stopped']:
                cursor.execute('''
                    UPDATE crawls
                    SET status = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (status, crawl_id))
            else:
                cursor.execute('''
                    UPDATE crawls
                    SET status = ?
                    WHERE id = ?
                ''', (status, crawl_id))

            print(f"Updated crawl {crawl_id} status to: {status}")
            return True

    except Exception as e:
        print(f"Error setting crawl status: {e}")
        return False

def get_crawl_by_id(crawl_id):
    """Get crawl metadata by ID"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM crawls WHERE id = ?
            ''', (crawl_id,))

            row = cursor.fetchone()
            if row:
                crawl = dict(row)
                # Parse JSON fields
                if crawl.get('config_snapshot'):
                    crawl['config_snapshot'] = json.loads(crawl['config_snapshot'])
                if crawl.get('resume_checkpoint'):
                    crawl['resume_checkpoint'] = json.loads(crawl['resume_checkpoint'])
                return crawl
            return None

    except Exception as e:
        print(f"Error fetching crawl: {e}")
        return None

def get_user_crawls(user_id, limit=50, offset=0, status_filter=None):
    """Get all crawls for a user"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            query = 'SELECT * FROM crawls WHERE user_id = ?'
            params = [user_id]

            if status_filter:
                query += ' AND status = ?'
                params.append(status_filter)

            query += ' ORDER BY started_at DESC LIMIT ? OFFSET ?'
            params.extend([limit, offset])

            cursor.execute(query, params)

            crawls = []
            for row in cursor.fetchall():
                crawl = dict(row)
                # Don't parse full config for list view
                crawl['config_snapshot'] = None  # Save bandwidth
                crawls.append(crawl)

            return crawls

    except Exception as e:
        print(f"Error fetching user crawls: {e}")
        return []

def load_crawled_urls(crawl_id, limit=None, offset=0):
    """Load all crawled URLs for a crawl"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            query = 'SELECT * FROM crawled_urls WHERE crawl_id = ? ORDER BY crawled_at'
            params = [crawl_id]

            if limit:
                query += ' LIMIT ? OFFSET ?'
                params.extend([limit, offset])

            cursor.execute(query, params)

            urls = []
            for row in cursor.fetchall():
                url_data = dict(row)
                # Parse JSON fields
                for field in ['h2', 'h3', 'meta_tags', 'og_tags', 'twitter_tags',
                             'json_ld', 'analytics', 'images', 'resources', 'accessibility',
                             'custom_extractions', 'directives', 'hreflang',
                             'schema_org', 'redirects', 'linked_from']:
                    if url_data.get(field):
                        try:
                            url_data[field] = json.loads(url_data[field])
                        except:
                            url_data[field] = []

                if url_data.get('advanced_data'):
                    try:
                        advanced = json.loads(url_data['advanced_data'])
                        if isinstance(advanced, dict):
                            url_data.update(advanced)
                    except (TypeError, ValueError):
                        pass

                urls.append(url_data)

            return urls

    except Exception as e:
        print(f"Error loading crawled URLs: {e}")
        return []

def load_crawl_links(crawl_id, limit=None, offset=0):
    """Load all links for a crawl"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            query = 'SELECT * FROM crawl_links WHERE crawl_id = ?'
            params = [crawl_id]

            if limit:
                query += ' LIMIT ? OFFSET ?'
                params.extend([limit, offset])

            cursor.execute(query, params)

            return [dict(row) for row in cursor.fetchall()]

    except Exception as e:
        print(f"Error loading links: {e}")
        return []

def load_crawl_issues(crawl_id, limit=None, offset=0):
    """Load all issues for a crawl"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            query = 'SELECT * FROM crawl_issues WHERE crawl_id = ?'
            params = [crawl_id]

            if limit:
                query += ' LIMIT ? OFFSET ?'
                params.extend([limit, offset])

            cursor.execute(query, params)

            return [dict(row) for row in cursor.fetchall()]

    except Exception as e:
        print(f"Error loading issues: {e}")
        return []

def create_crawl_share(crawl_id, owner_user_id=None, expires_at=None):
    """Create a revocable-by-expiry read-only share token for a crawl."""
    token = secrets.token_urlsafe(32)
    try:
        with get_db() as conn:
            conn.execute('''INSERT INTO crawl_shares
                (crawl_id, owner_user_id, share_token, expires_at) VALUES (?, ?, ?, ?)''',
                (crawl_id, owner_user_id, token, expires_at))
        return token
    except Exception as exc:
        print(f"Error creating crawl share: {exc}")
        return None

def get_crawl_share(token):
    """Return a share only when it exists and has not expired."""
    try:
        with get_db() as conn:
            row = conn.execute('''SELECT * FROM crawl_shares
                WHERE share_token = ? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)''', (token,)).fetchone()
            return dict(row) if row else None
    except Exception as exc:
        print(f"Error loading crawl share: {exc}")
        return None

def revoke_crawl_share(token, owner_user_id=None):
    """Revoke a crawl share owned by the requesting user."""
    try:
        with get_db() as conn:
            query = 'DELETE FROM crawl_shares WHERE share_token = ?'
            params = [token]
            if owner_user_id is not None:
                query += ' AND owner_user_id = ?'; params.append(owner_user_id)
            cursor = conn.execute(query, params)
            return cursor.rowcount > 0
    except Exception as exc:
        print(f"Error revoking crawl share: {exc}")
        return False

def get_resume_data(crawl_id):
    """Get all data needed to resume a crawl"""
    crawl = get_crawl_by_id(crawl_id)
    if not crawl:
        return None

    # Only allow resume for paused/failed/running crawls
    if crawl['status'] not in ['paused', 'failed', 'running']:
        return None

    return crawl

def delete_crawl(crawl_id):
    """Delete a crawl and all associated data (CASCADE handles related tables)"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM crawls WHERE id = ?', (crawl_id,))
            print(f"Deleted crawl {crawl_id} and all associated data")
            return True
    except Exception as e:
        print(f"Error deleting crawl: {e}")
        return False

def get_crashed_crawls():
    """Find crawls that were running when server crashed"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM crawls
                WHERE status = 'running'
                ORDER BY started_at DESC
            ''')

            crawls = []
            for row in cursor.fetchall():
                crawl = dict(row)
                crawls.append(crawl)

            return crawls

    except Exception as e:
        print(f"Error finding crashed crawls: {e}")
        return []

def cleanup_old_crawls(days=90):
    """Delete crawls older than specified days (optional maintenance)"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM crawls
                WHERE started_at < datetime('now', '-' || ? || ' days')
                AND status IN ('completed', 'failed', 'stopped')
            ''', (days,))

            deleted = cursor.rowcount
            print(f"Cleaned up {deleted} old crawls")
            return deleted

    except Exception as e:
        print(f"Error cleaning up old crawls: {e}")
        return 0

def get_crawl_count(user_id):
    """Get total number of crawls for a user"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) as count FROM crawls WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            return result['count'] if result else 0
    except Exception as e:
        print(f"Error getting crawl count: {e}")
        return 0

def get_database_size_mb():
    """Get total database size in MB"""
    try:
        import os
        if os.path.exists(DB_FILE):
            size_bytes = os.path.getsize(DB_FILE)
            return round(size_bytes / (1024 * 1024), 2)
        return 0
    except Exception as e:
        print(f"Error getting database size: {e}")
        return 0

def create_schedule(user_id, name, url, mode='spider', interval_seconds=86400, recipients=None, settings=None, timezone='UTC'):
    with get_db() as conn:
        cur = conn.execute('''INSERT INTO crawl_schedules
            (user_id,name,url,mode,interval_seconds,next_run_at,timezone,recipients,settings_snapshot)
            VALUES (?,?,?,?,?,datetime('now'),?,?,?)''',
            (user_id, name, url, mode, max(1, int(interval_seconds)), timezone or 'UTC', json.dumps(recipients or []), json.dumps(settings or {})))
        return cur.lastrowid

def list_schedules(user_id):
    with get_db() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM crawl_schedules WHERE user_id=? ORDER BY id DESC', (user_id,))]

def delete_schedule(schedule_id, user_id):
    with get_db() as conn:
        cur = conn.execute('DELETE FROM crawl_schedules WHERE id=? AND user_id=?', (schedule_id, user_id))
        return cur.rowcount > 0

def save_rank_snapshot(user_id, snapshot, crawl_id=None):
    with get_db() as conn:
        cur=conn.execute('''INSERT INTO seo_rank_snapshots
            (user_id,crawl_id,keyword,url,position,country,device,serp_features,captured_at,competitor)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',(user_id,crawl_id,snapshot.get('keyword',''),snapshot.get('url'),
            snapshot.get('position'),snapshot.get('country','global'),snapshot.get('device','desktop'),
            json.dumps(snapshot.get('serp_features',[])),snapshot.get('captured_at'),snapshot.get('competitor')))
        return cur.lastrowid

def list_rank_snapshots(user_id, keyword=None, url=None, limit=500):
    with get_db() as conn:
        query='SELECT * FROM seo_rank_snapshots WHERE user_id=?'; args=[user_id]
        if keyword: query+=' AND keyword=?'; args.append(keyword)
        if url: query+=' AND url=?'; args.append(url)
        query+=' ORDER BY captured_at DESC LIMIT ?'; args.append(int(limit))
        rows=[dict(x) for x in conn.execute(query,args)]
        for row in rows:
            row['serp_features']=json.loads(row.get('serp_features') or '[]')
        return rows

def save_cwv_snapshot(user_id, snapshot, crawl_id=None):
    with get_db() as conn:
        cur=conn.execute('''INSERT INTO seo_cwv_snapshots
            (user_id,crawl_id,url,lcp,inp,cls,ttfb,fcp,passed,captured_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',(user_id,crawl_id,snapshot.get('url',''),snapshot.get('lcp'),
            snapshot.get('inp'),snapshot.get('cls'),snapshot.get('ttfb'),snapshot.get('fcp'),
            int(bool(snapshot.get('passed'))),snapshot.get('snapshot')))
        return cur.lastrowid

def list_cwv_snapshots(user_id, url=None, limit=500):
    with get_db() as conn:
        if url:
            rows=conn.execute('SELECT * FROM seo_cwv_snapshots WHERE user_id=? AND url=? ORDER BY captured_at DESC LIMIT ?', (user_id,url,int(limit)))
        else:
            rows=conn.execute('SELECT * FROM seo_cwv_snapshots WHERE user_id=? ORDER BY captured_at DESC LIMIT ?', (user_id,int(limit)))
        return [dict(x) for x in rows]
