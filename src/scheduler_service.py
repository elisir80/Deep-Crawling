"""Execution service for persisted crawl schedules."""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone


def _set_status(schedule_id, status, run_at=None):
    from src.crawl_db import get_db
    with get_db() as conn:
        conn.execute('UPDATE crawl_schedules SET last_status=?, last_run_at=COALESCE(?, last_run_at) WHERE id=?', (status, run_at, schedule_id))


def execute_schedule(schedule, output_dir='reports', project_root=None):
    """Run one schedule in a background thread and return immediately."""
    os.makedirs(output_dir, exist_ok=True)
    root = project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    started = datetime.now(timezone.utc).isoformat()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    output = os.path.join(output_dir, f"schedule-{schedule['id']}-{stamp}.json")
    _set_status(schedule['id'], 'running', started)

    def worker():
        mode = schedule.get('mode', 'spider')
        command = [sys.executable, os.path.join(root, 'librecrawl_cli.py'), schedule['url'], '--mode', mode, '--output', output]
        settings = schedule.get('settings_snapshot') or '{}'
        if isinstance(settings, str):
            try: settings = json.loads(settings)
            except Exception: settings = {}
        if settings.get('max_urls'):
            command.extend(['--max-urls', str(settings['max_urls'])])
        if settings.get('max_depth'):
            command.extend(['--max-depth', str(settings['max_depth'])])
        if settings.get('javascript'):
            command.append('--javascript')
        if settings.get('screenshot'):
            command.append('--screenshot')
        try:
            process = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
            payload = {'schedule_id': schedule['id'], 'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(), 'output': output, 'returncode': process.returncode}
            if process.returncode != 0:
                payload['stderr'] = process.stderr[-2000:]
            recipients = schedule.get('recipients') or '[]'
            if isinstance(recipients, str):
                try: recipients = json.loads(recipients)
                except Exception: recipients = []
            if recipients and os.path.exists(output):
                from src.email_service import send_report_email
                with open(output, encoding='utf-8') as report:
                    text = report.read()
                payload['email'] = []
                for recipient in recipients:
                    sent, message = send_report_email(recipient, f"Deep Crawling: {schedule['name']}", text, os.path.basename(output))
                    payload['email'].append({'to': recipient, 'sent': sent, 'message': message})
            _set_status(schedule['id'], 'completed' if process.returncode == 0 else 'failed')
        except Exception as error:
            payload = {'schedule_id': schedule['id'], 'started_at': started, 'returncode': -1, 'error': str(error)}
            _set_status(schedule['id'], 'failed')
        with open(output + '.status.json', 'w', encoding='utf-8') as status:
            json.dump(payload, status, indent=2, default=str)

    thread = threading.Thread(target=worker, name=f'librecrawl-schedule-{schedule["id"]}', daemon=True)
    thread.start()
    return {'schedule_id': schedule['id'], 'accepted': True, 'status': 'running', 'output': output}


def run_due_schedules_once(output_dir='reports'):
    """Start all due enabled schedules once; safe to call from a polling worker."""
    from src.crawl_db import get_db
    with get_db() as conn:
        schedules = [dict(row) for row in conn.execute("SELECT * FROM crawl_schedules WHERE enabled=1 AND (next_run_at IS NULL OR next_run_at <= datetime('now'))")]
        for schedule in schedules:
            interval = max(1, int(schedule.get('interval_seconds') or 86400))
            conn.execute("UPDATE crawl_schedules SET next_run_at=datetime('now', ?) WHERE id=?", (f'+{interval} seconds', schedule['id']))
    return [execute_schedule(schedule, output_dir) for schedule in schedules]


def start_scheduler_worker(output_dir='reports', poll_seconds=30):
    """Start one daemon poller; returns a stop event and avoids duplicate workers."""
    stop = threading.Event()
    def worker():
        while not stop.is_set():
            try:
                run_due_schedules_once(output_dir)
            except Exception as error:
                print(f'Scheduler worker error: {error}')
            stop.wait(max(1, int(poll_seconds)))
    thread = threading.Thread(target=worker, name='librecrawl-scheduler', daemon=True)
    thread.start()
    return {'thread': thread, 'stop': stop, 'poll_seconds': max(1, int(poll_seconds))}
