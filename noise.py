"""
Noise alert generator.

This is the important half of the demo. It posts realistic-looking but
operationally meaningless alerts into the same Slack channel your real
alerts land in — the kind every on-call rotation has learned to ignore,
which is exactly why real alerts get ignored too.

Droid's job is to correctly triage these as non-actionable. Yours is to
have them on screen so the audience sees it do that.

Setup:
    Create an incoming webhook for your alert channel:
    https://api.slack.com/messaging/webhooks
    export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

Usage:
    python scripts/noise.py                    # one random noise alert
    python scripts/noise.py --count 4          # a small burst
    python scripts/noise.py --kind disk        # a specific one
    python scripts/noise.py --duplicate 3      # same alert 3x, 20s apart
    python scripts/noise.py --list             # show available kinds
"""

import argparse
import json
import os
import random
import time
import urllib.request
from datetime import datetime, timezone

# Each of these is non-actionable for a specific, defensible reason. If you
# get asked on a call why a given alert is noise, the "why" field is your
# answer — it is also roughly what you want Droid to conclude on its own.
NOISE_ALERTS = {
    "disk": {
        "source": "Datadog",
        "title": "Disk usage above 80% on ci-runner-ephemeral-07",
        "detail": "disk.used_pct = 83.1% (threshold 80%) host:ci-runner-ephemeral-07",
        "why": "Ephemeral CI runner. Scratch volume fills during builds and is "
               "destroyed with the runner. Has never once required action.",
    },
    "latency": {
        "source": "Datadog",
        "title": "p99 latency degraded on /api/internal/heartbeat",
        "detail": "p99 = 812ms (baseline 240ms) service:storefront-api",
        "why": "Internal healthcheck endpoint with a handful of requests per "
               "minute. p99 on tiny sample sizes is statistical noise.",
    },
    "memory": {
        "source": "Datadog",
        "title": "Memory utilization above 85% on storefront-api-canary-2",
        "detail": "mem.used_pct = 87.4% pod:storefront-api-canary-2",
        "why": "JVM-style heap behavior on a canary pod sized for one tenth of "
               "production traffic. Expected steady state.",
    },
    "cert": {
        "source": "Rootly",
        "title": "TLS certificate expiring in 29 days: staging.internal",
        "detail": "cn=staging.internal expires_in=29d",
        "why": "Staging domain, auto-renews at 14 days. Fires every single "
               "month and is never acted on.",
    },
    "deprecation": {
        "source": "Sentry",
        "title": "DeprecationWarning: datetime.utcnow() is deprecated",
        "detail": "storefront-api/app/legacy_report.py:88 — 1,204 events, 1 user",
        "why": "Warning, not an error. High event count from a single hourly "
               "batch job. Real, but not an incident.",
    },
}

DEFAULT_ICONS = {"Datadog": ":dog:", "Sentry": ":ghost:", "Rootly": ":rotating_light:"}


def build_payload(kind, alert):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    icon = DEFAULT_ICONS.get(alert["source"], ":warning:")
    return {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{icon} *[{alert['source']}] {alert['title']}*",
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{alert['detail']}```"},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"triggered {ts}  |  monitor:{kind}-threshold  |  "
                                f"env:production",
                    }
                ],
            },
        ]
    }


def post(webhook, payload):
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=sorted(NOISE_ALERTS), default=None)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--duplicate", type=int, default=0,
                        help="Post the SAME alert this many times, 20s apart. "
                             "Use this to demo duplicate-alert filtering.")
    parser.add_argument("--gap", type=float, default=20.0)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print payloads instead of posting.")
    args = parser.parse_args()

    if args.list:
        for name, alert in NOISE_ALERTS.items():
            print(f"{name:12} [{alert['source']}] {alert['title']}")
            print(f"{'':12} why it is noise: {alert['why']}\n")
        return

    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook and not args.dry_run:
        raise SystemExit("Set SLACK_WEBHOOK_URL, or pass --dry-run.")

    if args.duplicate:
        kind = args.kind or "disk"
        for i in range(args.duplicate):
            payload = build_payload(kind, NOISE_ALERTS[kind])
            if args.dry_run:
                print(json.dumps(payload, indent=2))
            else:
                post(webhook, payload)
                print(f"posted duplicate {i + 1}/{args.duplicate}: {kind}")
            if i + 1 < args.duplicate:
                time.sleep(args.gap)
        return

    kinds = ([args.kind] * args.count if args.kind
             else random.sample(sorted(NOISE_ALERTS),
                                min(args.count, len(NOISE_ALERTS))))
    for kind in kinds:
        payload = build_payload(kind, NOISE_ALERTS[kind])
        if args.dry_run:
            print(json.dumps(payload, indent=2))
        else:
            post(webhook, payload)
            print(f"posted: {kind}")
        time.sleep(1.5)


if __name__ == "__main__":
    main()
