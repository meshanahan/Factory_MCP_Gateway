# Storefront API — incident demo environment

A deliberately broken service for recording an autonomous incident-response
demo. It produces a real, non-staged production failure: a traffic spike
causes cache stampede, the downstream dependency sheds load, and error rate
goes to ~88%.

Nothing here is faked. The spike is real load, the failure is a real
concurrency bug, and the fix is a real fix. That matters, because the whole
credibility of the video rests on the agent solving something it wasn't
handed the answer to.

## What's in here

```
app/api.py        Storefront API. Contains the planted bug.
app/backend.py    Downstream catalog service. Rate-limited, sheds load.
scripts/spike.py  Traffic spike generator. Causes the incident.
scripts/noise.py  Noise alert generator. The triage beat.
FIX.md            Root cause + fix. DO NOT READ BEFORE RECORDING.
```

## Verified behavior

```
$ python scripts/spike.py --concurrency 200
wave 1: 200 requests in 3.5s  200=24  502=176  other=0

$ curl -s localhost:8000/metrics
{"backend_calls_total": 200,     <- should be 1
 "backend_calls_rejected": 176,
 "error_rate": 0.88}
```

After the fix: `backend_calls_total: 1`, `error_rate: 0.0`. Same spike.

## Setup

### 1. Local service

```bash
pip install flask
python -m app.api          # serves on 127.0.0.1:8000
```

Confirm it works before anything else:

```bash
curl localhost:8000/healthz
python scripts/spike.py --concurrency 200
```

You should see roughly 170–180 502s. If you see zero, your machine is
serializing the requests — raise `--concurrency` to 400, or raise
`LATENCY_SECONDS` in `app/backend.py` to widen the cold-cache window.

### 2. Sentry

Free tier is enough. Create a Python project, copy the DSN.

```bash
pip install "sentry-sdk[flask]"
export SENTRY_DSN="https://...ingest.sentry.io/..."
export SENTRY_ENVIRONMENT="demo-production"
python -m app.api
```

Then in Sentry: **Alerts → Create Alert → Issues**, condition
"an issue is seen more than 50 times in one minute", action: send to your
Slack channel. This is what puts a real alert in front of Droid.

### 3. Slack

Create a throwaway workspace — do not do this in a workspace you care about.
Create `#alerts-production`.

- Connect Sentry to it via the Sentry Slack integration.
- Create an incoming webhook for the noise generator:
  https://api.slack.com/messaging/webhooks

```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
python scripts/noise.py --list        # see the noise catalog
python scripts/noise.py --count 3     # post a burst
```

### 4. Factory

Pro tier, $20/month — there is no free tier. Connect the repo, connect Slack,
point Incident Response at `#alerts-production`.

Push this repo to a private GitHub repo first. **Exclude `FIX.md`** — if
Droid indexes the answer, the demo is worthless and anyone technical
watching will be able to tell.

```bash
echo "FIX.md" >> .gitignore
```

## Running a take

```bash
# 1. reset all state
curl -X POST localhost:8000/admin/reset

# 2. seed the channel with noise, 2-3 minutes before you start
python scripts/noise.py --count 3
python scripts/noise.py --kind cert --duplicate 3

# 3. roll camera, then fire the incident
python scripts/spike.py --concurrency 200 --waves 3
```

Three waves keeps the error rate elevated long enough for Sentry to trip its
threshold and for Droid to have live signal while it investigates. A single
wave often resolves before the alert even fires.

## Recording notes

- **Do four to six takes.** Agent runs vary. You want to cut from the best
  one, not the only one.
- **Keep every take**, including failures. If Droid gets something wrong and
  you correct it in-thread, that is often better footage than a clean run —
  it shows the workflow rather than a magic trick.
- **Watch your Slack sidebar and browser tabs.** Blur anything identifying
  before you send footage to an editor.
- **Do not narrate while the agent works.** Let it run silently, then cut.
  Voiceover goes on in post.
