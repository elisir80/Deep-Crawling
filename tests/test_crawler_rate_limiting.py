import unittest
from unittest.mock import Mock

from src.core.rate_limiter import RateLimiter
from src.crawler import WebCrawler


class CrawlerRateLimitingTests(unittest.TestCase):
    def test_rate_limiter_defer_sets_shared_cooldown(self):
        limiter = RateLimiter(1.0)
        with unittest.mock.patch('src.core.rate_limiter.time.time', return_value=100.0):
            limiter.defer(15)
        self.assertEqual(limiter.blocked_until, 115.0)

    def test_429_without_retry_after_uses_exponential_cooldown(self):
        crawler = WebCrawler()
        crawler.rate_limiter = Mock()
        response = Mock(headers={})

        crawler._defer_after_rate_limit(response, 2)

        crawler.rate_limiter.defer.assert_called_once_with(40)

    def test_429_honors_retry_after_header(self):
        crawler = WebCrawler()
        crawler.rate_limiter = Mock()
        response = Mock(headers={'retry-after': '25'})

        crawler._defer_after_rate_limit(response, 0)

        crawler.rate_limiter.defer.assert_called_once_with(25.0)


if __name__ == '__main__':
    unittest.main()
