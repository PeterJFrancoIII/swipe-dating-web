# Product scope (canonical)

**Status:** ACTIVE — overrides conflicting product docs  
**Updated:** 2026-07-24  
**Audience:** adults 18+; visual and product design emphasis on ages **18–25**  
**Minimum account age:** **18** (16–17 is never an access path)  
**Active client:** **Web only** (Python FastAPI/Jinja R&D under `GPT_Workspace_Documents/swipe-dating-python-rnd-rebuild/`)

This document is the product boundary for Swipe Dating. If another product brief, ADR interpretation, research note, or UI sketch conflicts with this file, **this file wins** until a deliberate product decision updates it.

Native mobile clients are **out of scope and removed**. Do not recreate `apps/ios`, `apps/android`, or an `apps/` mobile tree unless a later product decision adds them back to this document.

## One-sentence product

> An adults-only swipe app that ranks compatible people, gets matches offline quickly, and uses trusted community members plus automation to remove bots.

Anything that does not directly support that sentence must be deleted, consolidated behind a sheet, deferred behind a feature flag, or rejected.

## Permitted user-facing areas

| Area | Role |
|---|---|
| Swipe and matching | Primary loop: full-screen card, pass, like, mutual match |
| Community bot detection | Private report → trusted review → containment / challenge / remove |
| Profiles and preferences | Nested sheet: photos, bio, identity, verification, account |
| Alignment scoring | Curated questionnaire ranks eligible people; no user-tuned weights |
| Looking For modes | Curated intent list; private until mutual compatibility |
| Matches, limited messaging, meetup planning | Match list, chat, meetup CTA, unmatch / block / report |
| Get fk’d proximity mode | Toggle on Swipe; off by default; store-facing label may be Nearby Mode |
| Opt-in match location | From Matches only; per-match consent; expiring shares |
| Skin Shop cosmetics | From Profile sheet; never affects rank, match, moderation, or safety |

Required infrastructure (authentication, age assurance, payments, blocking, appeals, logging, security) is allowed. It must not become additional product surface or permanent tabs.

## Primary navigation (hard limit)

Exactly **two permanent tabs**:

1. **Swipe** — app opens here on a full-screen profile card.
2. **Matches** — match list, unread state, chat, meetup CTA, location-sharing prompt, match-map entry.

**Chat** is the only normal nested full screen. Everything else is a sheet or nested view:

- Profile sheet
- Filters sheet
- Alignment sheet
- Skin Shop sheet
- Community review sheet (eligible moderators only)
- Match map sheet (from Matches)

## Swipe card contents (allowed)

- Current profile card
- Alignment percentage (plus at most one or two useful agreement areas)
- Looking For intent
- Approximate distance
- A few self-declared lifestyle or grooming traits
- Pass / Like
- Report suspected bot
- Top bar: Get fk’d toggle, Filters, Profile/avatar

## Explicitly prohibited

- Native iOS / Android / store client work (web is the only active client)
- “Deepen Connection” / relationship phases
- Bio-first or progressive profile reveal
- User-adjustable ranking algorithms or weight editors
- Forced conversation starters / mandatory shared-ground openers
- Social feeds, Stories, popularity scores, public follower counts
- Streaks or daily engagement mechanics
- Separate safety dashboards for ordinary users
- Relationship coaching or compatibility essays
- Public downvote / hot-or-not voting of people
- Race, ethnicity, skin-color, or height filters
- Inferred intelligence, attractiveness, hygiene, or sexuality scoring
- Gender-based privacy defaults (including proximity disclosure)
- Pay-to-win dating reach or paid moderation power
- Any new feature not added here through a deliberate product decision

## Adults only and age assurance

- Design audience and visual style: **18–25**
- Minimum account age: **18**
- Age assurance must be stronger than typing a birthday alone for real-user builds
- No visibility, matching, messaging, proximity, marketplace, or sexual-intent access until adult verification succeeds
- Fail closed when adult eligibility cannot be established

## Privacy defaults (gender-neutral)

Every adult gets the same proximity / profile-share choices:

1. **Ask before sharing** — recommended default
2. **Auto-share with compatible nearby users**
3. **Never share**

Do not infer consent from gender. Gender feed preferences remain private. Location and proximity remain off by default.

## Community bot control (private moderation)

- Report from every profile card and conversation (≤3 taps)
- Reasons: suspected bot, scam, impersonation, stolen photos, spam links, other abuse
- Optional short evidence note + immediate personal block
- Moderator eligibility: account age ≥90 days, adult + identity verification passed, low automated bot-risk, no active/recent serious enforcement, normal usage history, accepted moderator rules, privileges not revoked
- Eligibility must not depend on attractiveness, match count, spend, or popularity
- Review queue: random eligible reviewers (target seven), exclude people who matched / messaged / blocked / interacted; private identities; no public vote counts
- Layered outcomes: monitor → rate-limit + verification challenge → temporary discovery removal → suspend on strong agreement → remove after failed challenge / rejected appeal
- Supermajority required (e.g. 5 of 7) plus automated risk support or a larger second panel
- Wrongful-vote penalties escalate reputation → vote weight → temporary mod removal → only then capped temporary dating-distribution penalty for demonstrated malicious patterns; always explained and appealable
- Automation recommends containment / verification; it does not permanently delete borderline accounts without review or appeal

## Matching and ranking

Hard eligibility first:

- Both verified adults
- Mutual gender/feed compatibility
- Overlapping Looking For modes
- Allowed distance
- Neither blocked the other
- Neither contained as a likely bot

Then alignment percentage ranks the rest. Dealbreakers may exclude. Users cannot tune algorithm weights. Filters use self-declared choices only (curiosity / conversation depth — never inferred “intelligence”).

## Messaging and meetup

- Initial experiment: 20 messages per match with a visible counter
- Persistent Plan a meetup button
- At the limit: plan meetup, mutually extend once, or unmatch — do not silently delete the chat
- No mandatory openers, synthetic reply buttons, relationship-phase prompts, or reflection questionnaires in chat

## Feature flags (until core acceptance)

Get fk’d, Match Map, and Skin Shop remain feature-flagged until Swipe + community bot control pass their acceptance tests. Creator Skin Shop sales require moderation, payments, copyright, and abuse controls first.

## Execution sequence

| PR | Focus | Exit condition |
|---|---|---|
| 1 | Scope lock + mass deletion + two-tab shell | Old product concepts no longer compile / exist |
| 2 | Clean swipe + mutual match | Verified adult opens app, sees a card, swipes, matches |
| 3 | Community bot control | Report → review → bury / challenge / restore / remove with audit trail |
| 4 | Limited chat + meetup path | Every match leads to meetup, mutual extension, or end |
| 5 | Proximity + match location | No exposure without standing or per-event permission |
| 6 | Skin Shop | Creator content cannot bypass moderation; purchases cannot buy reach |

## Definition of done (product)

- Only two permanent tabs exist
- First normal screen is a swipe card
- No questionnaire, algorithm editor, or research explanation blocks swiping
- Deepen Connection and relationship phases are completely gone
- Bot reporting ≤3 taps; one malicious voter cannot bury a profile
- Qualified community consensus can remove a likely bot from discovery
- Wrongful-vote penalties require a demonstrated pattern and are appealable
- Automation supports—not replaces—the community
- Strictly 18+; gender never sets privacy defaults
- No race/ethnicity/skin-color/height filters; no inferred intimate trait scoring
- Purchases never alter matching or moderation power
- Location and proximity off by default
- Messaging points toward meetup or mutual extension
