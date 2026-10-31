#!/usr/bin/env python3
"""Small dependency-free scheduler for recurring LibreCrawl CLI jobs."""
import argparse
import json
import os
import subprocess
import time
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen


def notify(webhook, payload):
    if not webhook:
        return
    body = json.dumps(payload).encode('utf-8')
    request = Request(webhook, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=15):
        pass


def main():
    parser = argparse.ArgumentParser(description='Run a recurring LibreCrawl crawl')
    parser.add_argument('url')
    parser.add_argument('--interval', type=int, default=86400, help='Seconds between runs')
    parser.add_argument('--mode', choices=('spider', 'list', 'sitemap'), default='spider')
    parser.add_argument('--output-dir', default='reports')
    parser.add_argument('--webhook', help='POST completion JSON to this URL')
    parser.add_argument('--email', action='append', default=[], help='Email recipient; repeat for multiple recipients')
    parser.add_argument('--subject', default='LibreCrawl scheduled crawl')
    parser.add_argument('--once', action='store_true', help='Run once and exit')
    args = parser.parse_args()
    if args.interval < 1:
        parser.error('--interval must be positive')
    os.makedirs(args.output_dir, exist_ok=True)

    while True:
        started = datetime.now(timezone.utc).isoformat()
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        output = f'{args.output_dir}/crawl-{stamp}.json'
        command = [sys.executable, 'librecrawl_cli.py', args.url, '--mode', args.mode, '--output', output]
        process = subprocess.run(command, check=False)
        payload = {'started_at': started, 'output': output, 'returncode': process.returncode}
        if args.email:
            try:
                from src.email_service import send_report_email
                with open(output, encoding='utf-8') as report_file:
                    report_text = report_file.read()
                for recipient in args.email:
                    sent, message = send_report_email(recipient, args.subject, report_text, os.path.basename(output))
                    payload.setdefault('email', []).append({'to': recipient, 'sent': sent, 'message': message})
            except Exception as error:
                payload['email_error'] = str(error)
        try:
            notify(args.webhook, payload)
        except Exception as error:
            print(f'Notification failed: {error}')
        if process.returncode != 0:
            print(f'Crawl failed: {payload}')
        if args.once:
            return 0
        print(f'Next crawl in {args.interval} seconds')
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
