# Mission — Python R&D

**Status:** ACTIVE — product reset PR 1 / synthetic users only  
**Updated:** 2026-07-24  
**Canonical product boundary:** repository root `PRODUCT_SCOPE.md`  
**Public or production approval:** Not granted

Deliver a synthetic-only Python web app for the reset product:

> Adults-only swipe that ranks compatible people, gets matches offline quickly, and uses trusted community members plus automation to remove bots.

## Non-negotiable boundaries

- adults 18+ only, with exact calendar-date behavior;
- only two permanent tabs: Swipe and Matches;
- no Deepen Connection / relationship phases;
- no progressive profile reveal;
- no user-adjustable ranking weights;
- no forced shared-ground openers on swipe;
- no unilateral match;
- no automatic message, proximity participation, or location grant;
- no protected, inferred, popularity, or purchase ranking input;
- no sensitive dating state in the unencrypted local R&D store;
- block purges visible content and suppresses rediscovery;
- every simulated credential, reciprocal action, message, proximity event, and location choice is labeled synthetic;
- no claim of authentication, identity proof, encryption, delivery, moderation, billing, safety guarantee, or production readiness;
- no real users, real secrets, identity documents, intimate media, safety evidence, Bluetooth collection, or location collection.

## Success criteria (PR 1)

- age gate → swipe card → pass / like / report bot without configuration panels;
- Matches tab for reciprocal outcomes;
- community review reachable as a nested moderator surface, not a third primary tab;
- Deepen Connection code and docs absent;
- deterministic tests, type checks, lint, simulation, governance checks, and CI pass;
- beta and production remain blocked.

## Release state

```text
PYTHON_RND_SYNTHETIC_ONLY
REAL_USER_CLOSED_BETA_BLOCKED
PRODUCTION_BLOCKED_HUMAN_APPROVALS_REQUIRED
```
