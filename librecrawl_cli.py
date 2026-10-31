#!/usr/bin/env python3
"""Command-line runner for LibreCrawl.

Examples:
  python librecrawl_cli.py https://example.com
  python librecrawl_cli.py --mode list --seed https://example.com/a --seed https://example.com/b
  python librecrawl_cli.py --mode sitemap --seed https://example.com/sitemap.xml --output report.json
"""
import argparse
import json
import sys
import time

from src.crawler import WebCrawler


def main(argv=None):
    parser = argparse.ArgumentParser(description='LibreCrawl command-line crawler')
    parser.add_argument('url', nargs='?', help='Primary URL or domain')
    parser.add_argument('--mode', choices=('spider', 'list', 'sitemap'), default='spider')
    parser.add_argument('--seed', action='append', default=[], help='Seed URL; repeat for list mode')
    parser.add_argument('--max-urls', type=int, default=1000)
    parser.add_argument('--max-depth', type=int, default=3)
    parser.add_argument('--timeout', type=int, default=10)
    parser.add_argument('--javascript', action='store_true')
    parser.add_argument('--screenshot', action='store_true')
    parser.add_argument('--output', help='Write final JSON report to this path')
    args = parser.parse_args(argv)

    seeds = args.seed
    primary = args.url or (seeds[0] if seeds else None)
    if not primary:
        parser.error('a URL or at least one --seed is required')
    if args.mode != 'spider' and not seeds:
        parser.error('--seed is required for list and sitemap modes')
    if args.mode == 'sitemap' and len(seeds) != 1:
        parser.error('sitemap mode accepts exactly one --seed')

    crawler = WebCrawler()
    crawler.update_config({
        'max_urls': args.max_urls,
        'max_depth': args.max_depth,
        'timeout': args.timeout,
        'enable_javascript': args.javascript,
        'js_screenshots': args.screenshot,
    })
    success, message = crawler.start_crawl(
        primary, crawl_mode=args.mode, seed_urls=seeds or None
    )
    if not success:
        print(message, file=sys.stderr)
        return 1

    while crawler.is_running:
        status = crawler.get_status()
        print(
            f"\rCrawled {status['stats']['crawled']} / "
            f"{status['stats']['discovered']} URLs",
            end='', flush=True
        )
        time.sleep(0.25)
    print()
    report = crawler.get_status()
    report['cli'] = {'mode': args.mode, 'message': message}
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as handle:
            handle.write(encoded + '\n')
        print(f'Report written to {args.output}')
    else:
        print(encoded)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
