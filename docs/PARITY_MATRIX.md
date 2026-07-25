# Parity matrix (post product-reset PR 1)

The JavaScript research packages are no longer the active product surface. This matrix tracks the
Python R&D modules that remain after deleting Deepen Connection and collapsing navigation.

| Concern | Python module | Status |
|---|---|---|
| Adult gate | `domain/adult.py` | Active |
| Alignment scoring | `domain/alignment.py` | Domain retained; UI deferred |
| Preferences | `domain/preferences.py` | Domain retained; sheet deferred |
| Discovery ranking | `domain/discovery.py` | Fixed weights only; no progressive reveal |
| Matching / conversations | `domain/conversations.py` | Reciprocal match; no forced openers |
| Bot moderation | `domain/bot_moderation.py` | Nested community review surface |
| Automated risk | `domain/risk.py` | Second layer |
| Local state allowlist | `domain/local_state.py` | Swipe tab only persisted |
| Proximity / location / skins | domain modules | Feature-flagged / deferred UI |
| Deepen Connection | deleted | Forbidden by governance |

Verification uses unit, property, golden-vector, API contract, governance, web integration, and
browser acceptance tests.
