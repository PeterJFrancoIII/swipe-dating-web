# Architecture

The project uses a domain-first hexagonal layout:

```text
FastAPI + Jinja web ─┐
JSON API adapter ────┼─> application session ─> pure domain transitions
simulator ───────────┘             │
                                   ├─> synthetic bot moderation
                                   ├─> content-blind risk assessment
                                   ├─> in-memory rendezvous adapter
                                   ├─> strict local-state repository
                                   └─> synthetic HMAC identifier adapter
```

Domain modules never import FastAPI, Jinja, the file system, or environment variables. External
wire validation uses Pydantic; domain state uses frozen dataclasses, enums, tuples, and copied
mappings. Clocks and timestamps are passed explicitly for deterministic tests.

The web adapter creates one `ResearchSession` per random, HTTP-only browser cookie. Sessions,
birth dates, dating decisions, reports, votes, risk results, and moderation cases remain in process
memory. The cookie is only an opaque lookup key. Nothing in this layer is real authentication.

Bot moderation is deliberately separate from dating rank:

```text
adult report
    ├─> trusted independent community votes ─> temporary containment
    └─> technical behavior signals ─────────> risk ladder / containment
                                              │
                                              └─> appeal + synthetic adjudication
```

Review cases expose a sanitized synthetic profile summary and risk reason labels only. They never
include messages, exact location, questionnaire answers, identity documents, or private evidence.
Wrong synthetic votes reduce moderation reputation; that reputation never enters discovery rank.

The adapters are research surfaces, not trust boundaries. All reciprocal activity, reviewers,
votes, risk signals, and adjudication truth are deterministic fixtures. No adapter collects real
location, scans Bluetooth, sends messages over a network, authenticates a person, or persists
sensitive dating or moderation state.
