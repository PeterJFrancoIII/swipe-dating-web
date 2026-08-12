# Current objective — canonical web application build

**Status:** ACTIVE — synthetic-only web implementation  
**Real users:** Prohibited  
**Canonical scope:** repository `PRODUCT_SCOPE.md`  
**Updated:** 2026-08-12

## Mission

Build the complete web expression of the canonical Swipe Dating product while preserving its hard boundaries. The active client is FastAPI + Jinja (`uv run swipe-web`). Native iOS and Android are not part of the product.

## Experience target

Deliver a focused, contemporary dating experience built around one dominant profile at a time and exactly two permanent tabs:

1. **Swipe** — full profile card, pass, like, private report, nested profile and filters.
2. **Matches** — reciprocal matches, chat, meetup planning, unmatch, block, and report.

Borrow proven interaction principles from leading dating products—fast comprehension, strong profile imagery, low-friction decisions, compact match inboxes, responsive mobile ergonomics—without copying another product's protected brand, assets, copy, or distinctive trade dress.

## Canonical behavior in this build

- exact 18+ fail-closed gate;
- mutual matching only;
- fixed product-controlled ranking weights;
- no progressive profile reveal, ranking editor, forced opener, relationship phase, social feed, streak, or popularity mechanic;
- private bot reports with an optional short evidence note;
- independent trusted-community review using a seven-reviewer target panel and 5-of-7 suspicious supermajority for community containment;
- automation remains a separate supporting risk layer;
- 20-message initial chat limit, one synthetic mutual-extension path, persistent meetup planning, unmatch and block;
- block purges visible conversation content and suppresses rediscovery;
- Profile, Filters, Community Review, and Chat remain nested rather than permanent tabs.

## Feature flags still closed

The following canonical features remain intentionally disabled until their prerequisite acceptance gates are satisfied:

- Get fk’d / Nearby Mode;
- Match Map and match-scoped location sharing;
- Skin Shop commerce.

Domain prototypes may exist, but the user-facing feature must not claim readiness or collect real proximity/location/payment data.

## Evidence required

- unit, property, contract, integration, smoke, and governance tests;
- Ruff lint and format checks;
- strict mypy;
- deterministic simulation;
- browser acceptance where supported;
- GitHub review before merge.

## Release boundary

```text
PYTHON_RND_SYNTHETIC_ONLY
REAL_USER_CLOSED_BETA_BLOCKED
PRODUCTION_BLOCKED_HUMAN_APPROVALS_REQUIRED
```

A polished interface is not authorization for real users or production deployment.
