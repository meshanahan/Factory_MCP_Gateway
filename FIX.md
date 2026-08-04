# The fix (do not read before recording)

Keep this file out of the repo Droid indexes if you want a clean run. It is
here so you know where the demo lands, and so you can verify the environment
before you shoot.

## Root cause

`app/api.py :: get_product()` has no request coalescing. The cache lock
protects the dictionary, not the fetch. Under concurrency, N simultaneous
misses for the same key produce N backend calls:

```
200 concurrent requests  ->  200 cache misses  ->  200 backend calls
                                                    ^ should be 1
```

The downstream catalog service is sized correctly for the actual traffic.
It is not sized for 200x amplification of that traffic. It sheds load, the
API returns 502, and the error rate goes to ~88%.

This is a thundering herd (also called cache stampede or dogpile). It is
invisible at low traffic because requests arrive far enough apart that the
first one warms the cache before the second arrives. It only appears when
request concurrency exceeds backend latency — which is precisely during the
traffic spike you were least prepared to debug.

## The fix: single-flight

One in-flight fetch per key. Everyone else waits on that fetch and shares
its result.

```python
_inflight = {}
_inflight_lock = threading.Lock()


def get_product(product_id):
    cached = _get_cached(product_id)
    if cached is not None:
        return cached

    with _inflight_lock:
        event = _inflight.get(product_id)
        leader = event is None
        if leader:
            event = threading.Event()
            _inflight[product_id] = event

    if not leader:
        # Someone else is already fetching this key. Wait for them.
        event.wait(timeout=10)
        cached = _get_cached(product_id)
        if cached is not None:
            return cached
        # Leader failed; fall through and try once ourselves.

    try:
        record = backend.fetch_product(product_id)
        _store_cached(product_id, record)
        return record
    finally:
        with _inflight_lock:
            _inflight.pop(product_id, None)
        event.set()
```

## Verified result

| | backend calls | 502s | error rate |
|---|---|---|---|
| before | 200 | 176 | 88% |
| after | 1 | 0 | 0% |

Same 200-request spike, same backend, same rate limit. One line of
architecture.

## What a good RCA should also mention

If Droid produces these unprompted, say so on camera — it is the difference
between a summarizer and something that actually understands the system:

- **The cache TTL is a cliff.** Every 30 seconds the key expires and the herd
  can re-form. Single-flight fixes the stampede; stale-while-revalidate would
  also remove the cliff.
- **There is no backpressure.** The API has no circuit breaker on the
  downstream. When the catalog service starts rejecting, the API keeps
  hammering it.
- **The alert fired on symptom, not cause.** The monitor watches API error
  rate. Nothing watches backend call amplification, which is the actual
  leading indicator. This is the "coverage gap" point in your closing beat.
