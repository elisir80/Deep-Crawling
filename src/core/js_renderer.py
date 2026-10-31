"""JavaScript rendering handler using Playwright"""
import asyncio
import threading
import hashlib
import os
import json
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from urllib.parse import urlparse


class JavaScriptRenderer:
    """Handles JavaScript rendering for dynamic content using Playwright"""

    def __init__(self, config):
        self.config = config
        self.playwright = None
        self.browser = None
        self.page_pool = []
        self.pool_lock = threading.Lock()

    async def initialize(self):
        """Initialize Playwright browser and page pool"""
        try:
            print("Starting Playwright browser...")
            self.playwright = await async_playwright().start()

            # Choose browser based on configuration
            browser_type = self.config.get('js_browser', 'chromium').lower()
            headless = self.config.get('js_headless', True)

            if browser_type == 'firefox':
                self.browser = await self.playwright.firefox.launch(headless=headless)
            elif browser_type == 'webkit':
                self.browser = await self.playwright.webkit.launch(headless=headless)
            else:  # Default to chromium
                args = ['--no-sandbox', '--disable-dev-shm-usage'] if headless else []
                self.browser = await self.playwright.chromium.launch(headless=headless, args=args)

            # Create page pool
            max_pages = self.config.get('js_max_concurrent_pages', 3)
            for i in range(max_pages):
                context = await self.browser.new_context(
                    user_agent=self.config.get('js_user_agent', 'LibreCrawl/1.0 (Web Crawler with JavaScript)'),
                    viewport={
                        'width': self.config.get('js_viewport_width', 1920),
                        'height': self.config.get('js_viewport_height', 1080)
                    }
                )
                page = await context.new_page()
                page.set_default_timeout(self.config.get('js_timeout', 30) * 1000)
                self.page_pool.append(page)

            print(f"JavaScript rendering initialized with {len(self.page_pool)} browser pages")

        except Exception as e:
            print(f"Failed to initialize JavaScript rendering: {e}")
            await self.cleanup()
            raise

    async def cleanup(self):
        """Clean up Playwright browser and resources"""
        try:
            if self.page_pool:
                for page in self.page_pool:
                    try:
                        await page.context.close()
                    except:
                        pass
                self.page_pool.clear()

            if self.browser:
                await self.browser.close()
                self.browser = None

            if self.playwright:
                await self.playwright.stop()
                self.playwright = None

            print("JavaScript rendering resources cleaned up")

        except Exception as e:
            print(f"Error during JavaScript cleanup: {e}")

    async def get_page(self):
        """Get an available page from the pool"""
        with self.pool_lock:
            if self.page_pool:
                return self.page_pool.pop()
        return None

    async def return_page(self, page):
        """Return a page to the pool"""
        with self.pool_lock:
            self.page_pool.append(page)

    async def render_page(self, url):
        """
        Render a page with JavaScript and return the HTML content

        Returns:
            tuple: (html_content, status_code, error_message, screenshot_path, js_errors, archive_path, diagnostics)
        """
        page = None
        js_errors = []
        archive_path = None
        console_handler = None
        page_error_handler = None
        request_handler = None
        failed_request_handler = None
        diagnostics = {'network': [], 'blocked_requests': [], 'source_html_hash': None, 'dom_html_hash': None, 'hydration_mismatch': False}
        try:
            page = await self.get_page()
            if not page:
                return None, 0, "No JavaScript page available", None, js_errors, archive_path, diagnostics

            def on_console(message):
                if message.type in ('error', 'warning'):
                    js_errors.append({'type': message.type, 'text': message.text})

            def on_page_error(error):
                js_errors.append({'type': 'pageerror', 'text': str(error)})

            def on_request(request):
                if len(diagnostics['network']) < 1000:
                    diagnostics['network'].append({'url': request.url, 'method': request.method, 'resource_type': request.resource_type})

            def on_request_failed(request):
                if len(diagnostics['blocked_requests']) < 1000:
                    diagnostics['blocked_requests'].append({'url': request.url, 'failure': request.failure})

            console_handler = on_console
            page_error_handler = on_page_error
            page.on('console', console_handler)
            page.on('pageerror', page_error_handler)
            request_handler = on_request
            failed_request_handler = on_request_failed
            page.on('request', request_handler)
            page.on('requestfailed', failed_request_handler)

            # Navigate to the page
            try:
                response = await page.goto(
                    url,
                    wait_until='domcontentloaded',
                    timeout=self.config.get('js_timeout', 30) * 1000
                )

                # Wait for JavaScript to render
                await asyncio.sleep(self.config.get('js_wait_time', 3))
                source_html = await page.content()
                diagnostics['source_html_hash'] = hashlib.sha256(source_html.encode('utf-8')).hexdigest()

                # Execute deterministic browser interactions before collecting the DOM.
                # Each action is a dict: {action: click|type|wait, selector, value, timeout}.
                for interaction in self.config.get('js_interactions', []) or []:
                    if not isinstance(interaction, dict):
                        continue
                    action = str(interaction.get('action', '')).lower()
                    selector = interaction.get('selector')
                    timeout = int(interaction.get('timeout', self.config.get('js_timeout', 30) * 1000))
                    if action == 'click' and selector:
                        await page.locator(selector).click(timeout=timeout)
                    elif action == 'type' and selector:
                        await page.locator(selector).fill(str(interaction.get('value', '')), timeout=timeout)
                    elif action == 'wait':
                        await page.wait_for_timeout(max(0, int(interaction.get('milliseconds', interaction.get('value', 500)))))

                custom_script = self.config.get('js_custom_script', '').strip()
                if custom_script:
                    await page.evaluate(custom_script)
                if self.config.get('js_flatten_shadow_dom', False):
                    await page.evaluate("""() => {
                        const walk = (root) => {
                            root.querySelectorAll('*').forEach(node => {
                                if (node.shadowRoot) {
                                    const fragment = document.createDocumentFragment();
                                    [...node.shadowRoot.childNodes].forEach(child => fragment.appendChild(child.cloneNode(true)));
                                    node.replaceWith(...fragment.childNodes);
                                }
                            });
                        }; walk(document);
                    }""")
                if self.config.get('js_flatten_iframes', False):
                    await page.evaluate("""() => {
                        document.querySelectorAll('iframe').forEach(frame => {
                            try {
                                const doc = frame.contentDocument;
                                if (doc && doc.body) frame.replaceWith(...doc.body.childNodes);
                            } catch (e) {}
                        });
                    }""")

                # Get the rendered HTML content
                html_content = await page.content()
                diagnostics['dom_html_hash'] = hashlib.sha256(html_content.encode('utf-8')).hexdigest()
                diagnostics['hydration_mismatch'] = diagnostics['source_html_hash'] != diagnostics['dom_html_hash']
                status_code = response.status if response else 200

                screenshot_path = None
                if self.config.get('js_screenshots', False):
                    screenshot_dir = self.config.get('js_screenshot_dir', 'data/screenshots')
                    os.makedirs(screenshot_dir, exist_ok=True)
                    filename = hashlib.sha256(url.encode('utf-8')).hexdigest()[:24] + '.png'
                    screenshot_path = os.path.join(screenshot_dir, filename)
                    await page.screenshot(path=screenshot_path, full_page=True)

                if self.config.get('js_archive', False):
                    archive_dir = self.config.get('js_archive_dir', 'data/rendered')
                    os.makedirs(archive_dir, exist_ok=True)
                    filename = hashlib.sha256(url.encode('utf-8')).hexdigest()[:24] + '.html'
                    archive_path = os.path.join(archive_dir, filename)
                    with open(archive_path, 'w', encoding='utf-8') as handle:
                        handle.write(html_content)

                return html_content, status_code, None, screenshot_path, js_errors, archive_path, diagnostics

            except PlaywrightTimeoutError:
                return None, 0, "JavaScript rendering timeout", None, js_errors, archive_path, diagnostics
            except Exception as e:
                return None, 0, f"Navigation error: {str(e)}", None, js_errors, archive_path, diagnostics

        except Exception as e:
            return None, 0, f"JavaScript rendering error: {str(e)}", None, js_errors, archive_path, diagnostics

        finally:
            if page:
                if console_handler:
                    page.remove_listener('console', console_handler)
                if page_error_handler:
                    page.remove_listener('pageerror', page_error_handler)
                if request_handler:
                    page.remove_listener('request', request_handler)
                if failed_request_handler:
                    page.remove_listener('requestfailed', failed_request_handler)
                await self.return_page(page)

    def should_use_javascript(self, url):
        """Determine if a URL should use JavaScript rendering"""
        parsed = urlparse(url)
        path = parsed.path.lower()

        # Skip if it's clearly a non-HTML resource
        if path.endswith(('.pdf', '.jpg', '.jpeg', '.png', '.gif', '.css', '.js', '.xml', '.txt', '.zip')):
            return False

        return True
