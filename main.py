import threading
import time
import csv
import json
import xml.etree.ElementTree as ET
import uuid
import webbrowser
import argparse
import secrets
import string
import os
from io import StringIO
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, Response, send_file
from flask_compress import Compress
from functools import wraps
from src.crawler import WebCrawler
from src.settings_manager import SettingsManager
from src.auth_db import init_db, create_user, authenticate_user, get_user_by_id, log_guest_crawl, get_guest_crawls_last_24h, verify_user, set_user_tier, create_verification_token, verify_token, get_user_by_email, get_all_users
from src.email_service import send_verification_email, send_welcome_email

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Parse command line arguments
parser = argparse.ArgumentParser(description='Deep Crawling - SEO Spider Tool')
parser.add_argument('--local', '-l', action='store_true',
                    help='Run in local mode (all users get admin tier, no rate limits)')
parser.add_argument('--disable-register', '-dr', action='store_true',
                    help='Disable new user registrations')
parser.add_argument('--disable-guest', '-dg', action='store_true',
                    help='Disable guest login')
parser.add_argument('--demo', '-dm', action='store_true',
                    help='Demo mode: 1.5GB memory limit per user, crawls auto-stop at limit')
parser.add_argument('--dangerously-skip-auth', '-dsa', action='store_true',
                    help='DANGEROUS: Allow anyone to log in as any username with no password. '
                         'The username is only used to separate per-user sessions. '
                         'Do NOT use on a public network or in production.')
args = parser.parse_args()

LOCAL_MODE = args.local or os.getenv('LOCAL_MODE', '').lower() in ('true', '1', 'yes')
DISABLE_REGISTER = args.disable_register or os.getenv('REGISTRATION_DISABLED', '').lower() in ('true', '1', 'yes')
DISABLE_GUEST = args.disable_guest or os.getenv('DISABLE_GUEST', '').lower() in ('true', '1', 'yes')
DEMO_MODE = args.demo or os.getenv('DEMO_MODE', '').lower() in ('true', '1', 'yes')
SKIP_AUTH = args.dangerously_skip_auth or os.getenv('DANGEROUSLY_SKIP_AUTH', '').lower() in ('true', '1', 'yes')

app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
_scheduler_worker = None
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
if not os.environ.get('SECRET_KEY'):
    print('⚠️  WARNING: SECRET_KEY not set — using an ephemeral random key. '
          'Sessions will not persist across restarts. Set SECRET_KEY in production.', flush=True)

# Enable compression for all responses
Compress(app)

@app.route('/favicon.ico')
def favicon():
    """Avoid a noisy browser 404 when no custom favicon is configured."""
    return Response(status=204)

# Initialize database on startup
init_db()

def generate_random_password(length=16):
    """Generate a random password with letters, digits, and symbols"""
    alphabet = string.ascii_letters + string.digits + string.punctuation
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def auto_login_local_mode():
    """Auto-login for local mode - creates or logs into 'local' admin account"""
    import sqlite3
    try:
        conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'users.db'))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check if 'local' user exists
        cursor.execute('SELECT id, username, tier FROM users WHERE username = ?', ('local',))
        user = cursor.fetchone()

        if user:
            # User exists, just log them in
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['tier'] = 'admin'
            session.permanent = True
            print(f"Auto-logged in as existing 'local' user (ID: {user['id']})")
        else:
            # Create new local user with random password
            random_password = generate_random_password()
            from src.auth_db import hash_password
            password_hash = hash_password(random_password)

            cursor.execute('''
                INSERT INTO users (username, email, password_hash, verified, tier)
                VALUES (?, ?, ?, 1, 'admin')
            ''', ('local', 'local@localhost', password_hash))
            conn.commit()

            user_id = cursor.lastrowid

            # Log in the new user
            session['user_id'] = user_id
            session['username'] = 'local'
            session['tier'] = 'admin'
            session.permanent = True

            print(f"Created and auto-logged in as new 'local' admin user (ID: {user_id})")
            print(f"Generated password: {random_password}")

        conn.close()
        return True
    except Exception as e:
        print(f"Error in auto_login_local_mode: {e}")
        return False

def skip_auth_login(username):
    """Skip-auth login: create user record if missing, log them in.

    Each username gets its own user_id, which drives per-user crawler
    instance and settings isolation. No password is checked. Always
    grants admin tier (matches local-mode behavior).

    Returns (success, message).
    """
    import sqlite3
    try:
        conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'users.db'))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('SELECT id, username FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()

        if user:
            user_id = user['id']
        else:
            from src.auth_db import hash_password
            random_password = generate_random_password()
            password_hash = hash_password(random_password)
            cursor.execute('''
                INSERT INTO users (username, email, password_hash, verified, tier)
                VALUES (?, ?, ?, 1, 'admin')
            ''', (username, f'{username}@skipauth.local', password_hash))
            conn.commit()
            user_id = cursor.lastrowid

        conn.close()

        session['user_id'] = user_id
        session['username'] = username
        session['tier'] = 'admin'
        session.permanent = True

        return True, 'Logged in (authentication skipped)'
    except sqlite3.IntegrityError as e:
        # Most likely the generated email collides with an existing account
        # whose email happens to match. Fall back to a clearer message.
        return False, f'Username conflict: try a different username ({e})'
    except Exception as e:
        print(f"Error in skip_auth_login: {e}")
        return False, f'Login error: {str(e)}'

if LOCAL_MODE:
    print("=" * 60)
    print("LOCAL MODE ENABLED")
    print("All users will have admin tier access")
    print("No rate limits or tier restrictions")
    print("Auto-login enabled with 'local' admin account")
    print("=" * 60)

if DISABLE_REGISTER:
    print("=" * 60)
    print("REGISTRATION DISABLED")
    print("New user registrations are not allowed")
    print("=" * 60)

if DISABLE_GUEST:
    print("=" * 60)
    print("GUEST MODE DISABLED")
    print("Guest login is not allowed")
    print("=" * 60)

if DEMO_MODE:
    print("=" * 60)
    print("DEMO MODE ENABLED")
    print("Memory limit: 1.5GB per user")
    print("Crawls will auto-stop when limit is reached")
    print("=" * 60)

if SKIP_AUTH:
    print("=" * 60)
    print("⚠️  DANGEROUSLY SKIP AUTH ENABLED")
    print("Anyone can log in as any username with no password!")
    print("Username is used only to separate per-user sessions.")
    print("DO NOT use on a public network or production server!")
    print("=" * 60)

def get_client_ip():
    """Get the real client IP address, checking Cloudflare headers first"""
    # Check Cloudflare header first
    if 'CF-Connecting-IP' in request.headers:
        return request.headers['CF-Connecting-IP']
    # Check other common proxy headers
    if 'X-Forwarded-For' in request.headers:
        # X-Forwarded-For can contain multiple IPs, take the first one
        return request.headers['X-Forwarded-For'].split(',')[0].strip()
    if 'X-Real-IP' in request.headers:
        return request.headers['X-Real-IP']
    # Fall back to direct connection IP
    return request.remote_addr

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # In local mode, auto-login if not already logged in
        if LOCAL_MODE and 'user_id' not in session:
            auto_login_local_mode()
        elif 'user_id' not in session:
            # Not in local mode and not logged in
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Authentication required'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Require an authenticated administrator for account management APIs."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if session.get('tier') != 'admin':
            return jsonify({'success': False, 'error': 'Administrator access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# Multi-tenant crawler instances
crawler_instances = {}  # session_id -> {'crawler': WebCrawler, 'settings': SettingsManager, 'last_accessed': datetime}
instances_lock = threading.Lock()

def get_or_create_crawler():
    """Get or create a crawler instance for the current session"""
    # Get or create session ID
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())

    session_id = session['session_id']
    user_id = session.get('user_id')  # Get user_id from session
    tier = session.get('tier', 'guest')  # Get tier from session

    with instances_lock:
        # Check if crawler exists for this session
        if session_id not in crawler_instances:
            print(f"Creating new crawler instance for session: {session_id}, user: {user_id}, tier: {tier}")
            crawler_instances[session_id] = {
                'crawler': WebCrawler(),
                'settings': SettingsManager(session_id=session_id, user_id=user_id, tier=tier),  # Per-user settings
                'last_accessed': datetime.now()
            }
        else:
            # Update last accessed time
            crawler_instances[session_id]['last_accessed'] = datetime.now()

        return crawler_instances[session_id]['crawler']

def get_session_settings():
    """Get the settings manager for the current session"""
    # Get or create session ID
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())

    session_id = session['session_id']
    user_id = session.get('user_id')  # Get user_id from session
    tier = session.get('tier', 'guest')  # Get tier from session

    with instances_lock:
        # Create instance if it doesn't exist
        if session_id not in crawler_instances:
            print(f"Creating new settings instance for session: {session_id}, user: {user_id}, tier: {tier}")
            crawler_instances[session_id] = {
                'crawler': WebCrawler(),
                'settings': SettingsManager(session_id=session_id, user_id=user_id, tier=tier),
                'last_accessed': datetime.now()
            }
        else:
            # Update last accessed time
            crawler_instances[session_id]['last_accessed'] = datetime.now()

        return crawler_instances[session_id]['settings']

def cleanup_old_instances():
    """Remove crawler instances that haven't been accessed in 1 hour"""
    timeout = timedelta(hours=1)
    now = datetime.now()

    with instances_lock:
        sessions_to_remove = []
        for session_id, instance_data in crawler_instances.items():
            if now - instance_data['last_accessed'] > timeout:
                sessions_to_remove.append(session_id)

        for session_id in sessions_to_remove:
            print(f"Cleaning up crawler instance for session: {session_id}")
            # Stop any running crawls
            try:
                crawler_instances[session_id]['crawler'].stop_crawl()
            except:
                pass
            del crawler_instances[session_id]

        if sessions_to_remove:
            print(f"Cleaned up {len(sessions_to_remove)} inactive crawler instances")

def start_cleanup_thread():
    """Start background thread to cleanup old instances"""
    def cleanup_loop():
        while True:
            time.sleep(300)  # Check every 5 minutes
            try:
                cleanup_old_instances()
            except Exception as e:
                print(f"Error in cleanup thread: {e}")

    cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
    cleanup_thread.start()
    print("Started crawler instance cleanup thread")

def generate_csv_export(urls, fields):
    """Generate CSV export content"""
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()

    for url_data in urls:
        row = {}
        for field in fields:
            value = url_data.get(field, '')

            # Handle complex data types for CSV
            if field == 'analytics' and isinstance(value, dict):
                analytics_list = []
                if value.get('gtag') or value.get('ga4_id'): analytics_list.append('GA4')
                if value.get('google_analytics'): analytics_list.append('GA')
                if value.get('gtm_id'): analytics_list.append('GTM')
                if value.get('facebook_pixel'): analytics_list.append('FB')
                if value.get('hotjar'): analytics_list.append('HJ')
                if value.get('mixpanel'): analytics_list.append('MP')
                row[field] = ', '.join(analytics_list)
            elif field == 'og_tags' and isinstance(value, dict):
                row[field] = f"{len(value)} tags" if value else ''
            elif field == 'twitter_tags' and isinstance(value, dict):
                row[field] = f"{len(value)} tags" if value else ''
            elif field == 'json_ld' and isinstance(value, list):
                row[field] = f"{len(value)} scripts" if value else ''
            elif field == 'images' and isinstance(value, list):
                row[field] = f"{len(value)} images" if value else ''
            elif field == 'internal_links' and isinstance(value, (int, float)):
                row[field] = f"{int(value)} internal links" if value else '0 internal links'
            elif field == 'external_links' and isinstance(value, (int, float)):
                row[field] = f"{int(value)} external links" if value else '0 external links'
            elif field == 'h2' and isinstance(value, list):
                row[field] = ', '.join(value[:3]) + ('...' if len(value) > 3 else '')
            elif field == 'h3' and isinstance(value, list):
                row[field] = ', '.join(value[:3]) + ('...' if len(value) > 3 else '')
            elif isinstance(value, (dict, list)):
                row[field] = str(value)
            else:
                row[field] = value

        writer.writerow(row)

    return output.getvalue()

def generate_json_export(urls, fields):
    """Generate JSON export content"""
    filtered_urls = []
    for url_data in urls:
        filtered_data = {}
        for field in fields:
            value = url_data.get(field, '')
            # Keep complex data structures intact in JSON
            filtered_data[field] = value
        filtered_urls.append(filtered_data)

    return json.dumps({
        'export_date': time.strftime('%Y-%m-%d %H:%M:%S'),
        'total_urls': len(filtered_urls),
        'fields': fields,
        'data': filtered_urls
    }, indent=2, default=str)

def generate_xml_export(urls, fields):
    """Generate XML export content"""
    root = ET.Element('librecrawl_export')
    root.set('export_date', time.strftime('%Y-%m-%d %H:%M:%S'))
    root.set('total_urls', str(len(urls)))

    urls_element = ET.SubElement(root, 'urls')

    for url_data in urls:
        url_element = ET.SubElement(urls_element, 'url')
        for field in fields:
            field_element = ET.SubElement(url_element, field)
            field_element.text = str(url_data.get(field, ''))

    return ET.tostring(root, encoding='unicode')

def generate_links_csv_export(links):
    """Generate CSV export for links data"""
    output = StringIO()
    fieldnames = ['source_url', 'target_url', 'anchor_text', 'is_internal', 'target_domain', 'target_status', 'placement']
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for link in links:
        row = {
            'source_url': link.get('source_url', ''),
            'target_url': link.get('target_url', ''),
            'anchor_text': link.get('anchor_text', ''),
            'is_internal': 'Yes' if link.get('is_internal') else 'No',
            'target_domain': link.get('target_domain', ''),
            'target_status': link.get('target_status', 'Not crawled'),
            'placement': link.get('placement', 'body')
        }
        writer.writerow(row)

    return output.getvalue()

def generate_links_json_export(links):
    """Generate JSON export for links data"""
    return json.dumps(links, indent=2)

def filter_issues_by_exclusion_patterns(issues, exclusion_patterns):
    """Filter issues based on exclusion patterns (applies current settings to loaded crawls)"""
    from fnmatch import fnmatch
    from urllib.parse import urlparse

    if not exclusion_patterns:
        return issues

    filtered_issues = []

    for issue in issues:
        url = issue.get('url', '')
        parsed = urlparse(url)
        path = parsed.path

        # Check if URL matches any exclusion pattern
        should_exclude = False
        for pattern in exclusion_patterns:
            if not pattern.strip() or pattern.strip().startswith('#'):
                continue

            if '*' in pattern:
                if fnmatch(path, pattern):
                    should_exclude = True
                    break
            elif path == pattern or path.startswith(pattern.rstrip('*')):
                should_exclude = True
                break

        if not should_exclude:
            filtered_issues.append(issue)

    return filtered_issues

def generate_issues_csv_export(issues):
    """Generate CSV export for issues data"""
    output = StringIO()
    fieldnames = ['url', 'type', 'category', 'issue', 'details']
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for issue in issues:
        row = {
            'url': issue.get('url', ''),
            'type': issue.get('type', ''),
            'category': issue.get('category', ''),
            'issue': issue.get('issue', ''),
            'details': issue.get('details', '')
        }
        writer.writerow(row)

    return output.getvalue()

def generate_issues_json_export(issues):
    """Generate JSON export for issues data"""
    # Group issues by URL for better organization
    issues_by_url = {}
    for issue in issues:
        url = issue.get('url', '')
        if url not in issues_by_url:
            issues_by_url[url] = []
        issues_by_url[url].append({
            'type': issue.get('type', ''),
            'category': issue.get('category', ''),
            'issue': issue.get('issue', ''),
            'details': issue.get('details', '')
        })

    return json.dumps({
        'export_date': time.strftime('%Y-%m-%d %H:%M:%S'),
        'total_issues': len(issues),
        'total_urls_with_issues': len(issues_by_url),
        'issues_by_url': issues_by_url,
        'all_issues': issues
    }, indent=2)

@app.route('/login')
def login_page():
    # In local mode, auto-login and redirect to index
    if LOCAL_MODE:
        auto_login_local_mode()
        return redirect(url_for('index'))
    # Redirect to app if already logged in
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html', registration_disabled=DISABLE_REGISTER, guest_disabled=DISABLE_GUEST, skip_auth=SKIP_AUTH)

@app.route('/register')
def register_page():
    # Redirect to app if already logged in
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('register.html', registration_disabled=DISABLE_REGISTER)

@app.route('/verify')
def verify_email():
    """Email verification endpoint"""
    token = request.args.get('token')

    if not token:
        return render_template('verification_result.html',
                             success=False,
                             message='Invalid verification link',
                             app_source='main')

    # Verify the token
    success, message, app_source, user_email = verify_token(token)

    # Send welcome email if successful
    if success and user_email:
        try:
            user = get_user_by_email(user_email)
            if user:
                send_welcome_email(user_email, user['username'], app_source or 'main')
        except Exception as e:
            print(f"Error sending welcome email: {e}")

    # Determine redirect URL based on app_source
    redirect_url = None
    if success:
        if app_source == 'workshop':
            redirect_url = os.getenv('WORKSHOP_APP_URL', 'https://workshop.librecrawl.com')
        else:
            redirect_url = url_for('login_page')

    return render_template('verification_result.html',
                         success=success,
                         message=message,
                         app_source=app_source or 'main',
                         redirect_url=redirect_url)

@app.route('/api/register', methods=['POST'])
def register():
    # Check if registration is disabled
    if DISABLE_REGISTER:
        return jsonify({'success': False, 'message': 'Registration is currently disabled'})

    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')

    success, message, user_id = create_user(username, email, password)

    # In local mode, auto-verify and set to admin tier
    if success and LOCAL_MODE:
        try:
            from src.auth_db import verify_user, set_user_tier
            # Get the user that was just created
            import sqlite3
            conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'users.db'))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()
            conn.close()

            if user:
                verify_user(user['id'])
                set_user_tier(user['id'], 'admin')
                message = 'Account created and verified! You have admin access in local mode.'
        except Exception as e:
            print(f"Error during local mode auto-verification: {e}")
            # Don't fail the registration, just log the error
            # The account is still created successfully

    elif success:
        # Not in local mode - send verification email
        is_resend = (message == 'resend')
        try:
            # Create verification token
            token = create_verification_token(user_id, app_source='main')
            if token:
                # Send verification email
                email_success, email_message = send_verification_email(
                    email, username, token, app_source='main', is_resend=is_resend
                )
                if email_success:
                    if is_resend:
                        message = 'A verification email was already sent to this address. We\'ve updated your account details and sent a new verification link.'
                    else:
                        message = 'Registration successful! Please check your email to verify your account.'
                else:
                    message = 'Account created, but we could not send the verification email. Please contact support.'
                    print(f"Email error: {email_message}")
            else:
                message = 'Account created, but verification token generation failed. Please contact support.'
        except Exception as e:
            print(f"Error sending verification email: {e}")
            message = 'Account created, but we could not send the verification email. Please contact support.'

    return jsonify({'success': success, 'message': message})

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def admin_users():
    return jsonify({'success': True, 'users': get_all_users()})

@app.route('/api/admin/users', methods=['POST'])
@admin_required
def admin_create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''
    tier = data.get('tier') or 'user'
    if tier not in ('user', 'extra', 'admin'):
        return jsonify({'success': False, 'error': 'Invalid account role'}), 400
    success, message, user_id = create_user(username, email, password)
    if not success:
        return jsonify({'success': False, 'error': message}), 400
    verify_user(user_id)
    set_user_tier(user_id, tier)
    return jsonify({'success': True, 'message': 'User created and verified', 'user_id': user_id}), 201

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''

    # Dangerously skip auth: accept any username with no password.
    # Username is only used to separate per-user sessions.
    if SKIP_AUTH:
        if not username:
            return jsonify({'success': False, 'message': 'Username required'})
        if len(username) > 50:
            return jsonify({'success': False, 'message': 'Username must be 50 characters or less'})
        success, message = skip_auth_login(username)
        return jsonify({'success': success, 'message': message})

    success, message, user_data = authenticate_user(username, password)

    if success:
        session['user_id'] = user_data['id']
        session['username'] = user_data['username']
        # In local mode, always give admin tier
        session['tier'] = 'admin' if LOCAL_MODE else user_data['tier']
        session.permanent = True  # Remember login

    return jsonify({'success': success, 'message': message})

@app.route('/api/guest-login', methods=['POST'])
def guest_login():
    """Login as a guest user (no account required, limited to 3 crawls/24h)"""
    if DISABLE_GUEST:
        return jsonify({'success': False, 'message': 'Guest login is disabled'})

    # Create a guest session with no user_id but with tier='guest'
    # In local mode, guests also get admin tier
    session['user_id'] = None
    session['username'] = 'Guest'
    session['tier'] = 'admin' if LOCAL_MODE else 'guest'
    session.permanent = False  # Don't persist guest sessions

    return jsonify({'success': True, 'message': 'Logged in as guest'})

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out successfully'})

@app.route('/api/user/info')
@login_required
def user_info():
    """Get current user info including tier"""
    from src.auth_db import get_crawls_last_24h
    user_id = session.get('user_id')
    tier = session.get('tier', 'guest')
    username = session.get('username')

    # Get crawl count
    crawls_today = 0
    if tier == 'guest':
        # For guests, count from IP address
        client_ip = get_client_ip()
        crawls_today = get_guest_crawls_last_24h(client_ip)
    else:
        # For registered users, count from database
        crawls_today = get_crawls_last_24h(user_id)

    return jsonify({
        'success': True,
        'user': {
            'id': user_id,
            'username': username,
            'tier': tier,
            'crawls_today': crawls_today,
            'crawls_remaining': max(0, 3 - crawls_today) if tier == 'guest' else -1
        }
    })

@app.route('/')
def index():
    # In local mode, auto-login if not already logged in
    if LOCAL_MODE and 'user_id' not in session:
        auto_login_local_mode()
    elif 'user_id' not in session:
        # Not in local mode and not logged in, redirect to login
        return redirect(url_for('login_page'))
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    """Crawl history dashboard"""
    return render_template('dashboard.html')

@app.route('/debug/memory')
@login_required
def debug_memory_page():
    """Debug page with nice UI for memory monitoring"""
    return render_template('debug_memory.html')

@app.route('/api/start_crawl', methods=['POST'])
@login_required
def start_crawl():
    from src.auth_db import get_crawls_last_24h, log_crawl_start

    data = request.get_json()
    url = data.get('url')
    crawl_mode = data.get('crawl_mode', 'spider')
    seed_urls = data.get('seed_urls')

    if not url:
        return jsonify({'success': False, 'error': 'URL is required'})
    if crawl_mode not in ('spider', 'list', 'sitemap'):
        return jsonify({'success': False, 'error': 'Invalid crawl mode'})
    if crawl_mode in ('list', 'sitemap') and not seed_urls:
        return jsonify({'success': False, 'error': 'seed_urls is required for list and sitemap modes'})
    if crawl_mode == 'list' and not isinstance(seed_urls, list):
        return jsonify({'success': False, 'error': 'seed_urls must be an array for list mode'})
    if crawl_mode == 'sitemap' and not isinstance(seed_urls, list):
        return jsonify({'success': False, 'error': 'seed_urls must contain one sitemap URL'})

    user_id = session.get('user_id')
    session_id = session.get('session_id')
    tier = session.get('tier', 'guest')

    # Check guest limits (IP-based) - skip in local mode
    if tier == 'guest' and not LOCAL_MODE:
        client_ip = get_client_ip()
        crawls_from_ip = get_guest_crawls_last_24h(client_ip)

        if crawls_from_ip >= 3:
            return jsonify({
                'success': False,
                'error': 'Guest limit reached: 3 crawls per 24 hours from your IP address. Please register for unlimited crawls.'
            })

        # Log this guest crawl
        log_guest_crawl(client_ip)

    # Get or create crawler for this session
    crawler = get_or_create_crawler()
    settings_manager = get_session_settings()

    # Apply current settings to crawler before starting
    try:
        crawler_config = settings_manager.get_crawler_config()
        crawler.update_config(crawler_config)
    except Exception as e:
        print(f"Warning: Could not apply settings: {e}")

    # Enforce demo mode limits
    if DEMO_MODE:
        crawler.config['demo_mode'] = True
        crawler.config['demo_memory_limit_bytes'] = int(1.5 * 1024 * 1024 * 1024)  # 1.5GB

    # Pass user_id and session_id for database persistence
    success, message = crawler.start_crawl(
        url, user_id=user_id, session_id=session_id,
        crawl_mode=crawl_mode, seed_urls=seed_urls
    )

    # Store crawl_id in session
    if success and crawler.crawl_id:
        session['current_crawl_id'] = crawler.crawl_id
        # Also log to old crawl_history for compatibility
        log_crawl_start(user_id, url)

    return jsonify({'success': success, 'message': message, 'crawl_id': crawler.crawl_id})

@app.route('/api/stop_crawl', methods=['POST'])
@login_required
def stop_crawl():
    crawler = get_or_create_crawler()
    success, message = crawler.stop_crawl()
    return jsonify({'success': success, 'message': message})

@app.route('/api/analysis/orphans')
@login_required
def analysis_orphans():
    crawler = get_or_create_crawler()
    from src.core.advanced_analysis import orphan_pages
    status = crawler.get_status()
    return jsonify({'success': True, 'orphans': orphan_pages(status.get('urls', []), status.get('links', []))})


@app.route('/api/analysis/search', methods=['POST'])
@login_required
def analysis_search():
    data = request.get_json() or {}
    query = data.get('query', '').strip()
    if not query:
        return jsonify({'success': False, 'error': 'query is required'}), 400
    crawler = get_or_create_crawler()
    from src.core.advanced_analysis import semantic_search
    return jsonify({'success': True, 'query': query, 'results': semantic_search(crawler.get_status().get('urls', []), query, data.get('limit', 20))})

@app.route('/api/analysis/embeddings', methods=['POST'])
@login_required
def analysis_embeddings():
    data = request.get_json() or {}
    if not data.get('query'):
        return jsonify({'success': False, 'error': 'query is required'}), 400
    crawler = get_or_create_crawler()
    from src.core.advanced_analysis import embedding_search
    try:
        result = embedding_search(crawler.get_status().get('urls', []), data['query'], data.get('api_key', ''), data.get('endpoint', 'https://api.openai.com/v1/embeddings'), data.get('model', 'text-embedding-3-small'), data.get('limit', 20))
        return jsonify(result), (200 if result.get('success') else 400)
    except Exception as error:
        return jsonify({'success': False, 'error': str(error)}), 502


@app.route('/api/ai/analyze', methods=['POST'])
@login_required
def ai_analyze():
    data = request.get_json() or {}
    if not data.get('prompt'):
        return jsonify({'success': False, 'error': 'prompt is required'}), 400
    crawler = get_or_create_crawler()
    status = crawler.get_status()
    context = json.dumps({'urls': status.get('urls', []), 'issues': status.get('issues', [])}, ensure_ascii=False, default=str)
    from src.core.ai_integration import analyze
    try:
        result = analyze(data['prompt'], context, data.get('endpoint', 'https://api.openai.com/v1/chat/completions'), data.get('api_key', ''), data.get('model', 'gpt-4o-mini'))
        return jsonify(result), (200 if result.get('success') else 400)
    except Exception as error:
        return jsonify({'success': False, 'error': str(error)}), 502


@app.route('/api/analysis/changes', methods=['POST'])
@login_required
def analysis_changes():
    data = request.get_json() or {}
    old_id, new_id = data.get('old_crawl_id'), data.get('new_crawl_id')
    if not old_id or not new_id:
        return jsonify({'success': False, 'error': 'old_crawl_id and new_crawl_id are required'}), 400
    from src.crawl_db import get_crawl_by_id, load_crawled_urls
    old_crawl, new_crawl = get_crawl_by_id(old_id), get_crawl_by_id(new_id)
    if not old_crawl or not new_crawl:
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    user_id = session.get('user_id')
    if user_id and (old_crawl.get('user_id') != user_id or new_crawl.get('user_id') != user_id):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    from src.core.advanced_analysis import detect_changes
    changes = detect_changes(load_crawled_urls(old_id), load_crawled_urls(new_id))
    return jsonify({'success': True, 'changes': changes, 'count': len(changes)})


@app.route('/api/seo/robots-test', methods=['POST'])
@login_required
def seo_robots_test():
    data = request.get_json() or {}
    if not data.get('url'):
        return jsonify({'success': False, 'error': 'url is required'}), 400
    from src.core.seo_utilities import test_robots, fetch_and_test_robots
    try:
        if data.get('robots_text'):
            result = test_robots(data['robots_text'], data['url'], data.get('user_agent', '*'))
        else:
            result = fetch_and_test_robots(data['url'], data.get('target_url'), data.get('user_agent', '*'))
        return jsonify({'success': True, 'result': result})
    except Exception as error:
        return jsonify({'success': False, 'error': str(error)}), 502


@app.route('/api/seo/sitemap', methods=['POST'])
@login_required
def seo_sitemap():
    data = request.get_json() or {}
    from src.core.seo_utilities import generate_sitemap, generate_sitemap_index
    if data.get('sitemaps'):
        return Response(generate_sitemap_index(data['sitemaps']), mimetype='application/xml')
    return Response(generate_sitemap(data.get('urls', []), data.get('base_url')), mimetype='application/xml')


@app.route('/api/analysis/segment', methods=['POST'])
@login_required
def analysis_segment():
    data = request.get_json() or {}
    from src.core.seo_utilities import segment_urls
    crawler = get_or_create_crawler()
    return jsonify({'success': True, 'urls': segment_urls(crawler.get_status().get('urls', []), data.get('expression', ''))})

@app.route('/api/seo/rewrite', methods=['POST'])
@login_required
def seo_rewrite():
    data = request.get_json() or {}
    from src.core.seo_utilities import rewrite_url
    return jsonify({'success': True, 'url': rewrite_url(data.get('url', ''), data.get('rules', []))})

@app.route('/api/seo/cdn-rewrite', methods=['POST'])
@login_required
def seo_cdn_rewrite():
    data = request.get_json() or {}
    from src.core.seo_utilities import apply_cdn
    return jsonify({'success': True, 'urls': [apply_cdn(url, data.get('cdn_host', '')) for url in data.get('urls', [])]})


@app.route('/api/analysis/link-metrics')
@login_required
def analysis_link_metrics():
    crawler = get_or_create_crawler()
    from src.core.link_metrics import calculate_link_metrics
    status = crawler.get_status()
    return jsonify({'success': True, 'metrics': calculate_link_metrics(status.get('urls', []), status.get('links', []))})

@app.route('/api/analysis/http-audit')
@login_required
def analysis_http_audit():
    """Summarize response headers, cookies, HSTS and validation findings."""
    crawler = get_or_create_crawler(); urls = crawler.get_status().get('urls', [])
    summary = {'urls': len(urls), 'header_names': {}, 'cookies': 0, 'hsts_missing': 0,
               'validation_errors': 0, 'javascript_errors': 0}
    for row in urls:
        for name in (row.get('http_headers') or {}):
            key = str(name).lower(); summary['header_names'][key] = summary['header_names'].get(key, 0) + 1
        summary['cookies'] += len(row.get('cookies') or [])
        if row.get('security') and not row['security'].get('hsts'):
            summary['hsts_missing'] += 1
        summary['validation_errors'] += len((row.get('html_validation') or {}).get('errors', []))
        summary['javascript_errors'] += len(row.get('javascript_errors') or [])
    return jsonify({'success': True, 'audit': summary})


@app.route('/api/analysis/summary')
@login_required
def analysis_summary():
    from collections import Counter
    from src.core.advanced_analysis import orphan_pages
    from src.core.link_metrics import calculate_link_metrics
    crawler = get_or_create_crawler(); status = crawler.get_status()
    urls, links, issues = status.get('urls', []), status.get('links', []), status.get('issues', [])
    metrics = calculate_link_metrics(urls, links)
    response_times = [row.get('response_time', 0) for row in urls if row.get('response_time') is not None]
    return jsonify({'success': True, 'summary': {
        'urls': len(urls), 'links': len(links), 'orphans': len(orphan_pages(urls, links)),
        'duplicate_groups': len(status.get('duplicate_groups', [])), 'issues': len(issues),
        'status_codes': dict(Counter(str(row.get('status_code', 0)) for row in urls)),
        'resource_count': sum(len(row.get('resources', []) or []) for row in urls),
        'average_response_ms': round(sum(response_times) / len(response_times), 2) if response_times else 0,
        'top_link_score': metrics[0] if metrics else None,
    }})


@app.route('/api/reports/email', methods=['POST'])
@login_required
def email_report():
    data = request.get_json() or {}
    if not data.get('to') or not data.get('crawl_id'):
        return jsonify({'success': False, 'error': 'to and crawl_id are required'}), 400
    from src.crawl_db import get_crawl_by_id, load_crawled_urls, load_crawl_links, load_crawl_issues
    crawl = get_crawl_by_id(data['crawl_id'])
    if not crawl:
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    if session.get('user_id') and crawl.get('user_id') != session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    report_urls = load_crawled_urls(data['crawl_id'])
    report_links = load_crawl_links(data['crawl_id'])
    report_issues = load_crawl_issues(data['crawl_id'])
    report_format = str(data.get('format', 'json')).lower()
    if report_format == 'csv':
        report_text = generate_csv_export(report_urls, data.get('fields', ['url', 'status_code', 'title', 'meta_description']))
        attachment_name = data.get('attachment_name', 'crawl-report.csv')
    else:
        report_text = json.dumps({'crawl': crawl, 'urls': report_urls, 'links': report_links, 'issues': report_issues}, ensure_ascii=False, default=str)
        attachment_name = data.get('attachment_name', 'crawl-report.json')
    from src.email_service import send_report_email
    sent, message = send_report_email(data['to'], data.get('subject', 'Deep Crawling crawl report'), report_text, attachment_name)
    return jsonify({'success': sent, 'message': message}), (200 if sent else 503)

@app.route('/api/team/crawls/<int:crawl_id>/share', methods=['POST'])
@login_required
def create_crawl_share_api(crawl_id):
    from src.crawl_db import get_crawl_by_id, create_crawl_share
    crawl = get_crawl_by_id(crawl_id)
    if not crawl:
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    if session.get('user_id') and crawl.get('user_id') != session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    expires_at = None
    if data := (request.get_json(silent=True) or {}):
        hours = data.get('expires_in_hours')
        if hours:
            from datetime import datetime, timedelta
            expires_at = (datetime.utcnow() + timedelta(hours=float(hours))).strftime('%Y-%m-%d %H:%M:%S')
    token = create_crawl_share(crawl_id, session.get('user_id'), expires_at)
    return jsonify({'success': bool(token), 'share_token': token, 'url': f'/api/team/shared/{token}'}), (201 if token else 500)

@app.route('/api/team/shared/<token>', methods=['DELETE'])
@login_required
def revoke_crawl_share_api(token):
    from src.crawl_db import revoke_crawl_share
    revoked = revoke_crawl_share(token, session.get('user_id'))
    return jsonify({'success': revoked}), (200 if revoked else 404)

@app.route('/api/team/shared/<token>')
def shared_crawl(token):
    from src.crawl_db import get_crawl_share, get_crawl_by_id, load_crawled_urls, load_crawl_links, load_crawl_issues
    share = get_crawl_share(token)
    if not share:
        return jsonify({'success': False, 'error': 'share not found or expired'}), 404
    return jsonify({'success': True, 'crawl': get_crawl_by_id(share['crawl_id']),
                    'urls': load_crawled_urls(share['crawl_id']),
                    'links': load_crawl_links(share['crawl_id']),
                    'issues': load_crawl_issues(share['crawl_id'])})

@app.route('/api/mcp', methods=['POST'])
@login_required
def mcp_endpoint():
    """Small MCP-compatible JSON-RPC bridge for local crawl inspection."""
    request_data = request.get_json(silent=True) or {}
    method = request_data.get('method')
    request_id = request_data.get('id')
    if method == 'initialize':
        result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}, 'resources': {}}, 'serverInfo': {'name': 'Deep Crawling', 'version': '1.0'}}
    elif method == 'resources/list':
        result = {'resources': [{'uri': 'librecrawl://crawl/current', 'name': 'Current crawl', 'mimeType': 'application/json'}]}
    elif method == 'resources/read':
        uri = (request_data.get('params') or {}).get('uri')
        if uri != 'librecrawl://crawl/current':
            return jsonify({'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32002, 'message': 'Resource not found'}}), 404
        result = {'contents': [{'uri': uri, 'mimeType': 'application/json', 'text': json.dumps(get_or_create_crawler().get_status(), default=str)}]}
    elif method == 'tools/list':
        result = {'tools': [
            {'name': 'crawl_status', 'description': 'Return current Deep Crawling crawl status', 'inputSchema': {'type': 'object'}},
            {'name': 'crawl_summary', 'description': 'Return current crawl summary', 'inputSchema': {'type': 'object'}},
            {'name': 'crawl_search', 'description': 'Search current crawl content', 'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']}},
            {'name': 'crawl_report', 'description': 'Return a saved crawl report', 'inputSchema': {'type': 'object', 'properties': {'crawl_id': {'type': 'integer'}}, 'required': ['crawl_id']}},
            {'name': 'seo_tool_catalog', 'description': 'List professional native SEO tools', 'inputSchema': {'type': 'object'}},
            {'name': 'seo_capability_audit', 'description': 'Audit enterprise SEO capability coverage and execution modes', 'inputSchema': {'type': 'object'}}
        ]}
    elif method == 'tools/call':
        name = (request_data.get('params') or {}).get('name')
        if name == 'crawl_status':
            result = {'content': [{'type': 'text', 'text': json.dumps(get_or_create_crawler().get_status(), default=str)}]}
        elif name == 'crawl_summary':
            result = {'content': [{'type': 'text', 'text': json.dumps(analysis_summary().get_json(), default=str)}]}
        elif name == 'crawl_search':
            args = (request_data.get('params') or {}).get('arguments') or {}
            # Use MCP arguments directly instead of invoking the HTTP wrapper.
            from src.core.advanced_analysis import semantic_search
            status = get_or_create_crawler().get_status()
            result = {'content': [{'type': 'text', 'text': json.dumps(semantic_search(status.get('urls', []), args.get('query', ''), args.get('limit', 20)), default=str)}]}
        elif name == 'crawl_report':
            args = (request_data.get('params') or {}).get('arguments') or {}
            report_response = crawl_report(int(args.get('crawl_id', 0)))
            result = {'content': [{'type': 'text', 'text': json.dumps(report_response.get_json(), default=str)}]}
        elif name == 'seo_tool_catalog':
            from src.professional_tools import SEO_TOOL_CATALOG
            result = {'content': [{'type': 'text', 'text': json.dumps({'tools':SEO_TOOL_CATALOG}, default=str)}]}
        elif name == 'seo_capability_audit':
            from src.professional_tools import capability_audit
            result = {'content': [{'type': 'text', 'text': json.dumps(capability_audit(), default=str)}]}
        else:
            return jsonify({'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32601, 'message': 'Unknown tool'}}), 400
    else:
        return jsonify({'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32601, 'message': 'Unsupported MCP method'}}), 400
    return jsonify({'jsonrpc': '2.0', 'id': request_id, 'result': result})


@app.route('/api/crawl_status')
@login_required
def crawl_status():
    crawler = get_or_create_crawler()
    settings_manager = get_session_settings()

    # Check for incremental update parameters
    url_since = request.args.get('url_since', type=int)
    link_since = request.args.get('link_since', type=int)
    issue_since = request.args.get('issue_since', type=int)

    # Get full status data
    status_data = crawler.get_status()

    # Ensure baseUrl is in stats (needed for UI to work correctly)
    if crawler.base_url and 'stats' in status_data:
        status_data['stats']['baseUrl'] = crawler.base_url

    # Check if we need to force a full refresh (after loading from DB)
    force_full = session.pop('force_full_refresh', False)

    # If incremental parameters provided AND not forcing full refresh, slice the arrays
    if not force_full:
        if url_since is not None:
            status_data['urls'] = status_data.get('urls', [])[url_since:]
        if link_since is not None:
            status_data['links'] = status_data.get('links', [])[link_since:]
        if issue_since is not None:
            status_data['issues'] = status_data.get('issues', [])[issue_since:]

    # Apply current issue exclusion patterns to displayed issues
    issues = status_data.get('issues', [])
    if issues:
        current_settings = settings_manager.get_settings()
        exclusion_patterns_text = current_settings.get('issueExclusionPatterns', '')
        exclusion_patterns = [p.strip() for p in exclusion_patterns_text.split('\n') if p.strip()]
        filtered_issues = filter_issues_by_exclusion_patterns(issues, exclusion_patterns)
        status_data['issues'] = filtered_issues

    return jsonify(status_data)

@app.route('/api/visualization_data')
@login_required
def visualization_data():
    """Get graph data for site structure visualization"""
    try:
        crawler = get_or_create_crawler()
        status_data = crawler.get_status()

        # Get URLs from the status data
        crawled_pages = status_data.get('urls', [])
        all_links = status_data.get('links', [])

        # Build nodes and edges for the graph
        nodes = []
        edges = []
        url_to_id = {}

        # Create nodes from crawled pages (limit to prevent lag)
        max_nodes = 500  # Optimization: limit nodes for performance
        pages_to_visualize = crawled_pages[:max_nodes]

        for idx, page in enumerate(pages_to_visualize):
            url = page.get('url', '')
            status_code = page.get('status_code', 0)

            # Assign color based on status code
            if 200 <= status_code < 300:
                color = '#10b981'  # Green for 2xx
            elif 300 <= status_code < 400:
                color = '#3b82f6'  # Blue for 3xx
            elif 400 <= status_code < 500:
                color = '#f59e0b'  # Orange for 4xx
            elif 500 <= status_code < 600:
                color = '#ef4444'  # Red for 5xx
            else:
                color = '#6b7280'  # Gray for other

            # Create node
            node = {
                'data': {
                    'id': f'node-{idx}',
                    'label': url.split('/')[-1] or url.split('//')[-1],  # Use last path segment or domain
                    'url': url,
                    'status_code': status_code,
                    'title': page.get('title', ''),
                    'color': color,
                    'size': 30 if idx == 0 else 20,  # Make root node larger
                    'depth': page.get('depth', 0)
                }
            }
            nodes.append(node)
            url_to_id[url] = f'node-{idx}'

        # Create edges from links data
        # Links are stored as: {'source_url': url, 'target_url': url, 'is_internal': bool, ...}
        edges_set = set()  # Use set to avoid duplicate edges
        for link in all_links:
            if link.get('is_internal'):  # Only use internal links
                source_url = link.get('source_url', '')
                target_url = link.get('target_url', '')

                source_id = url_to_id.get(source_url)
                target_id = url_to_id.get(target_url)

                if source_id and target_id and source_id != target_id:
                    edge_key = f'{source_id}-{target_id}'
                    if edge_key not in edges_set:
                        edges_set.add(edge_key)
                        edge = {
                            'data': {
                                'id': f'edge-{edge_key}',
                                'source': source_id,
                                'target': target_id
                            }
                        }
                        edges.append(edge)

        return jsonify({
            'success': True,
            'nodes': nodes,
            'edges': edges,
            'total_pages': len(crawled_pages),
            'visualized_pages': len(nodes),
            'truncated': len(crawled_pages) > max_nodes
        })

    except Exception as e:
        print(f"Error generating visualization data: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e),
            'nodes': [],
            'edges': []
        })

@app.route('/api/crawls/<int:crawl_id>/visualization_data')
@login_required
def saved_visualization_data(crawl_id):
    """Build the same reproducible graph from a saved crawl."""
    from src.crawl_db import get_crawl_by_id, load_crawled_urls, load_crawl_links
    crawl = get_crawl_by_id(crawl_id)
    if not crawl:
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    if session.get('user_id') and crawl.get('user_id') != session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    pages = load_crawled_urls(crawl_id)
    links = load_crawl_links(crawl_id)
    max_nodes = max(1, min(int(request.args.get('limit', 500)), 5000))
    visible = pages[:max_nodes]
    ids = {row.get('url'): f'node-{index}' for index, row in enumerate(visible)}
    def color(status):
        status = int(status or 0)
        return '#10b981' if 200 <= status < 300 else '#3b82f6' if 300 <= status < 400 else '#f59e0b' if 400 <= status < 500 else '#ef4444' if 500 <= status < 600 else '#6b7280'
    nodes = [{'data': {'id': node_id, 'label': (row.get('url') or '').split('/')[-1] or row.get('url'),
                       'url': row.get('url'), 'status_code': row.get('status_code', 0), 'title': row.get('title', ''),
                       'depth': row.get('depth', 0), 'color': color(row.get('status_code')), 'size': 30 if index == 0 else 20}}
             for index, (row, node_id) in enumerate((row, ids.get(row.get('url'))) for row in visible) if node_id]
    seen = set(); edges = []
    for link in links:
        source, target = ids.get(link.get('source_url')), ids.get(link.get('target_url'))
        if source and target and source != target and (source, target) not in seen:
            seen.add((source, target)); edges.append({'data': {'id': f'edge-{source}-{target}', 'source': source, 'target': target}})
    return jsonify({'success': True, 'crawl_id': crawl_id, 'nodes': nodes, 'edges': edges,
                    'total_pages': len(pages), 'visualized_pages': len(nodes), 'truncated': len(pages) > max_nodes,
                    'saved': True})

@app.route('/api/debug/memory')
@login_required
def debug_memory():
    """Debug endpoint showing memory stats for all active crawler instances"""
    with instances_lock:
        memory_stats = {
            'total_instances': len(crawler_instances),
            'instances': []
        }

        for session_id, instance_data in crawler_instances.items():
            crawler = instance_data['crawler']
            stats = crawler.memory_monitor.get_stats()

            memory_stats['instances'].append({
                'session_id': session_id[:8] + '...',  # Truncate for privacy
                'last_accessed': instance_data['last_accessed'].isoformat(),
                'urls_crawled': len(crawler.crawl_results),
                'memory': stats,
                'data_sizes': crawler.user_memory.get_stats()
            })

        return jsonify(memory_stats)

@app.route('/api/debug/memory/profile')
@login_required
def debug_memory_profile():
    """Detailed memory profiling - what's actually using the RAM"""
    from src.core.memory_profiler import MemoryProfiler

    with instances_lock:
        profiles = []

        for session_id, instance_data in crawler_instances.items():
            crawler = instance_data['crawler']

            # Get object breakdown
            breakdown = MemoryProfiler.get_object_memory_breakdown()

            profiles.append({
                'session_id': session_id[:8] + '...',
                'urls_crawled': len(crawler.crawl_results),
                'object_breakdown': breakdown,
                'data_sizes': crawler.user_memory.get_stats()
            })

        return jsonify({
            'total_instances': len(crawler_instances),
            'profiles': profiles
        })

@app.route('/api/filter_issues', methods=['POST'])
@login_required
def filter_issues():
    try:
        data = request.get_json()
        issues = data.get('issues', [])
        settings_manager = get_session_settings()

        # Get current exclusion patterns
        current_settings = settings_manager.get_settings()
        exclusion_patterns_text = current_settings.get('issueExclusionPatterns', '')
        exclusion_patterns = [p.strip() for p in exclusion_patterns_text.split('\n') if p.strip()]

        # Filter issues
        filtered_issues = filter_issues_by_exclusion_patterns(issues, exclusion_patterns)

        return jsonify({'success': True, 'issues': filtered_issues})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/get_settings')
@login_required
def get_settings():
    try:
        settings_manager = get_session_settings()
        settings = settings_manager.get_settings()
        return jsonify({'success': True, 'settings': settings})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/save_settings', methods=['POST'])
@login_required
def save_settings():
    try:
        data = request.get_json()
        settings_manager = get_session_settings()
        success, message = settings_manager.save_settings(data)
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/reset_settings', methods=['POST'])
@login_required
def reset_settings():
    try:
        settings_manager = get_session_settings()
        success, message = settings_manager.reset_settings()
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/update_crawler_settings', methods=['POST'])
@login_required
def update_crawler_settings():
    try:
        crawler = get_or_create_crawler()
        settings_manager = get_session_settings()
        # Get current settings and update crawler configuration
        crawler_config = settings_manager.get_crawler_config()
        crawler.update_config(crawler_config)
        return jsonify({'success': True, 'message': 'Crawler settings updated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/pause_crawl', methods=['POST'])
@login_required
def pause_crawl():
    try:
        crawler = get_or_create_crawler()
        success, message = crawler.pause_crawl()
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/resume_crawl', methods=['POST'])
@login_required
def resume_crawl():
    try:
        crawler = get_or_create_crawler()
        success, message = crawler.resume_crawl()
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/crawls/list')
@login_required
def list_crawls():
    """Get all crawls for current user"""
    try:
        user_id = session.get('user_id')
        from src.crawl_db import get_user_crawls, get_crawl_count

        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        status_filter = request.args.get('status')

        crawls = get_user_crawls(user_id, limit=limit, offset=offset, status_filter=status_filter)
        total_count = get_crawl_count(user_id)

        return jsonify({
            'success': True,
            'crawls': crawls,
            'total': total_count
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/crawls/<int:crawl_id>')
@login_required
def get_crawl(crawl_id):
    """Get complete crawl data by ID"""
    try:
        user_id = session.get('user_id')
        from src.crawl_db import get_crawl_by_id, load_crawled_urls, load_crawl_links, load_crawl_issues

        # Get crawl metadata
        crawl = get_crawl_by_id(crawl_id)
        if not crawl:
            return jsonify({'success': False, 'error': 'Crawl not found'}), 404

        # Check ownership (guests have user_id = None)
        if user_id and crawl.get('user_id') != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403

        # Load all data
        urls = load_crawled_urls(crawl_id)
        links = load_crawl_links(crawl_id)
        issues = load_crawl_issues(crawl_id)

        return jsonify({
            'success': True,
            'crawl': crawl,
            'urls': urls,
            'links': links,
            'issues': issues
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/crawls/compare', methods=['GET'])
@login_required
def compare_crawls():
    """Compare two saved crawls and return URL-level SEO changes."""
    try:
        old_id = request.args.get('old', type=int)
        new_id = request.args.get('new', type=int)
        if not old_id or not new_id:
            return jsonify({'success': False, 'error': 'old and new crawl IDs are required'}), 400

        from src.crawl_db import get_crawl_by_id, load_crawled_urls, load_crawl_issues
        old_crawl, new_crawl = get_crawl_by_id(old_id), get_crawl_by_id(new_id)
        if not old_crawl or not new_crawl:
            return jsonify({'success': False, 'error': 'One or both crawls were not found'}), 404
        user_id = session.get('user_id')
        if user_id and (old_crawl.get('user_id') != user_id or new_crawl.get('user_id') != user_id):
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403

        import hashlib
        old_urls = {row['url']: row for row in load_crawled_urls(old_id)}
        new_urls = {row['url']: row for row in load_crawled_urls(new_id)}
        added, removed, changed = [], [], []
        fields = ('status_code', 'title', 'meta_description', 'h1', 'canonical_url',
                  'robots', 'word_count', 'response_time')
        for url in sorted(set(new_urls) - set(old_urls)):
            added.append({'url': url, 'new': new_urls[url]})
        for url in sorted(set(old_urls) - set(new_urls)):
            removed.append({'url': url, 'old': old_urls[url]})
        for url in sorted(set(old_urls) & set(new_urls)):
            diffs = {field: {'old': old_urls[url].get(field), 'new': new_urls[url].get(field)}
                     for field in fields if old_urls[url].get(field) != new_urls[url].get(field)}
            if diffs:
                changed.append({'url': url, 'changes': diffs})
            old_snapshot={key: str(old_urls[url].get(key) or '') for key in ('source_html','rendered_html','extracted_text')}
            new_snapshot={key: str(new_urls[url].get(key) or '') for key in ('source_html','rendered_html','extracted_text')}
            snapshot_diff={key:{'old_hash':hashlib.sha256(old_snapshot[key].encode()).hexdigest(),'new_hash':hashlib.sha256(new_snapshot[key].encode()).hexdigest(),'old_length':len(old_snapshot[key]),'new_length':len(new_snapshot[key])} for key in old_snapshot if old_snapshot[key] != new_snapshot[key]}
            if snapshot_diff:
                changed.append({'url':url,'snapshot_changes':snapshot_diff})

        old_issues = load_crawl_issues(old_id)
        new_issues = load_crawl_issues(new_id)
        issue_key = lambda issue: (issue.get('url'), issue.get('issue'), issue.get('details'))
        old_issue_keys, new_issue_keys = {issue_key(i) for i in old_issues}, {issue_key(i) for i in new_issues}
        report = {
            'success': True,
            'old_crawl': {'id': old_id, 'started_at': old_crawl.get('started_at'), 'status': old_crawl.get('status')},
            'new_crawl': {'id': new_id, 'started_at': new_crawl.get('started_at'), 'status': new_crawl.get('status')},
            'summary': {
                'old_urls': len(old_urls), 'new_urls': len(new_urls),
                'added': len(added), 'removed': len(removed), 'changed': len(changed),
                'old_issues': len(old_issues), 'new_issues': len(new_issues),
                'new_issues_found': len(new_issue_keys - old_issue_keys),
                'issues_resolved': len(old_issue_keys - new_issue_keys)
            },
            'added': added, 'removed': removed, 'changed': changed,
            'new_issues': [i for i in new_issues if issue_key(i) not in old_issue_keys],
            'resolved_issues': [i for i in old_issues if issue_key(i) not in new_issue_keys]
        }
        if request.args.get('format') == 'csv':
            import csv
            from io import StringIO
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(['url', 'change_type', 'field', 'old_value', 'new_value'])
            for item in added:
                writer.writerow([item['url'], 'added', '', '', 'URL added'])
            for item in removed:
                writer.writerow([item['url'], 'removed', '', 'URL removed', ''])
            for item in changed:
                for field, values in item['changes'].items():
                    writer.writerow([item['url'], 'changed', field, values['old'], values['new']])
            from flask import Response
            return Response(output.getvalue(), mimetype='text/csv', headers={
                'Content-Disposition': f'attachment; filename=crawl-comparison-{old_id}-{new_id}.csv'
            })
        return jsonify(report)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/crawls/<int:crawl_id>/report')
@login_required
def crawl_report(crawl_id):
    """Return a compact audit report derived from a saved crawl."""
    try:
        from collections import Counter
        from src.crawl_db import get_crawl_by_id, load_crawled_urls, load_crawl_links, load_crawl_issues
        crawl = get_crawl_by_id(crawl_id)
        if not crawl:
            return jsonify({'success': False, 'error': 'Crawl not found'}), 404
        user_id = session.get('user_id')
        if user_id and crawl.get('user_id') != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        urls = load_crawled_urls(crawl_id)
        links = load_crawl_links(crawl_id)
        issues = load_crawl_issues(crawl_id)
        status_counts = Counter(str(url.get('status_code', 0)) for url in urls)
        resource_counts = Counter()
        accessibility = Counter()
        for url in urls:
            for resource in url.get('resources', []) or []:
                resource_counts[resource.get('type', 'unknown')] += 1
            for finding in (url.get('accessibility', {}) or {}).get('findings', []):
                accessibility[finding.get('rule', 'unknown')] += finding.get('count', 1)
        issue_counts = Counter(issue.get('category', 'Unknown') for issue in issues)
        duplicate_urls = [url for url in urls if url.get('duplicate_group')]
        pdf_urls = [url for url in urls if str(url.get('content_type', '')).lower().find('pdf') >= 0 or url.get('pdf_pages') is not None]
        rendered_urls = [url for url in urls if url.get('javascript_rendered')]
        source_snapshots = sum(1 for url in urls if url.get('source_html'))
        rendered_snapshots = sum(1 for url in urls if url.get('rendered_html') or url.get('rendered_archive_path'))
        extracted_text_pages = sum(1 for url in urls if url.get('extracted_text') or (url.get('content_analysis') or {}).get('content_text'))
        hreflang_pages = sum(1 for url in urls if url.get('hreflang'))
        javascript_error_pages = sum(1 for url in urls if url.get('javascript_errors'))
        hsts_missing = sum(1 for url in urls if url.get('security') and not url['security'].get('hsts'))
        validation_errors = sum(len((url.get('html_validation') or {}).get('errors', [])) for url in urls)
        report = {
            'success': True,
            'crawl': crawl,
            'summary': {
                'urls': len(urls), 'links': len(links), 'issues': len(issues),
                'status_codes': dict(status_counts),
                'issue_categories': dict(issue_counts),
                'resource_types': dict(resource_counts),
                'duplicate_urls': len(duplicate_urls),
                'accessibility_findings': dict(accessibility),
                'pdf_urls': len(pdf_urls),
                'rendered_urls': len(rendered_urls),
                'source_snapshots': source_snapshots,
                'rendered_snapshots': rendered_snapshots,
                'extracted_text_pages': extracted_text_pages,
                'hreflang_pages': hreflang_pages,
                'javascript_error_pages': javascript_error_pages,
                'hsts_missing': hsts_missing,
                'html_validation_errors': validation_errors,
            },
            'urls': urls,
            'links': links,
            'issues': issues,
            'pagespeed': crawl.get('pagespeed_results', []),
        }
        report['tab_counts'] = {
            'internal': sum(1 for row in urls if not row.get('is_external', False)),
            'external': sum(1 for row in urls if row.get('is_external', False)),
            'response_codes': dict(status_counts),
            'page_titles': sum(1 for row in urls if row.get('title')),
            'meta_descriptions': sum(1 for row in urls if row.get('meta_description')),
            'headings': sum(1 for row in urls if row.get('h1') or row.get('h2')),
            'images': sum(1 for row in urls if row.get('images')),
            'canonicals': sum(1 for row in urls if row.get('canonical_url')),
            'hreflang': sum(1 for row in urls if row.get('hreflang')),
            'javascript': sum(1 for row in urls if row.get('javascript_errors') or row.get('render_diagnostics')),
            'structured_data': sum(1 for row in urls if row.get('structured_data') or row.get('json_ld')),
            'accessibility': sum(1 for row in urls if row.get('accessibility')),
            'validation': sum(1 for row in urls if row.get('html_validation')),
            'resources': sum(len(row.get('resources') or []) for row in urls),
        }
        if request.args.get('format', '').lower() == 'csv':
            import csv
            from io import StringIO
            output = StringIO(); writer = csv.writer(output)
            writer.writerow(['metric', 'value'])
            for key, value in report['summary'].items():
                if isinstance(value, dict):
                    for subkey, subvalue in value.items(): writer.writerow([f'{key}.{subkey}', subvalue])
                else: writer.writerow([key, value])
            for key, value in report['tab_counts'].items():
                writer.writerow([f'tab.{key}', value if not isinstance(value, dict) else json.dumps(value, sort_keys=True)])
            return Response(output.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename=crawl-report-{crawl_id}.csv'})
        return jsonify(report)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/crawls/<int:crawl_id>/export')
@login_required
def historical_crawl_export(crawl_id):
    from src.crawl_db import get_crawl_by_id, load_crawled_urls, load_crawl_links, load_crawl_issues
    crawl = get_crawl_by_id(crawl_id)
    if not crawl:
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    if session.get('user_id') and crawl.get('user_id') != session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    urls = load_crawled_urls(crawl_id)
    dataset = request.args.get('dataset', 'urls').lower()
    if dataset == 'links':
        urls = load_crawl_links(crawl_id)
    elif dataset == 'issues':
        urls = load_crawl_issues(crawl_id)
    elif dataset == 'resources':
        urls = [{'url': row.get('url'), **resource} for row in urls for resource in (row.get('resources') or [])]
    elif dataset == 'headers':
        urls = [{'url': row.get('url'), **(row.get('http_headers') or {})} for row in urls]
    elif dataset == 'cookies':
        urls = [{'url': row.get('url'), **cookie} for row in urls for cookie in (row.get('cookies') or [])]
    elif dataset == 'rendering':
        urls = [{'url': row.get('url'), 'screenshot_path': row.get('screenshot_path'), 'rendered_archive_path': row.get('rendered_archive_path'), 'javascript_errors': row.get('javascript_errors'), 'render_diagnostics': row.get('render_diagnostics')} for row in urls]
    elif dataset in {'internal', 'external', 'response-codes', 'page-titles', 'meta-description', 'headings',
                     'images', 'canonicals', 'pagination', 'directives', 'hreflang', 'javascript', 'amp',
                     'structured-data', 'sitemaps', 'mobile', 'accessibility', 'validation', 'analytics',
                     'search-console', 'link-metrics', 'ai', 'changes'}:
        predicates = {
            'internal': lambda row: not row.get('is_external', False),
            'external': lambda row: bool(row.get('is_external', False)),
            'response-codes': lambda row: True,
            'page-titles': lambda row: bool(row.get('title')), 'meta-description': lambda row: bool(row.get('meta_description')),
            'headings': lambda row: bool(row.get('h1') or row.get('h2')), 'images': lambda row: bool(row.get('images')),
            'canonicals': lambda row: bool(row.get('canonical_url')), 'pagination': lambda row: bool(row.get('pagination')),
            'directives': lambda row: bool(row.get('robots')), 'hreflang': lambda row: bool(row.get('hreflang')),
            'javascript': lambda row: bool(row.get('javascript_errors') or row.get('render_diagnostics')),
            'amp': lambda row: bool(row.get('amp_url')), 'structured-data': lambda row: bool(row.get('structured_data') or row.get('json_ld')),
            'sitemaps': lambda row: bool(row.get('sitemap')), 'mobile': lambda row: bool(row.get('mobile_alternate')),
            'accessibility': lambda row: bool(row.get('accessibility')), 'validation': lambda row: bool(row.get('html_validation')),
            'analytics': lambda row: bool(row.get('analytics')), 'search-console': lambda row: bool(row.get('search_console')),
            'link-metrics': lambda row: bool(row.get('link_metrics')), 'ai': lambda row: bool(row.get('ai')),
            'changes': lambda row: bool(row.get('change_detection')),
        }
        urls = [row for row in urls if predicates[dataset](row)]
    elif dataset != 'urls':
        return jsonify({'success': False, 'error': 'unsupported dataset'}), 400
    export_format = request.args.get('format', 'json').lower()
    fields = request.args.getlist('field')
    if not fields:
        fields = sorted({key for row in urls for key in row.keys()}) if dataset != 'urls' else ['url', 'status_code', 'title', 'meta_description', 'h1', 'word_count', 'content_type']
    if export_format == 'csv':
        content = generate_csv_export(urls, fields); mimetype = 'text/csv'; extension = 'csv'
    elif export_format == 'json':
        content = generate_json_export(urls, fields); mimetype = 'application/json'; extension = 'json'
    else:
        return jsonify({'success': False, 'error': 'format must be json or csv'}), 400
    response = Response(content, mimetype=mimetype)
    response.headers['Content-Disposition'] = f'attachment; filename="librecrawl-crawl-{crawl_id}.{extension}"'
    return response

@app.route('/api/crawls/<int:crawl_id>/panels', methods=['GET'])
@login_required
def historical_url_panels(crawl_id):
    from src.crawl_db import get_crawl_by_id, load_crawled_urls
    crawl = get_crawl_by_id(crawl_id)
    if not crawl:
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    if session.get('user_id') and crawl.get('user_id') != session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    target = request.args.get('url')
    rows = load_crawled_urls(crawl_id)
    if target:
        rows = [row for row in rows if row.get('url') == target]
    if not rows:
        return jsonify({'success': False, 'error': 'URL not found in crawl'}), 404
    from src.parity_tools import page_panels
    panels = [page_panels(row) for row in rows]
    panel_name = (request.args.get('panel') or '').lower().replace('-', '_')
    supported_panels = {'url_details', 'inlinks', 'outlinks', 'resources', 'serp_snippet', 'http_headers',
                        'cookies', 'images', 'render_debug', 'structured_data', 'lighthouse',
                        'accessibility', 'spelling_grammar', 'duplicate_details', 'ngrams'}
    if panel_name:
        if panel_name not in supported_panels:
            return jsonify({'success': False, 'error': 'unsupported panel', 'supported': sorted(supported_panels)}), 400
        return jsonify({'success': True, 'crawl_id': crawl_id, 'panel': panel_name,
                        'rows': [{'url': item.get('url'), 'data': item.get(panel_name)} for item in panels]})
    return jsonify({'success': True, 'crawl_id': crawl_id, 'panels': panels, 'supported_panels': sorted(supported_panels)})

@app.route('/api/crawls/<int:crawl_id>/tabs/<tab_name>', methods=['GET'])
@login_required
def historical_spider_tab(crawl_id, tab_name):
    """Return a first-class Spider tab dataset instead of a table-only filter."""
    from src.crawl_db import get_crawl_by_id, load_crawled_urls
    crawl = get_crawl_by_id(crawl_id)
    if not crawl:
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    if session.get('user_id') and crawl.get('user_id') != session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    aliases = {'response-codes': 'response_codes', 'page-titles': 'page_titles',
               'meta-description': 'meta_descriptions', 'structured-data': 'structured_data',
               'search-console': 'search_console', 'link-metrics': 'link_metrics'}
    tab = aliases.get(tab_name.lower(), tab_name.lower().replace('-', '_'))
    supported = {'internal', 'external', 'security', 'response_codes', 'url', 'page_titles',
                 'meta_descriptions', 'headings', 'content', 'images', 'canonicals',
                 'pagination', 'directives', 'hreflang', 'javascript', 'amp',
                 'structured_data', 'sitemaps', 'mobile', 'accessibility', 'validation',
                 'analytics', 'search_console', 'link_metrics', 'ai', 'changes', 'resources'}
    if tab not in supported:
        return jsonify({'success': False, 'error': 'unsupported tab', 'supported': sorted(supported)}), 400
    rows = load_crawled_urls(crawl_id)
    def has(row, key):
        value = row.get(key)
        return bool(value) if isinstance(value, (list, dict, str)) else value is not None
    predicates = {
        'internal': lambda r: not r.get('is_external', False),
        'external': lambda r: bool(r.get('is_external', False)),
        'security': lambda r: bool(r.get('security') or r.get('security_headers') or int(r.get('status_code') or 0) >= 400),
        'response_codes': lambda r: True, 'url': lambda r: True,
        'page_titles': lambda r: has(r, 'title'), 'meta_descriptions': lambda r: has(r, 'meta_description'),
        'headings': lambda r: has(r, 'h1') or has(r, 'h2'), 'content': lambda r: has(r, 'extracted_text') or has(r, 'word_count'),
        'images': lambda r: has(r, 'images'), 'canonicals': lambda r: has(r, 'canonical_url'),
        'pagination': lambda r: has(r, 'pagination'), 'directives': lambda r: has(r, 'robots'),
        'hreflang': lambda r: has(r, 'hreflang'), 'javascript': lambda r: has(r, 'render_diagnostics') or has(r, 'javascript_errors'),
        'amp': lambda r: has(r, 'amp_url'), 'structured_data': lambda r: has(r, 'structured_data') or has(r, 'json_ld'),
        'sitemaps': lambda r: has(r, 'sitemap'), 'mobile': lambda r: has(r, 'mobile_alternate'),
        'accessibility': lambda r: has(r, 'accessibility'), 'validation': lambda r: has(r, 'html_validation'),
        'analytics': lambda r: has(r, 'analytics'), 'search_console': lambda r: has(r, 'search_console'),
        'link_metrics': lambda r: has(r, 'link_metrics'), 'ai': lambda r: has(r, 'ai'),
        'changes': lambda r: has(r, 'change_detection'), 'resources': lambda r: has(r, 'resources')}
    filtered = [row for row in rows if predicates[tab](row)]
    return jsonify({'success': True, 'crawl_id': crawl_id, 'tab': tab, 'count': len(filtered), 'rows': filtered,
                    'tabs': sorted(supported)})

@app.route('/api/crawls/<int:crawl_id>/custom-audit', methods=['POST'])
@login_required
def historical_custom_audit(crawl_id):
    from src.crawl_db import get_crawl_by_id, load_crawled_urls
    crawl = get_crawl_by_id(crawl_id)
    if not crawl:
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    if session.get('user_id') and crawl.get('user_id') != session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    data = request.get_json(silent=True) or {}
    from src.parity_tools import custom_extract, custom_search, link_positions, html_validation
    results = []
    for row in load_crawled_urls(crawl_id):
        result = {'url': row.get('url')}
        if data.get('rules') is not None: result['extractions'] = custom_extract(row, data.get('rules', []))['extractions']
        if data.get('searches') is not None: result['searches'] = custom_search(row, data.get('searches', []))['searches']
        if data.get('link_positions'): result['link_positions'] = link_positions(row)['links']
        if data.get('validate_html'): result['html_validation'] = html_validation(row)
        results.append(result)
    return jsonify({'success': True, 'crawl_id': crawl_id, 'count': len(results), 'rows': results})

@app.route('/api/rendered-file')
@login_required
def rendered_file():
    """Serve only locally generated screenshot/archive artifacts."""
    requested = request.args.get('path', '')
    project_root = os.path.dirname(os.path.abspath(__file__))
    data_root = os.path.realpath(os.path.join(project_root, 'data'))
    candidate = os.path.realpath(requested if os.path.isabs(requested) else os.path.join(project_root, requested))
    if not candidate.startswith(data_root + os.sep) or not os.path.isfile(candidate):
        return jsonify({'success': False, 'error': 'rendered file not found'}), 404
    return send_file(candidate)

@app.route('/api/crawls/<int:crawl_id>/analysis')
@login_required
def historical_crawl_analysis(crawl_id):
    """Run the same architecture analysis against a persisted crawl."""
    from src.crawl_db import get_crawl_by_id, load_crawled_urls, load_crawl_links
    from src.core.advanced_analysis import orphan_pages
    from src.core.link_metrics import calculate_link_metrics
    crawl = get_crawl_by_id(crawl_id)
    if not crawl:
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    if session.get('user_id') and crawl.get('user_id') != session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    urls, links = load_crawled_urls(crawl_id), load_crawl_links(crawl_id)
    metrics = calculate_link_metrics(urls, links)
    return jsonify({'success': True, 'crawl_id': crawl_id, 'summary': {
        'urls': len(urls), 'links': len(links), 'orphans': len(orphan_pages(urls, links)),
        'top_link_metrics': metrics[:100]
    }})

@app.route('/api/crawls/<int:crawl_id>/search', methods=['POST'])
@login_required
def historical_crawl_search(crawl_id):
    from src.crawl_db import get_crawl_by_id, load_crawled_urls
    from src.core.advanced_analysis import semantic_search
    crawl = get_crawl_by_id(crawl_id)
    if not crawl:
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    if session.get('user_id') and crawl.get('user_id') != session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    data = request.get_json() or {}
    return jsonify({'success': True, 'results': semantic_search(load_crawled_urls(crawl_id), data.get('query', ''), data.get('limit', 20))})

@app.route('/api/crawls/<int:crawl_id>/load', methods=['POST'])
@login_required
def load_crawl_into_session(crawl_id):
    """Load a historical crawl into the current session"""
    try:
        user_id = session.get('user_id')
        from src.crawl_db import get_crawl_by_id, load_crawled_urls, load_crawl_links, load_crawl_issues

        # Get crawl metadata
        crawl = get_crawl_by_id(crawl_id)
        if not crawl:
            return jsonify({'success': False, 'error': 'Crawl not found'}), 404

        # Check ownership
        if user_id and crawl.get('user_id') != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403

        # Get current crawler instance
        crawler = get_or_create_crawler()

        # Stop any running crawl
        if crawler.is_running:
            crawler.stop_crawl()

        # Load all data from database
        urls = load_crawled_urls(crawl_id)
        links = load_crawl_links(crawl_id)
        issues = load_crawl_issues(crawl_id)

        # Inject into current crawler instance
        with crawler.results_lock:
            crawler.crawl_results = urls
            crawler.stats['crawled'] = len(urls)
            crawler.stats['discovered'] = len(urls)
            crawler.base_url = crawl['base_url']
            crawler.base_domain = crawl['base_domain']

        # Load links into link manager
        if crawler.link_manager:
            crawler.link_manager.all_links = links
            # Rebuild links_set
            crawler.link_manager.links_set.clear()
            for link in links:
                link_key = f"{link['source_url']}|{link['target_url']}"
                crawler.link_manager.links_set.add(link_key)

        # Load issues into issue detector
        if crawler.issue_detector:
            crawler.issue_detector.detected_issues = issues

        # Rebuild per-user memory tracker for loaded data
        crawler.user_memory.reset()
        crawler._demo_limit_reached = False
        for url_data in urls:
            crawler.user_memory.track_url(url_data)
        if links:
            crawler.user_memory.track_links(links)
        if issues:
            crawler.user_memory.track_issues(issues)

        # Set Flask session flag for force full refresh
        session['force_full_refresh'] = True

        return jsonify({
            'success': True,
            'message': f'Loaded {len(urls)} URLs, {len(links)} links, {len(issues)} issues',
            'urls_count': len(urls),
            'links_count': len(links),
            'issues_count': len(issues),
            'should_refresh_ui': True
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/crawls/<int:crawl_id>/resume', methods=['POST'])
@login_required
def resume_crawl_endpoint(crawl_id):
    """Resume an interrupted crawl"""
    try:
        user_id = session.get('user_id')
        session_id = session.get('session_id')

        # Get crawler for this session
        crawler = get_or_create_crawler()

        # Enforce demo mode limits on resumed crawls
        if DEMO_MODE:
            crawler.config['demo_mode'] = True
            crawler.config['demo_memory_limit_bytes'] = int(1.5 * 1024 * 1024 * 1024)

        # Resume from database
        success, message = crawler.resume_from_database(crawl_id, user_id=user_id, session_id=session_id)

        if success:
            session['current_crawl_id'] = crawl_id

        return jsonify({'success': success, 'message': message})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/crawls/<int:crawl_id>/delete', methods=['DELETE'])
@login_required
def delete_crawl_endpoint(crawl_id):
    """Delete a crawl and all associated data"""
    try:
        user_id = session.get('user_id')
        from src.crawl_db import delete_crawl, get_crawl_by_id

        # Verify ownership
        crawl = get_crawl_by_id(crawl_id)
        if not crawl:
            return jsonify({'success': False, 'error': 'Crawl not found'}), 404

        if user_id and crawl.get('user_id') != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403

        success = delete_crawl(crawl_id)
        return jsonify({'success': success, 'message': 'Crawl deleted successfully' if success else 'Failed to delete crawl'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/crawls/<int:crawl_id>/archive', methods=['POST'])
@login_required
def archive_crawl(crawl_id):
    """Archive crawl (mark as archived but keep data)"""
    try:
        user_id = session.get('user_id')
        from src.crawl_db import set_crawl_status, get_crawl_by_id

        # Verify ownership
        crawl = get_crawl_by_id(crawl_id)
        if not crawl:
            return jsonify({'success': False, 'error': 'Crawl not found'}), 404

        if user_id and crawl.get('user_id') != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403

        success = set_crawl_status(crawl_id, 'archived')
        return jsonify({'success': success, 'message': 'Crawl archived successfully' if success else 'Failed to archive crawl'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/crawls/stats')
@login_required
def crawl_stats():
    """Get statistics about user's crawls"""
    try:
        user_id = session.get('user_id')
        from src.crawl_db import get_crawl_count, get_database_size_mb
        import sqlite3

        # Get counts by status
        conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'users.db'))
        cursor = conn.cursor()

        cursor.execute('''
            SELECT status, COUNT(*) as count
            FROM crawls
            WHERE user_id = ?
            GROUP BY status
        ''', (user_id,))

        status_counts = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        return jsonify({
            'success': True,
            'total_crawls': get_crawl_count(user_id),
            'by_status': status_counts,
            'database_size_mb': get_database_size_mb()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/integrations/search-console', methods=['POST'])
@login_required
def search_console_integration():
    """Query Google Search Console with a caller-provided OAuth token."""
    try:
        data = request.get_json() or {}
        required = ('site_url', 'access_token', 'start_date', 'end_date')
        missing = [key for key in required if not data.get(key)]
        if missing:
            return jsonify({'success': False, 'error': f"Missing fields: {', '.join(missing)}"}), 400
        from src.integrations import search_console
        result = search_console(data['site_url'], data['access_token'], data['start_date'], data['end_date'], data.get('dimensions'), data.get('row_limit', 25000), data.get('dimension_filter_groups'), data.get('search_type'), data.get('aggregation_type'), data.get('start_row', 0))
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        status = getattr(getattr(e, 'response', None), 'status_code', 502)
        return jsonify({'success': False, 'error': str(e)}), status


@app.route('/api/integrations/analytics', methods=['POST'])
@login_required
def analytics_integration():
    """Query GA4 Data API with a caller-provided OAuth token."""
    try:
        data = request.get_json() or {}
        required = ('property_id', 'access_token', 'start_date', 'end_date')
        missing = [key for key in required if not data.get(key)]
        if missing:
            return jsonify({'success': False, 'error': f"Missing fields: {', '.join(missing)}"}), 400
        from src.integrations import analytics
        result = analytics(data['property_id'], data['access_token'], data['start_date'], data['end_date'], data.get('metrics'), data.get('dimensions'))
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        status = getattr(getattr(e, 'response', None), 'status_code', 502)
        return jsonify({'success': False, 'error': str(e)}), status

@app.route('/api/integrations/pagespeed', methods=['POST'])
@login_required
def pagespeed_integration():
    """Run one official PageSpeed Insights request with request-scoped credentials."""
    try:
        data = request.get_json(silent=True) or {}
        if not data.get('url'):
            return jsonify({'success': False, 'error': 'url is required'}), 400
        from src.integrations import pagespeed_insights
        result = pagespeed_insights(data['url'], data.get('api_key'), data.get('strategy', 'mobile'), data.get('categories'), data.get('locale'))
        return jsonify({'success': True, 'data': result})
    except Exception as error:
        return jsonify({'success': False, 'error': str(error)}), getattr(getattr(error, 'response', None), 'status_code', 502)

@app.route('/api/integrations/search-console/report', methods=['POST'])
@login_required
def search_console_report_integration():
    try:
        data=request.get_json() or {}
        required=('site_url','access_token','start_date','end_date')
        missing=[key for key in required if not data.get(key)]
        if missing: return jsonify({'success':False,'error':'Missing fields: '+', '.join(missing)}),400
        from src.integrations import search_console_report
        return jsonify({'success':True,'data':search_console_report(data['site_url'],data['access_token'],data['start_date'],data['end_date'],data.get('dimensions'),data.get('row_limit',25000),data.get('dimension_filter_groups'),data.get('search_type'),data.get('aggregation_type'),data.get('start_row',0))})
    except Exception as error:
        return jsonify({'success':False,'error':str(error)}),getattr(getattr(error,'response',None),'status_code',502)

@app.route('/api/integrations/ga4/attribution', methods=['POST'])
@login_required
def ga4_attribution_integration():
    try:
        data=request.get_json() or {}
        required=('property_id','access_token','start_date','end_date')
        missing=[key for key in required if not data.get(key)]
        if missing: return jsonify({'success':False,'error':'Missing fields: '+', '.join(missing)}),400
        from src.integrations import ga4_attribution
        return jsonify({'success':True,'data':ga4_attribution(data['property_id'],data['access_token'],data['start_date'],data['end_date'])})
    except Exception as error:
        return jsonify({'success':False,'error':str(error)}),getattr(getattr(error,'response',None),'status_code',502)

@app.route('/api/integrations/backlinks', methods=['POST'])
@login_required
def backlinks_integration():
    data = request.get_json() or {}
    if not data.get('target_url'):
        return jsonify({'success': False, 'error': 'target_url is required'}), 400
    from src.integrations import backlink_metrics, provider_metrics
    try:
        provider = data.get('provider', 'generic')
        if provider in ('ahrefs', 'majestic', 'moz'):
            result = provider_metrics(provider, data.get('api_key') or data.get('access_token', ''), data['target_url'], data.get('endpoint'), data.get('params'))
        else:
            if not data.get('endpoint'):
                return jsonify({'success': False, 'error': 'endpoint is required for generic provider'}), 400
            result = backlink_metrics(data['endpoint'], data.get('access_token', ''), data['target_url'], provider, data.get('params'))
        return jsonify({'success': True, 'provider': data.get('provider', 'generic'), 'metrics': result})
    except Exception as error:
        status = getattr(getattr(error, 'response', None), 'status_code', 502)
        return jsonify({'success': False, 'error': str(error)}), status

@app.route('/api/schedules', methods=['GET', 'POST'])
@login_required
def schedules_api():
    from src.crawl_db import create_schedule, list_schedules
    if request.method == 'GET':
        return jsonify({'success': True, 'schedules': list_schedules(session.get('user_id'))})
    data = request.get_json() or {}
    required = ('name', 'url')
    if any(not data.get(k) for k in required):
        return jsonify({'success': False, 'error': 'name and url are required'}), 400
    schedule_id = create_schedule(session.get('user_id'), data['name'], data['url'], data.get('mode','spider'), data.get('interval_seconds',86400), data.get('recipients',[]), data.get('settings',{}), data.get('timezone','UTC'))
    return jsonify({'success': True, 'schedule_id': schedule_id}), 201

@app.route('/api/schedules/<int:schedule_id>', methods=['DELETE'])
@login_required
def delete_schedule_api(schedule_id):
    from src.crawl_db import delete_schedule
    return jsonify({'success': delete_schedule(schedule_id, session.get('user_id'))})

@app.route('/api/schedules/<int:schedule_id>/run', methods=['POST'])
@login_required
def run_schedule_api(schedule_id):
    from src.crawl_db import list_schedules
    from src.scheduler_service import execute_schedule
    schedule = next((item for item in list_schedules(session.get('user_id')) if item['id'] == schedule_id), None)
    if not schedule:
        return jsonify({'success': False, 'error': 'schedule not found'}), 404
    try:
        result = execute_schedule(schedule)
        return jsonify({'success': True, 'run': result}), 202
    except Exception as error:
        return jsonify({'success': False, 'error': str(error)}), 500

@app.route('/api/schedules/worker', methods=['POST'])
@login_required
def schedule_worker_api():
    global _scheduler_worker
    from src.scheduler_service import start_scheduler_worker
    data = request.get_json(silent=True) or {}
    action = data.get('action', 'start')
    if action == 'start':
        if _scheduler_worker and _scheduler_worker['thread'].is_alive():
            return jsonify({'success': True, 'status': 'already_running'})
        _scheduler_worker = start_scheduler_worker(data.get('output_dir', 'reports'), data.get('poll_seconds', 30))
        return jsonify({'success': True, 'status': 'started', 'poll_seconds': _scheduler_worker['poll_seconds']})
    if action == 'stop':
        if _scheduler_worker:
            _scheduler_worker['stop'].set()
            _scheduler_worker = None
        return jsonify({'success': True, 'status': 'stopped'})
    return jsonify({'success': False, 'error': 'action must be start or stop'}), 400

@app.route('/api/projects/<int:crawl_id>/export', methods=['POST'])
@login_required
def export_project_api(crawl_id):
    from src.crawl_db import get_crawl_by_id, load_crawled_urls, load_crawl_links, load_crawl_issues
    from src.project_manager import export_project
    crawl = get_crawl_by_id(crawl_id)
    if not crawl or (session.get('user_id') and crawl.get('user_id') != session.get('user_id')):
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', f'project-{crawl_id}.librecrawl')
    export_project(path, crawl, load_crawled_urls(crawl_id), load_crawl_links(crawl_id), load_crawl_issues(crawl_id), crawl.get('config_snapshot'))
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))

@app.route('/api/projects/import', methods=['POST'])
@login_required
def import_project_api():
    from src.project_manager import import_project, restore_project
    upload = request.files.get('project')
    if not upload or not upload.filename.endswith('.librecrawl'):
        return jsonify({'success': False, 'error': 'project .librecrawl file is required'}), 400
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'incoming-project.librecrawl')
    upload.save(path)
    try: result = restore_project(path, session.get('user_id'), session.get('session_id'))
    except Exception as error: return jsonify({'success': False, 'error': str(error)}), 400
    return jsonify({'success': True, 'project': result})

@app.route('/api/projects/retention', methods=['POST'])
@login_required
def project_retention_api():
    data = request.get_json(silent=True) or {}
    try:
        from src.project_manager import apply_retention
        result = apply_retention(session.get('user_id'), data.get('retention_days', 90), data.get('storage_mode', 'full'), bool(data.get('confirm_delete', False)))
        return jsonify({'success': True, 'retention': result})
    except (TypeError, ValueError) as error:
        return jsonify({'success': False, 'error': str(error)}), 400

@app.route('/api/site/certificate', methods=['POST'])
@login_required
def certificate_audit_api():
    data = request.get_json() or {}
    if not data.get('url'): return jsonify({'success': False, 'error': 'url is required'}), 400
    from src.site_audit import certificate_audit
    return jsonify({'success': True, 'certificate': certificate_audit(data['url'])})

@app.route('/api/app/update', methods=['GET', 'POST'])
@login_required
def app_update_api():
    if request.method == 'GET':
        from src.update_service import CURRENT_VERSION
        return jsonify({'success': True, 'version': CURRENT_VERSION,
                        'manifest_configured': bool(os.environ.get('LIBRECRAWL_UPDATE_MANIFEST_URL')),
                        'auto_update': os.environ.get('LIBRECRAWL_AUTO_UPDATE', 'off')})
    data = request.get_json(silent=True) or {}
    action = data.get('action', 'check')
    try:
        from src.update_service import check_update, download_update, apply_update, rollback_update
        if action == 'check':
            return jsonify({'success': True, 'update': check_update(data.get('manifest_url'))})
        if action == 'download':
            return jsonify({'success': True, 'update': download_update(data.get('manifest') or {}, data.get('updates_dir', 'data/updates'))})
        if action == 'apply':
            root = os.path.dirname(os.path.abspath(__file__))
            return jsonify({'success': True, 'update': apply_update(data.get('archive_path'), root, bool(data.get('confirm', False)))})
        if action == 'rollback':
            root = os.path.dirname(os.path.abspath(__file__))
            return jsonify({'success': True, 'update': rollback_update(root)})
        return jsonify({'success': False, 'error': 'action must be check, download, apply or rollback'}), 400
    except Exception as error:
        return jsonify({'success': False, 'error': str(error)}), 400

@app.route('/api/site/carbon', methods=['POST'])
@login_required
def carbon_audit_api():
    data = request.get_json() or {}
    from src.site_audit import carbon_estimate
    return jsonify({'success': True, 'carbon': carbon_estimate(data.get('bytes_transferred', 0), data.get('requests_count', 1), data.get('green_hosting', False))})

@app.route('/api/ahrefs/<tool>', methods=['POST'])
@login_required
def ahrefs_local_tool(tool):
    """Local equivalents of Ahrefs batch/comparison/content workflows."""
    data = request.get_json(silent=True) or {}
    from src.ahrefs_tools import batch_analysis, domain_comparison, content_gap, link_intersect, keyword_opportunities
    if tool == 'batch-analysis': result = batch_analysis(data.get('rows', []))
    elif tool == 'domain-comparison': result = domain_comparison(data.get('datasets', {}))
    elif tool == 'content-gap': result = content_gap(data.get('datasets', {}), data.get('min_count', 1))
    elif tool == 'link-intersect': result = link_intersect(data.get('link_sets', {}))
    elif tool in ('keywords', 'keyword-opportunities'): result = keyword_opportunities(data.get('rows', []), data.get('limit', 100))
    else: return jsonify({'success': False, 'error': 'unknown Ahrefs-compatible local tool'}), 404
    return jsonify({'success': True, 'tool': tool, 'data': result})

@app.route('/api/native-seo/<tool>', methods=['POST'])
@login_required
def native_seo_tool(tool):
    data = request.get_json(silent=True) or {}
    from src.native_seo_intelligence import keyword_index, authority_score, traffic_estimate, record_ranking, ai_prompt_for_seo
    if tool == 'keywords':
        result = keyword_index(data.get('rows', []))
    elif tool == 'authority':
        result = authority_score(data.get('rows', []), data.get('links', []))
    elif tool == 'traffic':
        result = traffic_estimate(data.get('rankings', []))
    elif tool == 'rankings':
        result = record_ranking(data.get('rows', []), data.get('rankings', []), data.get('snapshot'))
    elif tool == 'ai-prompt':
        result = {'prompt': ai_prompt_for_seo(data.get('authority', {}), data.get('keywords', []), data.get('traffic', {}))}
    else:
        return jsonify({'success': False, 'error': 'unknown native SEO tool'}), 404
    return jsonify({'success': True, 'tool': tool, 'data': result})

@app.route('/api/native-seo-tools/<tool>', methods=['POST'])
@login_required
def native_seo_tools_api(tool):
    data=request.get_json(silent=True) or {}
    from src.native_seo_tools import serp_analyze, cluster_keywords, cannibalization, internal_link_suggestions, content_decay, content_brief, rank_snapshot, rank_tracker_report
    if tool=='serp-analyze': result=serp_analyze(data.get('html',''),data.get('target_domain'))
    elif tool=='keyword-cluster': result=cluster_keywords(data.get('keywords',[]))
    elif tool=='cannibalization': result=cannibalization(data.get('rows',[]))
    elif tool=='internal-links': result=internal_link_suggestions(data.get('rows',[]),data.get('links',[]),data.get('limit',50))
    elif tool=='content-decay': result=content_decay(data.get('previous',[]),data.get('current',[]))
    elif tool=='content-brief': result=content_brief(data.get('keyword',''),data.get('rows',[]),data.get('questions'))
    elif tool=='rank-snapshot': result=rank_snapshot(data.get('keyword',''),data.get('url',''),data.get('position',100),data.get('country','global'),data.get('device','desktop'),data.get('serp_features'))
    elif tool=='rank-tracker': result=rank_tracker_report(data.get('snapshots',[]),data.get('keyword'),data.get('country'),data.get('device'))
    else: return jsonify({'success':False,'error':'unknown native SEO tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/native/<tool>', methods=['POST'])
@login_required
def native_seo_utility_api(tool):
    data=request.get_json(silent=True) or {}
    from src.core.seo_utilities import analyze_link_reclamation, redirect_map, sitemap_monitor, indexability_simulator, generate_special_sitemap
    if tool=='link-reclamation': result=analyze_link_reclamation(data.get('rows',[]),data.get('links',[]))
    elif tool=='redirect-map': result=redirect_map(data.get('rows',[]))
    elif tool=='sitemap-monitor': result=sitemap_monitor(data.get('sitemap_urls',[]),data.get('crawled_rows',[]))
    elif tool=='indexability': result=indexability_simulator(data.get('row',{}),data.get('robots_allowed',True),data.get('renderable',True))
    elif tool in ('sitemap-news','sitemap-image','sitemap-video'):
        result={'xml':generate_special_sitemap(data.get('urls',[]),tool.split('-')[1])}
    else: return jsonify({'success':False,'error':'unknown native SEO utility'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/technical/<tool>', methods=['POST'])
@login_required
def technical_seo_api(tool):
    data=request.get_json(silent=True) or {}
    from src.technical_seo_tools import schema_audit, record_cwv, cwv_history, parse_access_log
    if tool=='schema': result=schema_audit(data.get('row',{}))
    elif tool=='cwv-record': result=record_cwv(data.get('url',''),data.get('metrics',{}),data.get('snapshot'))
    elif tool=='cwv-history': result=cwv_history(data.get('records',[]))
    elif tool in ('log-analyze','bot-analytics'):
        result=parse_access_log(data.get('lines',[]))
        if tool=='log-analyze':
            from src.log_seo_tools import crawl_budget
            result['crawl_budget']=crawl_budget(result,data.get('crawled_urls',[]))
        else:
            from src.log_seo_tools import bot_frequency
            result['frequency']=bot_frequency(result)
    elif tool=='serp-features':
        from src.serp_js_tools import serp_features
        result=serp_features(data)
    elif tool=='serp-volatility':
        from src.serp_js_tools import feature_volatility
        result=feature_volatility(data.get('previous',[]),data.get('current',[]))
    elif tool=='javascript-debug':
        from src.serp_js_tools import js_seo_debug
        result=js_seo_debug(data)
    elif tool in ('entities','topical-map','semantic-score','eat','near-duplicates','freshness','editorial-plan'):
        from src.content_intelligence import entities, topical_map, semantic_score, eat_audit, near_duplicates, freshness, editorial_plan
        if tool=='entities': result=entities(data.get('rows',[]))
        elif tool=='topical-map': result=topical_map(data.get('rows',[]))
        elif tool=='semantic-score': result=[semantic_score(row,data.get('target_terms',[])) for row in data.get('rows',[])]
        elif tool=='eat': result=eat_audit(data.get('rows',[]))
        elif tool=='near-duplicates': result=near_duplicates(data.get('rows',[]),data.get('threshold',.85))
        elif tool=='freshness': result=freshness(data.get('rows',[]))
        else: result=editorial_plan(data.get('rows',[]),data.get('cadence_days',14))
    else: return jsonify({'success':False,'error':'unknown technical SEO tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/audit/<tool>', methods=['POST'])
@login_required
def vertical_seo_audit_api(tool):
    data=request.get_json(silent=True) or {}
    from src.vertical_seo_audits import image_audit, accessibility_seo_audit, local_audit, ecommerce_audit, international_audit, programmatic_audit, competitor_content
    rows=data.get('rows',[])
    if tool=='images': result=image_audit(rows)
    elif tool=='accessibility': result=accessibility_seo_audit(rows)
    elif tool=='local': result=local_audit(rows)
    elif tool=='ecommerce': result=ecommerce_audit(rows)
    elif tool=='international': result=international_audit(rows)
    elif tool=='programmatic': result=programmatic_audit(rows)
    elif tool=='competitor-content': result=competitor_content(rows,data.get('competitor_rows',[]))
    elif tool=='product-feed': result=product_feed_audit(data.get('feed_items',[]),rows)
    elif tool in ('local-citations','gbp','map-pack'): result=local_citations(data.get('citations',[]))
    elif tool in ('hreflang-graph','international-serp'): result=hreflang_graph(rows)
    elif tool=='javascript-sitemap':
        from src.vertical_seo_audits import javascript_sitemap_discovery
        result=javascript_sitemap_discovery(data.get('rendered_pages',[]))
    elif tool=='multi-location':
        from src.vertical_seo_audits import multi_location_dashboard
        result=multi_location_dashboard(data.get('locations',[]))
    elif tool=='schema-graph':
        from src.content_intelligence import schema_graph
        result=schema_graph(rows)
    elif tool=='fact-check':
        from src.content_intelligence import citation_fact_audit
        result=citation_fact_audit(rows)
    elif tool=='backlink-quality':
        from src.core.link_metrics import backlink_quality_audit
        result=backlink_quality_audit(data.get('links',[]),data.get('known_domains'))
    else: return jsonify({'success':False,'error':'unknown vertical audit'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/strategy/<tool>', methods=['POST'])
@login_required
def seo_strategy_api(tool):
    data=request.get_json(silent=True) or {}
    from src.seo_strategy import seo_score, forecast, budget_forecast, recommendations, changes, white_label_report, submit_indexnow
    if tool=='score': result=seo_score(data.get('rows',[]),data.get('issues',[]))
    elif tool=='forecast': result=forecast(data.get('history',[]),data.get('horizon',6))
    elif tool=='budget-forecast': result=budget_forecast(data.get('history',[]),data.get('monthly_budget',0),data.get('horizon',6))
    elif tool=='recommendations': result=recommendations(data.get('rows',[]),data.get('issues',[]))
    elif tool=='changes': result=changes(data.get('previous',[]),data.get('current',[]),data.get('fields'))
    elif tool=='report': result=white_label_report(data.get('project',{}),data.get('rows',[]),data.get('issues',[]))
    elif tool=='indexnow':
        try: result=submit_indexnow(data.get('host'),data.get('key'),data.get('urls',[]),data.get('endpoint','https://api.indexnow.org/indexnow'),data.get('key_location'))
        except Exception as error: return jsonify({'success':False,'error':str(error)}),400
    else: return jsonify({'success':False,'error':'unknown SEO strategy tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/history/<kind>', methods=['GET','POST'])
@login_required
def seo_history_api(kind):
    from src.crawl_db import save_rank_snapshot, list_rank_snapshots, save_cwv_snapshot, list_cwv_snapshots
    user_id=session.get('user_id')
    if kind=='rank':
        if request.method=='POST':
            data=request.get_json(silent=True) or {}
            from src.native_seo_tools import rank_snapshot
            snapshot=rank_snapshot(data.get('keyword',''),data.get('url',''),data.get('position',100),data.get('country','global'),data.get('device','desktop'),data.get('serp_features'),data.get('competitor'))
            return jsonify({'success':True,'id':save_rank_snapshot(user_id,snapshot,data.get('crawl_id'))}),201
        return jsonify({'success':True,'snapshots':list_rank_snapshots(user_id,request.args.get('keyword'),request.args.get('url'),request.args.get('limit',500,type=int))})
    if kind=='cwv':
        if request.method=='POST':
            data=request.get_json(silent=True) or {}
            from src.technical_seo_tools import record_cwv
            snapshot=record_cwv(data.get('url',''),data.get('metrics',{}),data.get('snapshot'))
            return jsonify({'success':True,'id':save_cwv_snapshot(user_id,snapshot,data.get('crawl_id'))}),201
        return jsonify({'success':True,'snapshots':list_cwv_snapshots(user_id,request.args.get('url'),request.args.get('limit',500,type=int))})
    return jsonify({'success':False,'error':'kind must be rank or cwv'}),404

@app.route('/api/seo/automation/<tool>', methods=['POST'])
@login_required
def seo_automation_api(tool):
    data=request.get_json(silent=True) or {}
    from src.seo_automation import staging_diff, redirect_plan, regression_tests, incidents, experiment_variant, send_alert
    if tool=='staging-diff': result=staging_diff(data.get('staging',[]),data.get('production',[]))
    elif tool=='redirect-plan': result=redirect_plan(data.get('old_urls',[]),data.get('new_urls',[]))
    elif tool=='regression': result=regression_tests(data.get('rows',[]),data.get('rules'))
    elif tool=='incidents': result=incidents(data.get('previous',[]),data.get('current',[]))
    elif tool=='experiment': result=experiment_variant(data.get('url',''),data.get('title',''),data.get('variant','A'),data.get('metric','ctr'))
    elif tool=='alert':
        try: result=send_alert(data.get('channel','webhook'),data.get('target',''),data.get('message',''),data.get('token'))
        except Exception as error: return jsonify({'success':False,'error':str(error)}),502
    else: return jsonify({'success':False,'error':'unknown automation tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/data/<tool>', methods=['POST'])
@login_required
def seo_data_operations_api(tool):
    data=request.get_json(silent=True) or {}
    from src.data_operations import audit_replay, time_travel_compare, data_lake_export, sql_like_query, sla_monitor, remediation_queue, ai_cost_report, private_mode
    if tool=='replay': result=audit_replay(data.get('events',[]),data.get('at'))
    elif tool=='time-travel': result=time_travel_compare(data.get('events',[]),data.get('first_at',''),data.get('second_at',''))
    elif tool in ('data-lake','export'): result={'data':data_lake_export(data.get('rows',[]),data.get('format','jsonl'))}
    elif tool in ('query','nl-sql'): result=sql_like_query(data.get('rows',[]),data.get('field','url'),data.get('value',''))
    elif tool=='sla': result=sla_monitor(data.get('issues',[]),data.get('thresholds'))
    elif tool in ('remediation','auto-remediation'): result=remediation_queue(data.get('issues',[]))
    elif tool=='ai-cost': result=ai_cost_report(data.get('events',[]))
    elif tool=='private-mode': result=private_mode(data)
    else: return jsonify({'success':False,'error':'unknown data operation'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/platform/<tool>', methods=['POST'])
@login_required
def seo_platform_api(tool):
    data=request.get_json(silent=True) or {}
    from src.enterprise_platform import event_append, event_replay, compliance_policy, ai_registry, plugin_security, stream_event, voice_command, agent_plan
    if tool=='event-append': result=event_append(data.get('stream','seo'),data.get('event',{}),data.get('previous_hash',''))
    elif tool=='event-replay': result=event_replay(data.get('events',[]))
    elif tool in ('compliance','residency'): result=compliance_policy(data,data.get('retention_days',365),data.get('residency','EU'))
    elif tool=='ai-registry': result=ai_registry(data.get('models',[]))
    elif tool in ('plugin-security','marketplace-scan'): result=plugin_security(data.get('plugin',data),data.get('trusted_keys'))
    elif tool in ('stream','kafka','pubsub'): result=stream_event(data.get('event',{}),tool)
    elif tool in ('voice','assistant'): result=voice_command(data.get('transcript',''))
    elif tool in ('agents','multi-agent'): result=agent_plan(data.get('goal',''),data.get('agents'))
    elif tool in ('backlink-campaign','journalist-crm','review-quality','reputation-crisis','customer-scoring'):
        from src.relationship_tools import backlink_campaign, journalist_crm, review_quality, reputation_crisis, customer_scoring
        if tool=='backlink-campaign': result=backlink_campaign(data.get('prospects',[]),data.get('budget',0))
        elif tool=='journalist-crm': result=journalist_crm(data.get('contacts',[]),data.get('interactions'))
        elif tool=='review-quality': result=review_quality(data.get('reviews',[]))
        elif tool=='reputation-crisis': result=reputation_crisis(data.get('reviews',[]),data.get('mentions',[]))
        else: result=customer_scoring(data.get('rows',[]),data.get('weights'))
    elif tool in ('os-workflow','autonomous-agent','multi-site-twin','ecosystem-simulator','causal-impact','approval','guarded-execute','update-clustering','serp-market','demand-warning','competitor-monitor','vulnerability-scan','technical-debt','financial-risk','portfolio-forecast','budget-allocator','content-supply-chain','ai-approval','authorship-provenance','legal-scan','brand-safety','knowledge-panel','entity-reputation','local-competitors','map-volatility','marketplace-audit','feed-canonical-graph','migration-rehearsal','disaster-recovery','rum-summary','synthetic-monitor','privacy-analytics','accessibility-sustainability','edge-policy','cdn-purge-plan','identity-policy','mask-fields','federated-aggregate','local-index','certify-plugin','reproducible-report','knowledge-base','penalty-risk','procurement-questionnaire','review-response-plan','ecommerce-autopilot','connector-readiness','connector-call','semantic-query','agent-sandbox-check','signed-bundle'):
        if tool in ('connector-readiness','connector-call','semantic-query','agent-sandbox-check','signed-bundle'):
            from src.enterprise_connectors import connector_readiness, call_connector, semantic_query, agent_sandbox_check, signed_bundle
            if tool=='connector-readiness': result=connector_readiness(data)
            elif tool=='connector-call':
                try: result=call_connector(data.get('provider',''),data.get('endpoint'),data.get('payload'),data.get('token'),data.get('method','POST'),data.get('timeout',15))
                except Exception as error: return jsonify({'success':False,'error':str(error)}),502
            elif tool=='semantic-query': result=semantic_query(data.get('rows',[]),data.get('query',''),data.get('fields'))
            elif tool=='agent-sandbox-check': result=agent_sandbox_check(data.get('plan',data),data.get('available_tools'))
            else: result=signed_bundle(data.get('data',{}),data.get('evidence'))
        elif tool in ('ai-approval','authorship-provenance','legal-scan','brand-safety','knowledge-panel','entity-reputation','local-competitors','map-volatility','marketplace-audit','feed-canonical-graph'):
            from src.enterprise_compliance import ai_approval_gate, authorship_provenance, legal_content_scan, brand_safety_scan, knowledge_panel_monitor, entity_reputation, local_competitor_monitor, map_volatility, marketplace_audit, feed_sitemap_canonical_graph
            if tool=='ai-approval': result=ai_approval_gate(data.get('item',data),data.get('trusted_facts'),data.get('required_citations',1))
            elif tool=='authorship-provenance': result=authorship_provenance(data.get('items',[]))
            elif tool=='legal-scan': result=legal_content_scan(data.get('rows',[]),data.get('copyrighted_terms'))
            elif tool=='brand-safety': result=brand_safety_scan(data.get('rows',[]),data.get('blocked_terms'))
            elif tool=='knowledge-panel': result=knowledge_panel_monitor(data.get('previous',{}),data.get('current',{}))
            elif tool=='entity-reputation': result=entity_reputation(data.get('rows',[]),data.get('entity',''))
            elif tool=='local-competitors': result=local_competitor_monitor(data.get('previous',[]),data.get('current',[]))
            elif tool=='map-volatility': result=map_volatility(data.get('snapshots',[]))
            elif tool=='marketplace-audit': result=marketplace_audit(data.get('products',[]),data.get('required_fields'))
            else: result=feed_sitemap_canonical_graph(data.get('feed',[]),data.get('sitemap',[]),data.get('pages',[]))
        elif tool in ('identity-policy','mask-fields','federated-aggregate','local-index','certify-plugin','reproducible-report','knowledge-base','penalty-risk','procurement-questionnaire','review-response-plan','ecommerce-autopilot'):
            from src.enterprise_governance import identity_policy, mask_fields, federated_aggregate, local_index, certify_plugin, reproducible_report, knowledge_base, penalty_risk, procurement_questionnaire, review_response_plan, ecommerce_autopilot
            if tool=='identity-policy': result=identity_policy(data)
            elif tool=='mask-fields': result=mask_fields(data.get('rows',[]),data.get('fields'))
            elif tool=='federated-aggregate': result=federated_aggregate(data.get('partitions',[]),data.get('metric','value'))
            elif tool=='local-index': result=local_index(data.get('rows',[]),data.get('query'))
            elif tool=='certify-plugin': result=certify_plugin(data.get('plugin',data),data.get('trusted_scopes'))
            elif tool=='reproducible-report': result=reproducible_report(data.get('report',{}),data.get('inputs'),data.get('model'))
            elif tool=='knowledge-base': result=knowledge_base(data.get('decisions',[]),data.get('query'))
            elif tool=='penalty-risk': result=penalty_risk(data.get('rows',[]))
            elif tool=='procurement-questionnaire': result=procurement_questionnaire(data)
            elif tool=='review-response-plan': result=review_response_plan(data.get('reviews',[]),data.get('approved',False))
            else: result=ecommerce_autopilot(data.get('products',[]),data.get('approved',False))
        elif tool in ('migration-rehearsal','disaster-recovery','rum-summary','synthetic-monitor','privacy-analytics','accessibility-sustainability','edge-policy','cdn-purge-plan'):
            from src.enterprise_resilience import migration_rehearsal, disaster_recovery_snapshot, rum_summary, synthetic_monitor, privacy_safe_analytics, accessibility_sustainability, edge_policy_simulator, cdn_purge_plan
            if tool=='migration-rehearsal': result=migration_rehearsal(data.get('before',[]),data.get('after',[]),data.get('redirects'))
            elif tool=='disaster-recovery': result=disaster_recovery_snapshot(data.get('project',''),data.get('events'))
            elif tool=='rum-summary': result=rum_summary(data.get('samples',[]))
            elif tool=='synthetic-monitor': result=synthetic_monitor(data.get('probes',[]),data.get('thresholds'))
            elif tool=='privacy-analytics': result=privacy_safe_analytics(data.get('events',[]),data.get('dimensions'))
            elif tool=='accessibility-sustainability': result=accessibility_sustainability(data.get('row',data),data.get('bytes_per_page',0))
            elif tool=='edge-policy': result=edge_policy_simulator(data.get('rows',[]),data.get('policy'))
            else: result=cdn_purge_plan(data.get('changes',[]),data.get('approved',False))
        elif tool in ('update-clustering','serp-market','demand-warning','competitor-monitor','vulnerability-scan','technical-debt','financial-risk','portfolio-forecast','budget-allocator','content-supply-chain'):
            from src.enterprise_market import update_clustering, serp_market_intelligence, demand_early_warning, competitor_action_monitor, vulnerability_scan, technical_debt, financial_risk, portfolio_forecast, budget_allocator, content_supply_chain
            if tool=='update-clustering': result=update_clustering(data.get('updates',[]),data.get('threshold',.15))
            elif tool=='serp-market': result=serp_market_intelligence(data.get('snapshots',[]),data.get('dimensions',('market','device')))
            elif tool=='demand-warning': result=demand_early_warning(data.get('keywords',[]),data.get('growth_threshold',.25))
            elif tool=='competitor-monitor': result=competitor_action_monitor(data.get('previous',[]),data.get('current',[]))
            elif tool=='vulnerability-scan': result=vulnerability_scan(data.get('rows',[]))
            elif tool=='technical-debt': result=technical_debt(data.get('rows',[]))
            elif tool=='financial-risk': result=financial_risk(data.get('rows',[]),data.get('revenue_field','revenue'))
            elif tool=='portfolio-forecast': result=portfolio_forecast(data.get('series',[]),data.get('horizon',6),data.get('growth_rate',.05))
            elif tool=='budget-allocator': result=budget_allocator(data.get('workstreams',[]),data.get('budget',0))
            else: result=content_supply_chain(data.get('items',[]),data.get('stages'))
        else:
            from src.seo_operating_system import os_workflow, autonomous_agent, multi_site_twin, ecosystem_simulator, causal_impact, approval_transition, execute_guarded
            if tool=='os-workflow': result=os_workflow(data.get('problem',''),data.get('context'))
            elif tool=='autonomous-agent': result=autonomous_agent(data.get('goal',''),data.get('tools'),data.get('max_actions',3),data.get('budget',10))
            elif tool=='multi-site-twin': result=multi_site_twin(data.get('sites',[]))
            elif tool=='ecosystem-simulator': result=ecosystem_simulator(data.get('metrics',{}),data.get('ecosystems'))
            elif tool=='causal-impact': result=causal_impact(data.get('treatment',[]),data.get('control',[]),data.get('pre_period'),data.get('post_period'))
            elif tool=='approval': result=approval_transition(data.get('workflow',{}),data.get('approved',False))
            else: result=execute_guarded(data.get('workflow',{}),data.get('approved',False))
    else: return jsonify({'success':False,'error':'unknown platform tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/infrastructure/<tool>', methods=['POST'])
@login_required
def seo_infrastructure_api(tool):
    data=request.get_json(silent=True) or {}
    from src.infrastructure_tools import render_queue, cms_request, preview_fix, contract_test, security_privacy_audit
    if tool in ('render-farm','googlebot-render'): result=render_queue(data.get('urls',[]),data.get('workers',2),data.get('user_agent','Googlebot'))
    elif tool=='cms':
        try: result=cms_request(data.get('provider','wordpress'),data.get('endpoint'),data.get('token',''),data.get('method','GET'),data.get('payload'))
        except Exception as error: return jsonify({'success':False,'error':str(error)}),502
    elif tool in ('fix-preview','rollback'): result=preview_fix(data.get('row',{}),data.get('changes',{}) if tool=='fix-preview' else data.get('row',{}))
    elif tool=='contract': result=contract_test(data.get('name','seo'),data.get('actual',{}),data.get('expected',{}))
    elif tool in ('security','privacy'): result=security_privacy_audit(data.get('row',{}))
    else: return jsonify({'success':False,'error':'unknown infrastructure tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/enterprise/<tool>', methods=['POST'])
@login_required
def seo_enterprise_api(tool):
    data=request.get_json(silent=True) or {}
    from src.enterprise_core import digital_twin, rollback_patch, explain, lineage, immutable_audit, ownership, permission_matrix
    if tool=='digital-twin': result=digital_twin(data.get('rows',[]),data.get('proposed_changes'))
    elif tool=='rollback': result=rollback_patch(data)
    elif tool=='explain': result=explain(data.get('metric','score'),data.get('value'),data.get('inputs',{}),data.get('formula',''))
    elif tool=='lineage': result=lineage(data.get('metric',''),data.get('source',''),data.get('transformations'),data.get('quality',1))
    elif tool=='audit-log': result=immutable_audit(data.get('event',{}),data.get('previous_hash',''))
    elif tool=='ownership': result=ownership(data.get('url',''),data.get('owner',''),data.get('team'),data.get('sla_hours',72))
    elif tool=='permissions': result=permission_matrix(data.get('subject',''),data.get('properties',[]),data.get('role','analyst'))
    else: return jsonify({'success':False,'error':'unknown enterprise tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/graphql', methods=['POST'])
@login_required
def graphql_api():
    data=request.get_json(silent=True) or {}
    from src.enterprise_gateway import graphql_query
    return jsonify({'success':True,**graphql_query(data.get('query',''),data.get('variables'),{'projects':[]})})

@app.route('/api/enterprise/gateway/<tool>', methods=['POST'])
@login_required
def enterprise_gateway_api(tool):
    data=request.get_json(silent=True) or {}
    from src.enterprise_gateway import webhook_event, publish_webhook, enterprise_security
    if tool=='event': result=webhook_event(data.get('type','seo.event'),data.get('payload',{}))
    elif tool=='webhook':
        try: result=publish_webhook(data.get('endpoint'),data.get('event',{}),data.get('token'))
        except Exception as error: return jsonify({'success':False,'error':str(error)}),502
    elif tool in ('security','deployment'): result=enterprise_security(data)
    else: return jsonify({'success':False,'error':'unknown gateway tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/realtime/<tool>', methods=['POST'])
@login_required
def seo_realtime_api(tool):
    data=request.get_json(silent=True) or {}
    from src.realtime_enterprise import update_heatmap, causal_attribution, ranking_experiment, serp_replay, adaptive_scheduler, demand_graph, market_gap, entity_conflicts, authority_decay, content_revenue, safe_deploy
    if tool in ('experiment-platform','conversion-rank','algorithm-forensics','regression-gate','remediation-plan','content-roi','competitor-intelligence','citation-gap','serp-screenshot-archive','intent-drift-detector','migration-scale','knowledge-graph-conflicts','crawl-budget-optimizer','digital-pr','seo-security-scan','multilingual-quality','marketplace-monitor','incident-response','copilot-memory','causal-impact-multifactor','digital-twin-realtime','knowledge-graph-proprietary','revenue-at-risk','seo-canary-deploy','ai-factuality','content-provenance','backlink-risk-disavow','data-lake-local','seo-feature-flags','googlebot-profiler','content-quality-benchmark','internal-link-optimizer','lighthouse-regression','rum-multi-country','privacy-attribution','capacity-planner','multi-brand-governance','evidence-vault'):
        from src.nextgen_priority import experiment_platform, conversion_rank_tracker, algorithm_forensics, regression_gate, remediation_plan, content_roi, competitor_intelligence, citation_gap
        if tool=='experiment-platform': result=experiment_platform(data.get('name','experiment'),data.get('control',[]),data.get('variants'),data.get('metric','conversions'),data.get('direction','higher'))
        elif tool=='conversion-rank': result=conversion_rank_tracker(data.get('rows',[]))
        elif tool=='algorithm-forensics': result=algorithm_forensics(data.get('updates',[]),data.get('pages',[]))
        elif tool=='regression-gate': result=regression_gate(data.get('before',{}),data.get('after',{}),data.get('rules'))
        elif tool=='remediation-plan': result=remediation_plan(data.get('issues',[]),data.get('approved',False))
        elif tool=='content-roi': result=content_roi(data.get('rows',[]))
        elif tool=='competitor-intelligence': result=competitor_intelligence(data.get('previous',[]),data.get('current',[]))
        elif tool=='citation-gap': result=citation_gap(data.get('prompts',[]),data.get('owned_sources',[]),data.get('citations',{}))
        elif tool in ('serp-screenshot-archive','intent-drift-detector','migration-scale','knowledge-graph-conflicts','crawl-budget-optimizer'):
            from src.nextgen_advanced import serp_screenshot_archive, intent_drift_detector, large_migration_rehearsal, knowledge_graph_conflicts, crawl_budget_optimizer
            if tool=='serp-screenshot-archive': result=serp_screenshot_archive(data.get('snapshots',[]),data.get('pixel_threshold',0))
            elif tool=='intent-drift-detector': result=intent_drift_detector(data.get('previous',[]),data.get('current',[]))
            elif tool=='migration-scale': result=large_migration_rehearsal(data.get('before',[]),data.get('after',[]),data.get('redirects'),data.get('batch_size',10000))
            elif tool=='knowledge-graph-conflicts': result=knowledge_graph_conflicts(data.get('rows',[]))
            else: result=crawl_budget_optimizer(data.get('urls',[]),data.get('budget',100),data.get('learning_rate',.1),data.get('iterations',3))
        elif tool in ('causal-impact-multifactor','digital-twin-realtime','knowledge-graph-proprietary','revenue-at-risk','seo-canary-deploy','ai-factuality','content-provenance','backlink-risk-disavow','data-lake-local','seo-feature-flags','googlebot-profiler','content-quality-benchmark','internal-link-optimizer','lighthouse-regression','rum-multi-country','privacy-attribution','capacity-planner','multi-brand-governance','evidence-vault'):
            from src.frontier_seo import causal_impact_multifactor, realtime_digital_twin, proprietary_knowledge_graph, revenue_at_risk_incidents, seo_canary_deploy, ai_factuality_check, content_provenance, backlink_risk_disavow, self_hosted_data_lake, seo_feature_flags, googlebot_behavior_profiler, content_quality_benchmark, internal_link_optimizer, lighthouse_regression, rum_multi_country, privacy_attribution, capacity_planner, multi_brand_governance, evidence_vault
            if tool=='causal-impact-multifactor': result=causal_impact_multifactor(data.get('treatment',[]),data.get('control',[]),data.get('factors'))
            elif tool=='digital-twin-realtime': result=realtime_digital_twin(data.get('production',[]),data.get('staging',[]),data.get('events'))
            elif tool=='knowledge-graph-proprietary': result=proprietary_knowledge_graph(data.get('rows',[]),data.get('links'))
            elif tool=='revenue-at-risk': result=revenue_at_risk_incidents(data.get('incidents',[]))
            elif tool=='seo-canary-deploy': result=seo_canary_deploy(data.get('changes',[]),data.get('baseline',{}),data.get('canary',{}),data.get('guardrails'),data.get('approvals',0))
            elif tool=='ai-factuality': result=ai_factuality_check(data.get('responses',[]),data.get('trusted_facts',[]),data.get('trusted_sources'))
            elif tool=='content-provenance': result=content_provenance(data.get('rows',[]))
            elif tool=='backlink-risk-disavow': result=backlink_risk_disavow(data.get('links',[]),data.get('threshold',50))
            elif tool=='data-lake-local': result=self_hosted_data_lake(data.get('rows',[]),data.get('query'),data.get('dimension'))
            elif tool=='seo-feature-flags': result=seo_feature_flags(data.get('rows',[]),data.get('flags',{}),data.get('context'))
            elif tool=='googlebot-profiler': result=googlebot_behavior_profiler(data.get('logs',[]))
            elif tool=='content-quality-benchmark': result=content_quality_benchmark(data.get('rows',[]),data.get('sector'))
            elif tool=='internal-link-optimizer': result=internal_link_optimizer(data.get('rows',[]),data.get('links',[]),data.get('limit',20))
            elif tool=='lighthouse-regression': result=lighthouse_regression(data.get('before',{}),data.get('after',{}),data.get('thresholds'))
            elif tool=='rum-multi-country': result=rum_multi_country(data.get('samples',[]))
            elif tool=='privacy-attribution': result=privacy_attribution(data.get('touchpoints',[]))
            elif tool=='capacity-planner': result=capacity_planner(data.get('items',[]),data.get('people',1),data.get('days',30))
            elif tool=='multi-brand-governance': result=multi_brand_governance(data.get('rows',[]),data.get('roles'))
            else: result=evidence_vault(data.get('events',[]),data.get('previous_hash',''))
        else:
            from src.nextgen_operations import digital_pr_opportunities, seo_security_scan, multilingual_quality, marketplace_monitor, incident_response, seo_copilot_memory
            if tool=='digital-pr': result=digital_pr_opportunities(data.get('prospects',[]),data.get('campaign'))
            elif tool=='seo-security-scan': result=seo_security_scan(data.get('rows',[]))
            elif tool=='multilingual-quality': result=multilingual_quality(data.get('rows',[]),data.get('required_languages'))
            elif tool=='marketplace-monitor': result=marketplace_monitor(data.get('rows',[]),data.get('channels'))
            elif tool=='incident-response': result=incident_response(data.get('incidents',[]),data.get('thresholds'))
            else: result=seo_copilot_memory(data.get('decisions',[]),data.get('query'),data.get('approved_only',True))
    elif tool=='heatmap': result=update_heatmap(data.get('before',[]),data.get('after',[]),data.get('dimension','url'))
    elif tool=='attribution': result=causal_attribution(data.get('touchpoints',[]),data.get('revenue_field','revenue'))
    elif tool=='experiment': result=ranking_experiment(data.get('name','experiment'),data.get('control',[]),data.get('variants'),data.get('metric','position'))
    elif tool=='serp-replay': result=serp_replay(data.get('previous',[]),data.get('current',[]),data.get('pixel_diff_percent'))
    elif tool=='adaptive-crawl': result=adaptive_scheduler(data.get('urls',[]),data.get('changes'),data.get('budget',100))
    elif tool=='demand-graph': result=demand_graph(data.get('keywords',[]),data.get('markets'))
    elif tool=='market-gap': result=market_gap(data.get('datasets',{}))
    elif tool=='entity-conflicts': result=entity_conflicts(data.get('row',{}))
    elif tool=='authority-decay': result=authority_decay(data.get('history',[]),data.get('threshold',.2))
    elif tool=='content-revenue': result=content_revenue(data.get('rows',[]))
    elif tool in ('safe-deploy','canary'): result=safe_deploy(data.get('changes',[]),data.get('approvals',0),data.get('required_approvals',1))
    elif tool in ('causal-graph','anomaly-explainer','observability','intent-drift','query-satisfaction','zero-click','misinformation','freshness-prediction','serp-diff','cannibalization-plan','topical-benchmark','pagerank-links','link-attack','rollback-guard','evidence-snapshot','ai-citations','hallucination','margin-optimizer','inventory-canonical','hreflang-deploy','geo-test','cdn-conflicts','googlebot-prediction','crawl-cost','adaptive-recrawl','content-capacity','seo-roi','multi-touch','executive-report'):
        from src.enterprise_intelligence import causal_graph, anomaly_explainer, observability, intent_drift, query_satisfaction, zero_click_visibility, misinformation_check, freshness_prediction
        if tool=='causal-graph': result=causal_graph(data.get('events',[]))
        elif tool=='anomaly-explainer': result=anomaly_explainer(data.get('current',{}),data.get('baseline',{}),data.get('events'))
        elif tool=='observability': result=observability(data.get('samples',[]))
        elif tool=='intent-drift': result=intent_drift(data.get('previous',[]),data.get('current',[]))
        elif tool=='query-satisfaction': result=query_satisfaction(data.get('rows',[]))
        elif tool=='zero-click': result=zero_click_visibility(data.get('rows',[]))
        elif tool=='misinformation': result=misinformation_check(data.get('entity',''),data.get('claims',[]),data.get('trusted_facts',[]))
        elif tool=='serp-diff':
            from src.enterprise_next import serp_visual_diff
            result=serp_visual_diff(data.get('previous_html'),data.get('current_html'))
        elif tool=='cannibalization-plan':
            from src.enterprise_next import cannibalization_plan
            result=cannibalization_plan(data.get('rows',[]))
        elif tool=='topical-benchmark':
            from src.enterprise_next import topical_benchmark
            result=topical_benchmark(data.get('site_topics'),data.get('competitor_topics'))
        elif tool=='pagerank-links':
            from src.enterprise_next import pagerank_recommendations
            result=pagerank_recommendations(data.get('rows',[]),data.get('links',[]))
        elif tool=='link-attack':
            from src.enterprise_next import link_attack_detector
            result=link_attack_detector(data.get('links',[]))
        elif tool=='rollback-guard':
            from src.enterprise_next import rollback_guardrail
            result=rollback_guardrail(data.get('before',[]),data.get('after',[]),data.get('thresholds'))
        elif tool in ('ai-citations','hallucination','margin-optimizer','inventory-canonical','hreflang-deploy','geo-test','cdn-conflicts'):
            from src.enterprise_commerce import ai_citation_ownership, hallucination_monitor, margin_optimizer, inventory_canonical, hreflang_deployment_check, geo_test, cdn_indexability_conflicts
            if tool=='ai-citations': result=ai_citation_ownership(data.get('prompts',[]),data.get('brand',''),data.get('citations'))
            elif tool=='hallucination': result=hallucination_monitor(data.get('responses',[]),data.get('trusted_facts'))
            elif tool=='margin-optimizer': result=margin_optimizer(data.get('products',[]),data.get('sessions',1000))
            elif tool=='inventory-canonical': result=inventory_canonical(data.get('products',[]))
            elif tool=='hreflang-deploy': result=hreflang_deployment_check(data.get('rows',[]))
            elif tool=='geo-test': result=geo_test(data.get('urls',[]),data.get('markets'),data.get('expected_language'))
            else: result=cdn_indexability_conflicts(data.get('rows',[]))
        elif tool in ('googlebot-prediction','crawl-cost','adaptive-recrawl','content-capacity','seo-roi','multi-touch','executive-report'):
            from src.enterprise_operations import googlebot_prediction, crawl_budget_cost, adaptive_recrawl, content_capacity, seo_roi, multi_touch_attribution, executive_report
            if tool=='googlebot-prediction': result=googlebot_prediction(data.get('rows',[]),data.get('horizon_days',7))
            elif tool=='crawl-cost': result=crawl_budget_cost(data.get('rows',[]),data.get('cost_per_request',.001),data.get('cpu_seconds_per_request',.2))
            elif tool=='adaptive-recrawl': result=adaptive_recrawl(data.get('rows',[]),data.get('budget',100))
            elif tool=='content-capacity': result=content_capacity(data.get('items',[]),data.get('people',1),data.get('days',30))
            elif tool=='seo-roi': result=seo_roi(data.get('investments',[]))
            elif tool=='multi-touch': result=multi_touch_attribution(data.get('touchpoints',[]))
            else: result=executive_report(data.get('metrics',[]))
        else:
            from src.enterprise_next import evidence_snapshot
            result=evidence_snapshot(data.get('data',{}))
    else: return jsonify({'success':False,'error':'unknown realtime SEO tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/advanced/<tool>', methods=['POST'])
@login_required
def advanced_seo_api(tool):
    data=request.get_json(silent=True) or {}
    from src.aeo_crawl_controls import prompt_visibility, brand_mentions, ai_crawler_policy, crawl_space_audit, pagination_audit
    if tool=='prompt-visibility': result=prompt_visibility(data.get('prompt',''),data.get('responses',[]),data.get('brand_terms',[]))
    elif tool in ('brand-mentions','digital-pr'): result=brand_mentions(data.get('documents',[]),data.get('brand_terms',[]))
    elif tool=='ai-crawler-policy': result=ai_crawler_policy(data.get('robots_text',''),data.get('allowed_bots'))
    elif tool in ('crawl-space','faceted-navigation','parameters','crawl-traps'): result=crawl_space_audit(data.get('urls',[]))
    elif tool in ('pagination','archives'): result=pagination_audit(data.get('rows',[]))
    elif tool in ('knowledge-graph','topic-gap','search-intent','algorithm-updates','causal-forecast','impact-simulator'):
        from src.advanced_next import knowledge_graph, topic_gap, search_intent, algorithm_update_detector, causal_forecast, impact_simulator
        if tool=='knowledge-graph': result=knowledge_graph(data.get('rows',[]))
        elif tool=='topic-gap': result=topic_gap(data.get('rows',[]),data.get('target_terms',[]))
        elif tool=='search-intent': result=search_intent(data.get('keyword',''),data.get('serp_rows'))
        elif tool=='algorithm-updates': result=algorithm_update_detector(data.get('snapshots',[]),data.get('threshold',20))
        elif tool=='causal-forecast': result=causal_forecast(data.get('history',[]),data.get('events'),data.get('horizon',6))
        else: result=impact_simulator(data.get('rows',[]),data.get('changes',{}))
    elif tool in ('discover-news','news'):
        from src.professional_tools import discover_news_audit
        result=discover_news_audit(data.get('rows',[]))
    else: return jsonify({'success':False,'error':'unknown advanced SEO tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/seo/professional/catalog')
@login_required
def professional_catalog():
    from src.professional_tools import SEO_TOOL_CATALOG, capability_catalog
    return jsonify({'success':True,'tools':SEO_TOOL_CATALOG,'capabilities':capability_catalog(),'mcp':'/api/mcp','plugin_path':'web/static/plugins'})

@app.route('/api/seo/professional/audit')
@login_required
def professional_capability_audit():
    from src.professional_tools import capability_audit
    return jsonify({'success': True, **capability_audit()})

@app.route('/api/seo/professional/plugin', methods=['POST'])
@login_required
def professional_plugin():
    data=request.get_json(silent=True) or {}
    if not data.get('id') or not data.get('name'):
        return jsonify({'success':False,'error':'id and name are required'}),400
    from src.professional_tools import register_plugin
    return jsonify({'success':True,'plugin':register_plugin(data['id'],data['name'],data.get('hooks'))}),201

@app.route('/api/seo/professional/workflow', methods=['POST'])
@login_required
def professional_workflow():
    data=request.get_json(silent=True) or {}
    try:
        from src.professional_tools import send_workflow
        result=send_workflow(data.get('provider','webhook'),data.get('endpoint'),data.get('title','SEO issue'),data.get('description',''),data.get('url'),data.get('token'),data.get('labels'))
        return jsonify({'success':True,'data':result})
    except Exception as error:
        return jsonify({'success':False,'error':str(error)}),502

@app.route('/api/integrations/search-console/inspection', methods=['POST'])
@login_required
def search_console_inspection_integration():
    data=request.get_json(silent=True) or {}
    try:
        from src.integrations import search_console_inspection
        return jsonify({'success':True,'data':search_console_inspection(data.get('site_url'),data.get('inspection_url'),data.get('access_token'),data.get('language_code','en-US'))})
    except Exception as error: return jsonify({'success':False,'error':str(error)}),502

@app.route('/api/integrations/bing-webmaster', methods=['POST'])
@login_required
def bing_webmaster_integration():
    data=request.get_json(silent=True) or {}
    try:
        from src.integrations import bing_webmaster_call
        return jsonify({'success':True,'data':bing_webmaster_call(data.get('endpoint'),data.get('api_key'),data.get('payload'),data.get('method','POST'))})
    except Exception as error: return jsonify({'success':False,'error':str(error)}),502

@app.route('/api/integrations/bing-webmaster/operation', methods=['POST'])
@login_required
def bing_webmaster_operation_integration():
    data=request.get_json(silent=True) or {}
    try:
        from src.integrations import bing_webmaster_operation
        return jsonify({'success':True,'data':bing_webmaster_operation(data.get('operation'),data.get('endpoint'),data.get('api_key'),data.get('site_url'),data.get('payload'))})
    except Exception as error: return jsonify({'success':False,'error':str(error)}),502

@app.route('/api/integrations/search-console/resources', methods=['POST'])
@login_required
def search_console_resources_integration():
    data=request.get_json(silent=True) or {}
    try:
        from src.integrations import search_console_sites, search_console_sitemaps
        result=search_console_sites(data.get('access_token')) if data.get('resource')=='sites' else search_console_sitemaps(data.get('site_url'),data.get('access_token'),data.get('sitemap_url'),data.get('method','GET'))
        return jsonify({'success':True,'data':result})
    except Exception as error: return jsonify({'success':False,'error':str(error)}),502

@app.route('/api/integrations/ga4/report', methods=['POST'])
@login_required
def ga4_report_integration():
    data=request.get_json(silent=True) or {}
    try:
        from src.integrations import ga4_report
        return jsonify({'success':True,'data':ga4_report(data.get('property_id'),data.get('access_token'),data.get('start_date'),data.get('end_date'),data.get('dimensions',[]),data.get('metrics',[]),data.get('dimension_filter'),data.get('metric_filter'),data.get('order_bys'),data.get('limit'),data.get('offset'),data.get('keep_empty_rows',False),data.get('return_property_quota',False))})
    except Exception as error: return jsonify({'success':False,'error':str(error)}),502

@app.route('/api/seo/research/<tool>', methods=['POST'])
@login_required
def research_enterprise_api(tool):
    data=request.get_json(silent=True) or {}
    from src.research_enterprise import capability_matrix, page_inspect_history, portfolio_metrics, ai_bot_analytics, ai_visibility_report, report_task, report_task_status, data_quality_report, workspace_audit, patch_automation, patch_transition, patch_apply_local, patch_rollback_local, portfolio_dashboard
    from src.priority_tools import cron_next, resource_audit, spa_detection, duplicate_fingerprint
    if tool=='capabilities': result=capability_matrix()
    elif tool=='cron-next': result={'next_run':cron_next(data.get('expression'),data.get('timezone','UTC'),datetime.fromisoformat(data['now']) if data.get('now') else None)}
    elif tool=='resource-audit': result=resource_audit(data.get('rows',[]))
    elif tool=='spa-detection': result=spa_detection(data.get('row',data))
    elif tool=='duplicate-fingerprint': result=duplicate_fingerprint(data.get('text',''),data.get('simhash',False))
    elif tool=='page-history': result=page_inspect_history(data.get('snapshots',[]),data.get('url'))
    elif tool=='portfolio': result=portfolio_metrics(data.get('projects',[]))
    elif tool=='ai-bots': result=ai_bot_analytics(data.get('logs',[]))
    elif tool=='ai-visibility': result=ai_visibility_report(data.get('prompts',[]),data.get('target_domain'))
    elif tool=='report-task': result=report_task(data.get('data',{}),data.get('task_id'),data.get('async',True))
    elif tool=='report-task-status': result=report_task_status(data.get('task_id',''))
    elif tool=='data-quality': result=data_quality_report(data.get('rows',[]),data.get('expected_fields'),data.get('sample_metadata'))
    elif tool=='workspace-audit': result=workspace_audit(data.get('events',[]))
    elif tool=='patch-automation': result=patch_automation(data.get('issues',[]),data.get('approved',False))
    elif tool=='patch-apply': result=patch_apply_local(data.get('rows',[]),data.get('plans',[]),data.get('approved',False))
    elif tool=='patch-rollback': result=patch_rollback_local(data.get('rows',[]),data.get('changes',[]),data.get('approved',False))
    elif tool=='patch-transition': result=patch_transition(data.get('plans',[]),data.get('approved',False),False)
    elif tool=='dashboard': result=portfolio_dashboard(data.get('projects',[]),data.get('data_rows'),data.get('bot_logs'),data.get('report_tasks'))
    else: return jsonify({'success':False,'error':'unknown research tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/enterprise-next/<tool>', methods=['POST'])
@login_required
def enterprise_next_api(tool):
    data=request.get_json(silent=True) or {}
    from src.enterprise_next_tools import enterprise_next_capabilities, parse_log_lines, log_analyzer, rum_compare, crux_query, migration_assistant, security_scan, content_governance, serp_volatility, brand_monitor, rich_results_bulk, crawl_replay, warehouse_export, warehouse_query, product_intelligence, prioritize
    if tool=='capabilities': result=enterprise_next_capabilities()
    elif tool=='log-analyzer': result=log_analyzer(parse_log_lines(data.get('lines',[]),data.get('format','auto')) if data.get('lines') else data.get('records',[]),data.get('crawled_urls'))
    elif tool=='rum-compare': result=rum_compare(data.get('samples',[]),data.get('lighthouse'))
    elif tool=='crux':
        try: result=crux_query(data.get('origin'),data.get('url'),data.get('api_key'),data.get('form_factor'))
        except Exception as error: return jsonify({'success':False,'error':str(error)}),502
    elif tool=='migration': result=migration_assistant(data.get('before',[]),data.get('after',[]),data.get('redirects'),data.get('traffic'))
    elif tool=='security': result=security_scan(data.get('rows',[]))
    elif tool=='content-governance': result=content_governance(data.get('rows',[]),data.get('approvals'),data.get('previous'))
    elif tool=='serp-volatility': result=serp_volatility(data.get('rows',[]),data.get('update_dates'))
    elif tool=='brand-monitor': result=brand_monitor(data.get('mentions',[]),data.get('reviews'))
    elif tool=='rich-results': result=rich_results_bulk(data.get('rows',[]))
    elif tool=='crawl-replay': result=crawl_replay(data.get('events',[]),data.get('url'))
    elif tool=='warehouse-export': result={'format':data.get('format','json'),'content':warehouse_export(data.get('rows',[]),data.get('format','json'))}
    elif tool=='warehouse-query':
        try: result=warehouse_query(data.get('rows',[]),data.get('query',''))
        except ValueError as error: return jsonify({'success':False,'error':str(error)}),400
    elif tool=='product-intelligence': result=product_intelligence(data.get('products',[]),data.get('feed_items'))
    elif tool=='prioritize': result=prioritize(data.get('issues',[]),data.get('revenue'))
    else: return jsonify({'success':False,'error':'unknown enterprise-next tool'}),404
    return jsonify({'success':True,'tool':tool,'data':result})

@app.route('/api/parity/<tool>', methods=['GET', 'POST'])
@login_required
def parity_api(tool):
    """Expose Screaming-Frog-style lower panels and custom crawl rules."""
    if tool == 'catalog':
        from src.parity_catalog import parity_catalog
        return jsonify({'success': True, 'tool': tool, 'data': parity_catalog()})
    from src.parity_tools import page_panels, custom_extract, custom_search, link_positions, html_validation
    data = request.get_json(silent=True) or {}
    row = data.get('row', data)
    if tool == 'panels': result = page_panels(row)
    elif tool == 'custom-extraction': result = custom_extract(row, data.get('rules', []))
    elif tool == 'custom-search': result = custom_search(row, data.get('searches', []))
    elif tool == 'link-positions': result = link_positions(row)
    elif tool == 'html-validation': result = html_validation(row)
    else: return jsonify({'success': False, 'error': 'unknown parity tool'}), 404
    return jsonify({'success': True, 'tool': tool, 'data': result})

@app.route('/api/seo/dashboard')
@login_required
def seo_dashboard_api():
    from src.crawl_db import get_user_crawls, load_crawled_urls, load_crawl_issues
    from src.seo_strategy import seo_score
    dashboards=[]
    for crawl in get_user_crawls(session.get('user_id'),limit=100):
        urls=load_crawled_urls(crawl['id']); issues=load_crawl_issues(crawl['id'])
        dashboards.append({'crawl':crawl,'score':seo_score(urls,issues),'urls':len(urls),'issues':len(issues)})
    return jsonify({'success':True,'projects':dashboards})

@app.route('/api/team/cloud-sync', methods=['POST'])
@login_required
def cloud_sync():
    data = request.get_json() or {}
    if not data.get('endpoint') or not data.get('crawl_id'):
        return jsonify({'success': False, 'error': 'endpoint and crawl_id are required'}), 400
    from src.crawl_db import get_crawl_by_id, load_crawled_urls, load_crawl_links, load_crawl_issues
    crawl = get_crawl_by_id(data['crawl_id'])
    if not crawl:
        return jsonify({'success': False, 'error': 'crawl not found'}), 404
    if session.get('user_id') and crawl.get('user_id') != session.get('user_id'):
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    from src.integrations import sync_crawl
    payload = {'crawl': crawl, 'urls': load_crawled_urls(data['crawl_id']), 'links': load_crawl_links(data['crawl_id']), 'issues': load_crawl_issues(data['crawl_id'])}
    try:
        return jsonify({'success': True, 'response': sync_crawl(data['endpoint'], data.get('access_token', ''), payload)})
    except Exception as error:
        status = getattr(getattr(error, 'response', None), 'status_code', 502)
        return jsonify({'success': False, 'error': str(error)}), status


@app.route('/api/export_data', methods=['POST'])
@login_required
def export_data():
    try:
        data = request.get_json()
        export_format = data.get('format', 'csv')
        export_fields = data.get('fields', ['url', 'status_code', 'title'])
        local_data = data.get('localData', {})

        # Use local data if provided (from loaded crawl), otherwise get from crawler
        if local_data and local_data.get('urls'):
            urls = local_data.get('urls', [])
            links = local_data.get('links', [])
            issues = local_data.get('issues', [])
        else:
            # Get current crawl results
            crawler = get_or_create_crawler()
            crawl_data = crawler.get_status()
            urls = crawl_data.get('urls', [])
            links = crawl_data.get('links', [])
            issues = crawl_data.get('issues', [])

        if not urls:
            return jsonify({'success': False, 'error': 'No data to export'})

        # Update link statuses from crawled URLs (fixes missing status codes in exports)
        if links and urls:
            status_lookup = {url_data['url']: url_data.get('status_code') for url_data in urls}
            for link in links:
                target_url = link.get('target_url')
                if target_url in status_lookup:
                    link['target_status'] = status_lookup[target_url]

        # Apply current issue exclusion patterns (works for loaded crawls too)
        if issues:
            settings_manager = get_session_settings()
            current_settings = settings_manager.get_settings()
            exclusion_patterns_text = current_settings.get('issueExclusionPatterns', '')
            exclusion_patterns = [p.strip() for p in exclusion_patterns_text.split('\n') if p.strip()]
            issues = filter_issues_by_exclusion_patterns(issues, exclusion_patterns)
            print(f"DEBUG: After exclusion filter, {len(issues)} issues remain")

        # Collect files to export based on special field selections
        files_to_export = []

        # Check for special export fields and prepare them as separate files
        has_issues_export = 'issues_detected' in export_fields
        has_links_export = 'links_detailed' in export_fields

        # Remove special fields from regular export fields
        regular_fields = [f for f in export_fields if f not in ['issues_detected', 'links_detailed']]

        # Debug logging
        print(f"DEBUG: export_fields = {export_fields}")
        print(f"DEBUG: has_issues_export = {has_issues_export}")
        print(f"DEBUG: has_links_export = {has_links_export}")
        print(f"DEBUG: regular_fields = {regular_fields}")
        print(f"DEBUG: len(urls) = {len(urls)}")
        print(f"DEBUG: len(links) = {len(links)}")
        print(f"DEBUG: len(issues) = {len(issues)}")

        # Generate issues export if requested
        if has_issues_export:
            if export_format == 'csv':
                issues_content = generate_issues_csv_export(issues)
                issues_mimetype = 'text/csv'
                issues_filename = f'librecrawl_issues_{int(time.time())}.csv'
            elif export_format == 'json':
                issues_content = generate_issues_json_export(issues)
                issues_mimetype = 'application/json'
                issues_filename = f'librecrawl_issues_{int(time.time())}.json'
            else:
                issues_content = generate_issues_csv_export(issues)
                issues_mimetype = 'text/csv'
                issues_filename = f'librecrawl_issues_{int(time.time())}.csv'

            files_to_export.append({
                'content': issues_content,
                'mimetype': issues_mimetype,
                'filename': issues_filename
            })

        # Generate links export if requested
        if has_links_export:
            if export_format == 'csv':
                links_content = generate_links_csv_export(links)
                links_mimetype = 'text/csv'
                links_filename = f'librecrawl_links_{int(time.time())}.csv'
            elif export_format == 'json':
                links_content = generate_links_json_export(links)
                links_mimetype = 'application/json'
                links_filename = f'librecrawl_links_{int(time.time())}.json'
            else:
                links_content = generate_links_csv_export(links)
                links_mimetype = 'text/csv'
                links_filename = f'librecrawl_links_{int(time.time())}.csv'

            files_to_export.append({
                'content': links_content,
                'mimetype': links_mimetype,
                'filename': links_filename
            })

        # Generate regular export if there are regular fields
        if regular_fields:
            if export_format == 'csv':
                regular_content = generate_csv_export(urls, regular_fields)
                regular_mimetype = 'text/csv'
                regular_filename = f'librecrawl_export_{int(time.time())}.csv'
            elif export_format == 'json':
                regular_content = generate_json_export(urls, regular_fields)
                regular_mimetype = 'application/json'
                regular_filename = f'librecrawl_export_{int(time.time())}.json'
            elif export_format == 'xml':
                regular_content = generate_xml_export(urls, regular_fields)
                regular_mimetype = 'application/xml'
                regular_filename = f'librecrawl_export_{int(time.time())}.xml'
            else:
                return jsonify({'success': False, 'error': 'Unsupported export format'})

            files_to_export.append({
                'content': regular_content,
                'mimetype': regular_mimetype,
                'filename': regular_filename
            })

        # Handle special case where only special fields are selected but no data
        if not files_to_export:
            if has_issues_export and not issues:
                return jsonify({'success': False, 'error': 'No issues data to export'})
            elif has_links_export and not links:
                return jsonify({'success': False, 'error': 'No links data to export'})
            else:
                return jsonify({'success': False, 'error': 'No data to export'})

        # Return multiple files if we have more than one, otherwise single file
        if len(files_to_export) > 1:
            return jsonify({
                'success': True,
                'multiple_files': True,
                'files': files_to_export
            })
        else:
            # Single file
            file_data = files_to_export[0]
            return jsonify({
                'success': True,
                'content': file_data['content'],
                'mimetype': file_data['mimetype'],
                'filename': file_data['filename']
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def recover_crashed_crawls():
    """Check for and recover any crashed crawls on startup"""
    try:
        from src.crawl_db import get_crashed_crawls, set_crawl_status

        crashed = get_crashed_crawls()

        if crashed:
            print("\n" + "=" * 60)
            print("CRASH RECOVERY")
            print("=" * 60)
            for crawl in crashed:
                set_crawl_status(crawl['id'], 'failed')
                print(f"Found crashed crawl: {crawl['base_url']} (ID: {crawl['id']})")
                print(f"  → Marked as failed. User can resume from dashboard.")
            print("=" * 60 + "\n")
    except Exception as e:
        print(f"Error during crash recovery: {e}")

def graceful_shutdown(signum, frame):
    """Save all active crawls before shutdown"""
    print("\n" + "=" * 60)
    print("GRACEFUL SHUTDOWN")
    print("=" * 60)
    print("Saving all active crawls...")

    try:
        with instances_lock:
            for session_id, instance_data in list(crawler_instances.items()):
                crawler = instance_data['crawler']
                if crawler.is_running and crawler.crawl_id and crawler.db_save_enabled:
                    print(f"  → Saving crawl {crawler.crawl_id}...")
                    try:
                        crawler._save_batch_to_db(force=True)
                        crawler._save_queue_checkpoint()
                        from src.crawl_db import set_crawl_status
                        set_crawl_status(crawler.crawl_id, 'paused')
                    except Exception as e:
                        print(f"    Error saving crawl {crawler.crawl_id}: {e}")

        print("All crawls saved successfully")
        print("=" * 60)
    except Exception as e:
        print(f"Error during shutdown: {e}")

    print("Goodbye!")
    import sys
    sys.exit(0)

def maybe_auto_update():
    """Check/apply a verified update when explicitly configured by the operator."""
    manifest_url = os.getenv('LIBRECRAWL_UPDATE_MANIFEST_URL', '').strip()
    mode = os.getenv('LIBRECRAWL_AUTO_UPDATE', 'off').lower()
    if not manifest_url or mode not in ('check', 'apply'):
        return
    try:
        from src.update_service import check_update, download_update, apply_update
        checked = check_update(manifest_url)
        if not checked['update_available']:
            print(f"Auto-update: already current ({checked['current_version']})")
            return
        print(f"Auto-update: version {checked['available_version']} available")
        downloaded = download_update(checked['manifest'])
        print(f"Auto-update: verified archive {downloaded['path']}")
        if mode == 'apply':
            applied = apply_update(downloaded['path'], os.path.dirname(os.path.abspath(__file__)), confirm=True)
            print(f"Auto-update: applied with backup at {applied['backup']}")
        else:
            print('Auto-update: check-only mode; set LIBRECRAWL_AUTO_UPDATE=apply to install')
    except Exception as error:
        print(f"Auto-update unavailable: {error}")

def main():
    import signal

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    # Recover any crashed crawls from previous session
    recover_crashed_crawls()

    # Optional manifest-driven update check before starting the web server.
    maybe_auto_update()

    # Start cleanup thread for old crawler instances
    start_cleanup_thread()

    print("=" * 60)
    print("Deep Crawling - SEO Spider")
    print("=" * 60)
    port = int(os.getenv('PORT', '5000'))
    public_url = f'http://localhost:{port}'
    print(f"\n🚀 Server starting on http://0.0.0.0:{port}")
    print(f"🌐 Access from browser: {public_url}")
    print(f"📱 Access from network: http://<your-ip>:{port}")
    print(f"\n✨ Multi-tenancy enabled - each browser session is isolated")
    print(f"💾 Settings stored in browser localStorage")
    print(f"\nPress Ctrl+C to stop the server\n")
    print("=" * 60 + "\n")

    # Open browser in a separate thread after short delay
    def open_browser():
        time.sleep(1.5)  # Wait for Flask to start
        webbrowser.open(public_url)

    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()

    # Run Flask server with Waitress (production-grade WSGI server)
    from waitress import serve
    print(f"Starting Deep Crawling on {public_url}")
    print("Using Waitress WSGI server with multi-threading support")
    serve(app, host='0.0.0.0', port=port, threads=8)

if __name__ == '__main__':
    main()
