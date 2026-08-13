# Swipe Dating — canonical web R&D

A local, synthetic-only FastAPI/Jinja implementation of the canonical Swipe Dating product boundary in `PRODUCT_SCOPE.md`.

The current web experience includes:

- exact fail-closed 18+ entry;
- exactly two permanent tabs: **Swipe** and **Matches**;
- focused profile-card discovery with pass, like, private reporting, and prominent profile/filter controls;
- nested profile and intent/boundary filters with fixed product-controlled ranking weights;
- reciprocal matching only;
- match chat with an initial 20-message limit, a one-time synthetic mutual-extension path, meetup planning, unmatch, block, and report;
- private community bot review with a target panel of seven independent eligible reviewers and a 5-of-7 suspicious supermajority;
- content-blind automated behavior risk as a separate supporting layer;
- temporary discovery containment, subject appeal, synthetic adjudication, and moderation-reputation consequences for wrong votes;
- block behavior that purges visible chat content and suppresses rediscovery.

The UI uses original branding, copy, styling, and synthetic visual placeholders. It follows common high-quality dating-product principles such as a dominant profile, low-friction decisions, compact match inbox, and progressive disclosure without copying another application's protected assets or distinctive trade dress. The governed client surface remains server-rendered Python/Jinja plus CSS; repository governance intentionally rejects JavaScript application surfaces.

Nearby Mode, Match Map/location sharing, and Skin Shop commerce remain feature-gated until the prerequisite acceptance and safety work in `PRODUCT_SCOPE.md` is complete.

It does **not** provide real authentication, identity or age proof, real users, Bluetooth scanning, location collection, network messaging, E2EE, billing, staffed moderation, permanent autonomous bans, or production deployment.

## Quick start

Python 3.12 or 3.13 is required. With [uv](https://docs.astral.sh/uv/):

```bash
uv sync --all-extras
uv run playwright install chromium
uv run swipe-web
```

`swipe-web` starts on `http://127.0.0.1:8080` and opens the default browser. The birth-date wheels start unselected; roll month, day, and year in MM-DD-YYYY order and choose an adult date to enter. The interface loads no remote UI assets or JavaScript framework.

The JSON contract adapter and deterministic simulator remain available separately:

```bash
PORT=8081 uv run swipe-api
uv run swipe-simulate
```

Then visit `http://127.0.0.1:8081/docs` or `http://127.0.0.1:8081/healthz`.

## Verify

```bash
uv run pytest --cov=swipe_dating --cov-branch
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run swipe-governance
SWIPE_WEB_URL=http://127.0.0.1:8081 uv run python scripts/browser_acceptance.py
```

Run the browser command while `SWIPE_WEB_OPEN_BROWSER=0 PORT=8081 uv run swipe-web` is active in another terminal.

See `docs/BASELINE.md`, `docs/PARITY_MATRIX.md`, `docs/PRODUCTION_GAPS.md`, and `docs/specs/current-objective.md` for scope and limitations.

## Release state

```text
PYTHON_RND_SYNTHETIC_ONLY
REAL_USER_CLOSED_BETA_BLOCKED
PRODUCTION_BLOCKED_HUMAN_APPROVALS_REQUIRED
```
