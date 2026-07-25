# Mission

**Status:** ACTIVE — product reset (PR 1+)  
**Updated:** 2026-07-24  
**Legal status of policy drafts:** UNAPPROVED until counsel and named owners sign artifacts in `approvals/`  
**Canonical product boundary:** `PRODUCT_SCOPE.md` (overrides conflicting product docs)

## User objective

Build an adults-only swipe dating app that ranks compatible people, gets matches offline quickly, and uses trusted community members plus automation to remove bots.

Design for adults ages **18–25**. Minimum account age is **18**. People 16–17 must never participate. Sexual-intent modes, proximity, messaging, and offline meetups make a lower age floor unacceptable.

## Current objective

Build the **web app only** per `PRODUCT_SCOPE.md`. Native iOS and Android are removed and must not be rebuilt.

Continue the hard product reset:

1. Keep product scope locked; web is the only active client.
2. Keep Deepen Connection / relationship phases, progressive reveal, and ranking editors deleted.
3. Keep permanent navigation at **Swipe** and **Matches** only.
4. Advance the synthetic Python web R&D app (`uv run swipe-web`) through later PRs.
5. Leave closed beta and production blocked until release gates and authentic approvals exist.

Do not add Get fk’d, Match Map, Skin Shop, or expanded chat behavior until Swipe and community bot control pass their acceptance tests (later PRs).

## Success criteria

### Product reset (near-term)

- [ ] `PRODUCT_SCOPE.md` is the canonical product boundary
- [ ] Only two permanent tabs: Swipe and Matches
- [ ] App opens onto a full-screen swipe card without configuration gates
- [ ] Deepen Connection / relationship phases are completely gone
- [ ] Progressive profile reveal and ranking-weight editors are gone
- [ ] Forced shared-ground openers are gone from the swipe path
- [ ] Report suspected bot remains ≤3 taps on the card
- [ ] Community review is not a permanent tab for ordinary users
- [ ] Adults 18+ only; fail closed when age eligibility cannot be established
- [ ] Privacy defaults are identical for every gender

### Later PRs (tracked, not this slice)

- [ ] Mutual swipe matching with alignment ranking of eligible adults
- [ ] Private community bot review with weighted supermajority + automation
- [ ] Limited chat that points toward meetup or mutual extension
- [ ] Opt-in proximity and match location, off by default
- [ ] Skin Shop cosmetics isolated from dating reach and moderation power

### Governance / release

- [ ] Release gates deny beta/production without named approvals
- [ ] `make production-preflight` fails closed without authentic approvals
- [ ] No fabricated legal, security, trust-and-safety, store, or executive approvals
- [ ] Staging only for autonomous agents; never production deploy or store submission

## Non-goals

- Deepen Connection, relationship coaching, or progressive bio-first reveal
- User-editable ranking algorithms
- Social feeds, Stories, streaks, popularity scores, public follower counts
- Public downvote / hot-or-not voting of people
- Gender-based forced disclosure or weaker privacy defaults for any gender
- Minors or parental-consent bypass of the 18+ floor
- Race, ethnicity, skin-color, or height filters
- Inferred intelligence, attractiveness, hygiene, or sexuality scoring
- Pay-to-win dating reach or paid moderation power
- Sale or behavioral advertising of dating, sexuality, location, message, or photo data
- Claiming decentralization removes legal or safety duties
- Autonomous production deploy, store submission, legal filing, or fabricated approval

## Constraints

| Area | Constraint |
|---|---|
| Product | `PRODUCT_SCOPE.md` is authoritative |
| Client | Web only; `apps/ios`, `apps/android`, and `apps/` must not exist |
| Age | Adults 18+ only; 18–25 design audience; never 16–17 |
| Privacy | Equal defaults across genders; location/proximity off by default |
| Navigation | Two permanent tabs only; sheets for everything else |
| Ranking | Alignment ranks eligible people; no user-tuned weights |
| Bot control | Private community review + automation; no public attractiveness voting |
| Safety | Block, report, age, encryption, basic discovery never paywalled |
| Deployment | Staging only for agents; beta/production human-gated |
| Active R&D surface | Synthetic Python web app under `GPT_Workspace_Documents/swipe-dating-python-rnd-rebuild/` |

## Source of truth

- Product scope: `PRODUCT_SCOPE.md`
- Current specification: `docs/specs/current-objective.md`
- Python R&D app: `GPT_Workspace_Documents/swipe-dating-python-rnd-rebuild/`
- Governance: `docs/governance/`
- Release gates: `docs/governance/release-gates.md` + `approvals/`
- Community rules: `policies/community-rules.md`

## Red-zone areas

Auth, adult assurance, proximity permissions, location sharing, sensitive questionnaire data, payments/creator payouts, funding claims, secrets, production infrastructure, customer data, migrations, safety evidence vault, child-safety reporting, NCII operations, and store submission require **explicit human approval**.
