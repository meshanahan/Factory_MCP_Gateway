"""
Simulated downstream dependency: a product catalog service.

This stands in for whatever real backend sits behind your API — a database,
an internal microservice, a third-party vendor API. The only thing that
matters for the demo is that it has a concurrency ceiling and fails loudly
when you exceed it, exactly like a real dependency with a connection pool
or a rate limit.
"""

import threading
import time

# Requests per second this dependency will tolerate before it starts
# rejecting. Lower this if you want the incident to fire more aggressively
# on camera.
RATE_LIMIT_RPS = 20

# How long a "real" backend call takes. Keeps the window open long enough
# for concurrent requests to pile up on a cache miss.
LATENCY_SECONDS = 1.5


class BackendRateLimitError(Exception):
    """Raised when the downstream dependency sheds load."""


class _RateLimiter:
    def __init__(self, limit_per_second):
        self.limit = limit_per_second
        self._lock = threading.Lock()
        self._window_start = time.monotonic()
        self._count = 0
        self.total_calls = 0
        self.total_rejected = 0

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            if now - self._window_start >= 1.0:
                self._window_start = now
                self._count = 0
            self._count += 1
            self.total_calls += 1
            if self._count > self.limit:
                self.total_rejected += 1
                return False
            return True

    def stats(self):
        with self._lock:
            return {
                "backend_calls_total": self.total_calls,
                "backend_calls_rejected": self.total_rejected,
            }

    def reset(self):
        with self._lock:
            self._window_start = time.monotonic()
            self._count = 0
            self.total_calls = 0
            self.total_rejected = 0


_limiter = _RateLimiter(RATE_LIMIT_RPS)


def fetch_product(product_id):
    """Fetch a product record from the downstream catalog service."""
    if not _limiter.acquire():
        raise BackendRateLimitError(
            f"catalog-service rejected request for product {product_id}: "
            f"rate limit of {RATE_LIMIT_RPS} req/s exceeded"
        )
    time.sleep(LATENCY_SECONDS)
    return {
        "id": product_id,
        "name": f"Product {product_id}",
        "price_cents": 1999,
        "in_stock": True,
    }


def stats():
    return _limiter.stats()


def reset():
    _limiter.reset()
