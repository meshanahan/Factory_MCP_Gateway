"""
Storefront API — product detail endpoint.

  THE PLANTED BUG
  ---------------
  get_product() caches product records with a short TTL. On a cache miss it
  calls the downstream catalog service. There is no coalescing: if 200
  requests for the same product arrive while the cache is cold, all 200
  independently miss and all 200 hit the backend. That is a thundering herd,
  and it is the single most common cause of "traffic spike took down a
  dependency that was sized correctly for the traffic."

  It is invisible under normal load, because requests trickle in and the
  first one populates the cache before the second arrives. It only surfaces
  when concurrency exceeds backend latency — which is exactly when you are
  least equipped to debug it.

  The fix lives in FIX.md. Do not read it before recording.
"""

import os
import threading
import time

from flask import Flask, jsonify

from . import backend

CACHE_TTL_SECONDS = 30

app = Flask(__name__)

_cache = {}
_cache_lock = threading.Lock()

_request_count = 0
_error_count = 0
_counter_lock = threading.Lock()


# --- Optional Sentry wiring -------------------------------------------------
# If SENTRY_DSN is set, unhandled 5xx responses are reported to Sentry, which
# is what fires the alert into your Slack channel. Without a DSN the app still
# runs and still fails — it just fails quietly, which is fine for local
# rehearsal.
_sentry_enabled = False
if os.environ.get("SENTRY_DSN"):
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration

        sentry_sdk.init(
            dsn=os.environ["SENTRY_DSN"],
            integrations=[FlaskIntegration()],
            traces_sample_rate=1.0,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "demo-production"),
            release=os.environ.get("SENTRY_RELEASE", "storefront-api@1.4.2"),
        )
        _sentry_enabled = True
    except ImportError:
        print("SENTRY_DSN set but sentry-sdk is not installed; "
              "run: pip install sentry-sdk[flask]")


def _get_cached(product_id):
    with _cache_lock:
        entry = _cache.get(product_id)
        if entry and time.monotonic() - entry["stored_at"] < CACHE_TTL_SECONDS:
            return entry["value"]
    return None


def _store_cached(product_id, value):
    with _cache_lock:
        _cache[product_id] = {"value": value, "stored_at": time.monotonic()}


def get_product(product_id):
    """Return a product record, from cache if warm.

    NOTE: the cache lock protects the dict, not the fetch. Two hundred
    concurrent misses will each take the lock, each see nothing, each release
    the lock, and each go to the backend.
    """
    cached = _get_cached(product_id)
    if cached is not None:
        return cached

    record = backend.fetch_product(product_id)
    _store_cached(product_id, record)
    return record


@app.route("/api/product/<product_id>")
def product_detail(product_id):
    global _request_count, _error_count
    with _counter_lock:
        _request_count += 1

    try:
        return jsonify(get_product(product_id))
    except backend.BackendRateLimitError as exc:
        with _counter_lock:
            _error_count += 1
        if _sentry_enabled:
            import sentry_sdk

            sentry_sdk.capture_exception(exc)
        return jsonify({"error": "upstream_unavailable", "detail": str(exc)}), 502


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/metrics")
def metrics():
    """Crude counters so you have a number to put on screen."""
    with _counter_lock:
        requests_total = _request_count
        errors_total = _error_count
    payload = {
        "requests_total": requests_total,
        "errors_total": errors_total,
        "error_rate": round(errors_total / requests_total, 4) if requests_total else 0.0,
        "cache_entries": len(_cache),
    }
    payload.update(backend.stats())
    return jsonify(payload)


@app.route("/admin/reset", methods=["POST"])
def reset():
    """Clear all state between takes."""
    global _request_count, _error_count
    with _cache_lock:
        _cache.clear()
    with _counter_lock:
        _request_count = 0
        _error_count = 0
    backend.reset()
    return jsonify({"status": "reset"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, threaded=True)
