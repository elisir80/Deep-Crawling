# LibreCrawl / SEO Spider parity matrix

This document maps the requested SEO Spider capability set to the local
implementation. It is intentionally evidence-oriented: provider-dependent
features are marked optional rather than represented as locally verified.

| Capability | Local surface | Evidence |
| --- | --- | --- |
| PDF text, metadata and media/SWF | `src/crawler.py`, URL details, export | `tests/test_feature_parity.py`, local HTTP octet-stream test |
| AMP, mobile alternate, rel next/prev, meta refresh, srcset | `SEOExtractor`, URL details | parity unit tests and HTTP end-to-end test |
| Crawl limits | crawler settings and `_should_crawl_url` | depth/subdomain/redirect/link limit checks |
| JavaScript, interactions, Shadow DOM, iframes | Playwright renderer settings | local renderer test with click/shadow/iframe/archive |
| Screenshots and rendered archive | renderer, `/api/rendered-file` | local artifact/path-guard test |
| Headers, cookies, HSTS | crawler result, HTTP Audit and URL details | local HTTP end-to-end test |
| HTML validation and accessibility | extractor, issue detector, URL details | persisted result and regression suite |
| Content area, spelling, grammar, readability, n-grams | `content_analysis.py`, URL details | content-analysis regression test |
| Local semantic search | `/api/analysis/search`, Semantic Search tab | TF-IDF regression test, including persisted nested content |
| Remote embeddings | `/api/analysis/embeddings`, Semantic Search tab | request-scoped provider adapter and API guard |
| Internal link/backlink metrics | `/api/analysis/link-metrics`, Analysis tab | link metrics regression test |
| External backlink providers | `/api/integrations/backlinks` | provider-neutral request adapter; requires endpoint/token |
| Analytics and Search Console | Integrations tab and Google API routes | authenticated API smoke/field validation |
| AI providers | `/api/ai/analyze`, Integrations tab | OpenAI-compatible request adapter; requires provider key |
| Orphans, crawl analysis, change detection, segments | Analysis tab and `/api/analysis/*` | authenticated API smoke and regression suite |
| Search, custom extraction and custom search | settings, URL results, Semantic Search | parser and extraction regression tests |
| URL rewriting and CDN | SEO Utilities tab and `/api/seo/*` | utility regression tests |
| Robots tester | SEO Utilities tab and `/api/seo/robots-test` | pasted-text and live local-server tests |
| XML sitemap and sitemap index | SEO Utilities tab and `/api/seo/sitemap` | XML regression tests |
| JSON/CSV exports and email attachments | Export tab, historical export, email route | export generation and route validation |
| Team sharing and cloud sync | share/revoke routes and Integrations tab | token persistence/revocation and validation tests |
| MCP | `/api/mcp` | authenticated `initialize`, `resources/list`, `tools/list` smoke test |
| Advanced authentication | Basic, Bearer, Cookie, proxy and custom headers | request-session authentication test |
| First-class Spider tab datasets | `/api/crawls/<id>/tabs/<tab>` | returns independently filterable tab rows for internal, response codes, titles, directives, hreflang, JavaScript, structured data, accessibility, validation and other guide tabs |
| Advanced Spider preferences | Settings manager and Advanced settings UI | non-indexable/paginated duplicate handling, canonical/redirect/meta-refresh policy, fragments, 5xx retry and title-width mode are persisted and exposed |

## Verification commands

```bash
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m py_compile main.py src/crawler.py src/core/*.py src/settings_manager.py
git diff --check
```

External Google, AI, embeddings, backlink and cloud services require the
caller to provide an endpoint and credentials. LibreCrawl does not store
those credentials in crawl results.
