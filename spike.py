"""
Traffic spike generator — this is what causes the incident.

Fires N concurrent requests for the SAME product id against a cold cache.
Every one of them misses, every one of them hits the downstream catalog
service, the service sheds load, and your error rate goes vertical.

Usage:
    python scripts/spike.py                      # default: 200 concurrent
    python scripts/spike.py --concurrency 400
    python scripts/spike.py --product SKU-9931 --waves 3
"""

import argparse
import concurrent.futures
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8000"


def hit(base, product_id):
    url = f"{base}/api/product/{product_id}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


def wave(base, product_id, concurrency):
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(hit, base, product_id) for _ in range(concurrency)]
        return [f.result() for f in futures]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--product", default="SKU-4417")
    parser.add_argument("--concurrency", type=int, default=200)
    parser.add_argument("--waves", type=int, default=1)
    parser.add_argument(
        "--gap",
        type=float,
        default=35.0,
        help="Seconds between waves. Keep above the cache TTL so each wave "
             "hits a cold cache.",
    )
    args = parser.parse_args()

    for n in range(args.waves):
        started = time.monotonic()
        codes = wave(args.base, args.product, args.concurrency)
        elapsed = time.monotonic() - started
        ok = sum(1 for c in codes if c == 200)
        bad = sum(1 for c in codes if c == 502)
        other = len(codes) - ok - bad
        print(
            f"wave {n + 1}: {len(codes)} requests in {elapsed:.1f}s  "
            f"200={ok}  502={bad}  other={other}"
        )
        if n + 1 < args.waves:
            time.sleep(args.gap)


if __name__ == "__main__":
    main()
