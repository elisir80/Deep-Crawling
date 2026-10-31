"""Machine-readable parity catalogue for the Screaming Frog guide audit."""

PARITY_CATALOG = {
    'general': {'crawl': '/api/start_crawl', 'save_import_export': '/api/projects', 'scheduling': '/api/schedules', 'auto_updates': '/api/app/update', 'robots': '/api/seo/robots-test', 'sitemap': '/api/seo/sitemap', 'visualisations': '/api/visualization_data'},
    'crawl_options': {'images_media_css_javascript': 'src/crawler.py', 'links_canonicals_hreflang_pagination': 'src/core/seo_extractor.py', 'limits': 'src/crawler.py', 'rendering': 'src/core/js_renderer.py'},
    'advanced': {'cookies_auth_sessions': 'src/crawler.py', 'proxy_trusted_certificates': 'src/settings_manager.py', 'storage_retention': '/api/projects/retention', 'custom_search_extraction': '/api/crawls/<id>/custom-audit', 'html_validation': '/api/parity/html-validation', 'mcp': '/api/mcp'},
    'integrations': {'ga4': '/api/integrations/analytics', 'search_console': '/api/integrations/search-console', 'pagespeed': '/api/integrations/pagespeed', 'majestic': '/api/integrations/backlinks', 'ahrefs': '/api/integrations/backlinks', 'moz': '/api/integrations/backlinks'},
    'tabs_and_exports': {'top_tabs': 'web/templates/index.html', 'native_tab_datasets': '/api/crawls/<id>/tabs/<tab>', 'lower_panels': '/api/crawls/<id>/panels', 'named_panel_datasets': '/api/crawls/<id>/panels?panel=<panel>', 'dataset_exports': '/api/crawls/<id>/export', 'crawl_analysis': '/api/seo/dashboard', 'segments': '/api/analysis/segment'},
}

def parity_catalog():
    return {'catalog': PARITY_CATALOG, 'feature_count': sum(len(group) for group in PARITY_CATALOG.values()), 'source': 'Screaming Frog SEO Spider User Guide', 'groups': {name: {'status': 'implemented', 'feature_count': len(group)} for name, group in PARITY_CATALOG.items()}}
