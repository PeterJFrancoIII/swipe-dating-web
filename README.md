# Swipe Dating — Product-reset Python R&D

A local, synthetic-only Python web app for the hard product reset: exact 18+ gating, a two-tab
**Swipe + Matches** shell, nested community bot review, and reciprocal matching. Deepen Connection,
progressive reveal, ranking-weight editors, and forced openers are deleted.

The bot-control prototype includes:

- reports from any adult-gated synthetic user;
- voting restricted to verified, long-standing, good-standing synthetic reviewers;
- three independent trust clusters and a two-thirds suspicious quorum;
- content-blind automated behavior risk as a separate second layer;
- temporary discovery containment, subject appeal, and synthetic adjudication;
- moderation-reputation penalties for wrong votes, never dating-visibility penalties.

It does **not** provide real authentication, age assurance, users, Bluetooth scanning, location
collection, network messaging, E2EE, billing, staffed moderation, permanent autonomous bans, or
production deployment.

## Quick start

Python 3.12 or 3.13 is required. With [uv](https://docs.astral.sh/uv/):

```bash
uv sync --all-extras
uv run playwright install chromium
uv run swipe-web
```

`swipe-web` starts on `http://127.0.0.1:8080` and opens the default Mac browser. The birth-date
field starts blank; deliberately choose an adult date to enter. The active interface uses a
warm, light, system-font design with keyboard navigation and responsive layouts; it loads no
remote UI assets or JavaScript framework.

The original JSON contract adapter and deterministic simulator remain available separately:

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

Run the browser command while `SWIPE_WEB_OPEN_BROWSER=0 PORT=8081 uv run swipe-web` is active in
another terminal.

See [docs/BASELINE.md](docs/BASELINE.md), [docs/PARITY_MATRIX.md](docs/PARITY_MATRIX.md), and [docs/PRODUCTION_GAPS.md](docs/PRODUCTION_GAPS.md) for scope and limitations.

## Release state

```text
PYTHON_RND_SYNTHETIC_ONLY
REAL_USER_CLOSED_BETA_BLOCKED
PRODUCTION_BLOCKED_HUMAN_APPROVALS_REQUIRED
```
