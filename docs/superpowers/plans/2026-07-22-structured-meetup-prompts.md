# Structured Meetup Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an active synthetic match propose a curated, low-pressure public meetup after a two-way conversation, without collecting or sharing any location.

**Architecture:** Reuse the existing session-only conversation transcript as the sole state. The conversation domain will build three structured suggestions and send the selected suggestion through the existing message transition; the session coordinator and Tkinter adapter remain thin wrappers. No venue lookup, coordinates, calendar, event feed, acceptance state, network action, or new persistence is introduced.

**Tech Stack:** Python 3.12/3.13, pytest, Tkinter, Ruff, mypy, uv, GitHub Actions.

---

### Task 1: Define safe structured meetup suggestions

**Files:**
- Modify: `tests/unit/test_conversations.py`
- Modify: `src/swipe_dating/domain/conversations.py`

- [x] **Step 1: Write the failing suggestion-catalog test**

Add `build_meetup_suggestions` to the test imports and add:

```python
def test_meetup_suggestions_are_grounded_public_and_location_free() -> None:
    created = matched()
    match = created.state.matches[str(created.outcome["match_id"])]

    suggestions = build_meetup_suggestions(match)

    assert [suggestion.id for suggestion in suggestions] == [
        "coffee_public",
        "museum_daytime",
        "public_activity",
    ]
    assert all("hiking" in suggestion.prompt for suggestion in suggestions)
    assert all("public" in suggestion.prompt for suggestion in suggestions)
    assert all("no location has been shared" in suggestion.prompt for suggestion in suggestions)
```

- [x] **Step 2: Run the catalog test and verify RED**

Run: `uv run pytest tests/unit/test_conversations.py::test_meetup_suggestions_are_grounded_public_and_location_free -q`

Expected: collection fails because `build_meetup_suggestions` does not exist.

- [x] **Step 3: Implement the immutable catalog builder**

In `src/swipe_dating/domain/conversations.py`, add:

```python
@dataclass(frozen=True, slots=True)
class MeetupSuggestion:
    id: str
    title: str
    prompt: str
```

Then add:

```python
def build_meetup_suggestions(match: ConversationMatch) -> tuple[MeetupSuggestion, ...]:
    if match.status is not MatchStatus.ACTIVE:
        raise DomainError("match_not_active")
    if not match.starter_tag:
        raise DomainError("match_starter_missing")
    label = match.starter_tag.replace("_", " ")
    safety = "This is only a proposal; no location has been shared."
    return (
        MeetupSuggestion(
            "coffee_public",
            "Coffee in a public place",
            f"Would you like to meet for coffee in a public place and keep talking about {label}? {safety}",
        ),
        MeetupSuggestion(
            "museum_daytime",
            "Daytime public museum visit",
            f"Would you like to visit a public museum during daytime hours and keep talking about {label}? {safety}",
        ),
        MeetupSuggestion(
            "public_activity",
            "Low-pressure public activity",
            f"Would you like to choose a low-pressure activity in a well-populated public place and keep talking about {label}? {safety}",
        ),
    )
```

- [x] **Step 4: Run the catalog test and verify GREEN**

Run: `uv run pytest tests/unit/test_conversations.py::test_meetup_suggestions_are_grounded_public_and_location_free -q`

Expected: PASS.

### Task 2: Send a proposal only after two-way conversation

**Files:**
- Modify: `tests/unit/test_conversations.py`
- Modify: `src/swipe_dating/domain/conversations.py`

- [x] **Step 1: Write the failing readiness-and-send test**

Add `send_meetup_proposal` to the test imports and add:

```python
def test_meetup_proposal_requires_two_way_conversation() -> None:
    created = matched()
    match_id = str(created.outcome["match_id"])
    opened = send_message(
        created.state,
        match_id=match_id,
        text="What trail do you like?",
        shared_ground_tag="hiking",
        at_ms=AT,
    )
    with pytest.raises(DomainError, match="meetup_requires_two_way_conversation"):
        send_meetup_proposal(
            opened.state,
            match_id=match_id,
            suggestion_id="coffee_public",
            at_ms=AT + 1,
        )
    replied = receive_synthetic_reply(
        opened.state,
        match_id=match_id,
        text="I like the river loop.",
        at_ms=AT + 1,
    )

    proposed = send_meetup_proposal(
        replied.state,
        match_id=match_id,
        suggestion_id="coffee_public",
        at_ms=AT + 2,
    )

    assert proposed.value.sender == "local"
    assert proposed.value.body.startswith("Would you like to meet for coffee")
    assert proposed.state.matches[match_id].messages[-1] == proposed.value
```

- [x] **Step 2: Run the readiness test and verify RED**

Run: `uv run pytest tests/unit/test_conversations.py::test_meetup_proposal_requires_two_way_conversation -q`

Expected: collection fails because `send_meetup_proposal` does not exist.

- [x] **Step 3: Implement proposal sending through the existing message transition**

```python
def send_meetup_proposal(
    state: ConversationState,
    *,
    match_id: str,
    suggestion_id: str,
    at_ms: int | float | None = None,
) -> ValueResult[ConversationState, Message]:
    match = _require_active_match(state, match_id)
    senders = {message.sender for message in match.messages}
    if not {"local", "candidate"}.issubset(senders):
        raise DomainError("meetup_requires_two_way_conversation")
    suggestions = {suggestion.id: suggestion for suggestion in build_meetup_suggestions(match)}
    suggestion = suggestions[suggestion_id]
    return send_message(state, match_id=match_id, text=suggestion.prompt, at_ms=at_ms)
```

- [x] **Step 4: Run the readiness test and verify GREEN**

Run: `uv run pytest tests/unit/test_conversations.py::test_meetup_proposal_requires_two_way_conversation -q`

Expected: PASS.

- [x] **Step 5: Write the failing unknown-suggestion test**

```python
def test_unknown_meetup_suggestion_is_rejected() -> None:
    created = matched()
    match_id = str(created.outcome["match_id"])
    opened = send_message(
        created.state,
        match_id=match_id,
        text="Opening",
        shared_ground_tag="hiking",
        at_ms=AT,
    )
    replied = receive_synthetic_reply(
        opened.state,
        match_id=match_id,
        text="Reply",
        at_ms=AT + 1,
    )
    with pytest.raises(DomainError, match="unknown_meetup_suggestion"):
        send_meetup_proposal(
            replied.state,
            match_id=match_id,
            suggestion_id="private_address",
            at_ms=AT + 2,
        )
```

- [x] **Step 6: Run the unknown-suggestion test and verify RED**

Run: `uv run pytest tests/unit/test_conversations.py::test_unknown_meetup_suggestion_is_rejected -q`

Expected: FAIL with `KeyError`.

- [x] **Step 7: Fail closed for an unknown catalog identifier**

Replace the direct lookup with:

```python
    try:
        suggestion = suggestions[suggestion_id]
    except KeyError as error:
        raise DomainError("unknown_meetup_suggestion") from error
```

- [x] **Step 8: Run the complete conversation unit suite**

Run: `uv run pytest tests/unit/test_conversations.py -q`

Expected: PASS.

### Task 3: Coordinate proposals and prove the persistence boundary

**Files:**
- Modify: `tests/unit/test_session.py`
- Modify: `src/swipe_dating/application/session.py`

- [x] **Step 1: Write the failing session behavior test**

Add:

```python
def test_meetup_proposal_is_session_only_and_purged_on_block() -> None:
    session, adapter = create_session()
    session.accept_adult_gate("2000-01-01")
    outcome = session.express_interest("p1", "hiking")
    match_id = str(outcome["match_id"])
    session.send_message(match_id, "What trail do you like?", "hiking")
    session.receive_synthetic_reply(match_id, "I like the river loop.")

    proposal = session.propose_meetup(match_id, "coffee_public")

    assert "public place" in proposal.body
    assert adapter.inspect() is None
    session.block(match_id)
    assert session.conversations.matches[match_id].messages == ()
```

- [x] **Step 2: Run the session test and verify RED**

Run: `uv run pytest tests/unit/test_session.py::test_meetup_proposal_is_session_only_and_purged_on_block -q`

Expected: FAIL because `ResearchSession.propose_meetup` does not exist.

- [x] **Step 3: Add the thin session coordinator**

Import `send_meetup_proposal` in `src/swipe_dating/application/session.py`, then add:

```python
    def propose_meetup(self, match_id: str, suggestion_id: str) -> Message:
        self._require_adult()
        result = send_meetup_proposal(
            self.conversations,
            match_id=match_id,
            suggestion_id=suggestion_id,
            at_ms=self.clock(),
        )
        self.conversations = result.state
        return result.value
```

- [x] **Step 4: Run the session test and verify GREEN**

Run: `uv run pytest tests/unit/test_session.py::test_meetup_proposal_is_session_only_and_purged_on_block -q`

Expected: PASS.

### Task 4: Render meetup prompts in the active match UI

**Files:**
- Modify: `src/swipe_dating/desktop/app.py`
- Modify: `docs/PARITY_MATRIX.md`
- Modify: `docs/specs/current-objective.md`

- [x] **Step 1: Import the meetup catalog builder**

Add `build_meetup_suggestions` to the existing conversation imports in `src/swipe_dating/desktop/app.py`.

- [x] **Step 2: Render suggestions only after two-way conversation**

Inside the active-match branch, after the composer/reply controls, add:

```python
                        candidate_messages = [
                            message for message in match.messages if message.sender == "candidate"
                        ]
                        meetup = tk.Frame(card, bg=PANEL, padx=14, pady=14)
                        meetup.pack(fill="x", pady=(14, 0))
                        self._text(
                            meetup,
                            "Suggest a public meetup",
                            bg=PANEL,
                            size=16,
                            weight="bold",
                        ).pack(anchor="w")
                        self._text(
                            meetup,
                            "A suggestion is not consent to meet and shares no location. Exchange at least one message each first.",
                            bg=PANEL,
                            color=MUTED,
                            wrap=880,
                        ).pack(anchor="w", pady=(4, 8))
                        if candidate_messages:
                            for suggestion in build_meetup_suggestions(match):
                                self._button(
                                    meetup,
                                    suggestion.title,
                                    lambda suggestion_id=suggestion.id, match_id=match.id: self._send_meetup(
                                        match_id, suggestion_id
                                    ),
                                ).pack(fill="x", pady=3)
                        else:
                            self._text(
                                meetup,
                                "Meetup suggestions unlock after a synthetic reply.",
                                bg=PANEL,
                                color=AMBER,
                            ).pack(anchor="w")
```

- [x] **Step 3: Add the thin UI callback**

```python
    def _send_meetup(self, match_id: str, suggestion_id: str) -> None:
        try:
            self.session.propose_meetup(match_id, suggestion_id)
        except DomainError as error:
            self._show_domain_error(error)
            return
        self._render_active_tab()
```

Add `meetup_requires_two_way_conversation` and `unknown_meetup_suggestion` to `_show_domain_error` with concise messages.

```python
            "meetup_requires_two_way_conversation": "Exchange at least one message each before suggesting a meetup.",
            "unknown_meetup_suggestion": "Choose one of the available public meetup suggestions.",
```

- [x] **Step 4: Update scope documentation**

In `docs/PARITY_MATRIX.md`, change the conversations status to:

```markdown
| `rnd-conversations` | `domain/conversations.py` | Verified session-only behavior, including structured public-meetup prompts |
```

In `docs/specs/current-objective.md`, replace the `Current loop` line with:

```markdown
**Current loop:** [2026-07-22-structured-meetup-prompts.md](../superpowers/plans/2026-07-22-structured-meetup-prompts.md)
```

Keep all production blockers unchanged.

- [x] **Step 5: Format and run the focused checks**

Run:

```bash
uv run ruff format src/swipe_dating/domain/conversations.py src/swipe_dating/application/session.py src/swipe_dating/desktop/app.py tests/unit/test_conversations.py tests/unit/test_session.py
uv run pytest tests/unit/test_conversations.py tests/unit/test_session.py tests/smoke/test_desktop_import.py -q
uv run ruff check src/swipe_dating/domain/conversations.py src/swipe_dating/application/session.py src/swipe_dating/desktop/app.py tests/unit/test_conversations.py tests/unit/test_session.py
uv run mypy src
```

Expected: all commands exit 0.

- [x] **Step 6: Commit the complete meetup slice**

```bash
git add src/swipe_dating/domain/conversations.py src/swipe_dating/application/session.py src/swipe_dating/desktop/app.py tests/unit/test_conversations.py tests/unit/test_session.py docs/PARITY_MATRIX.md docs/specs/current-objective.md docs/superpowers/plans/2026-07-22-structured-meetup-prompts.md
git commit -m "Add structured public meetup prompts"
```

### Task 5: Verify and deploy the second loop

**Files:**
- Verify: entire repository

- [x] **Step 1: Run the full verification gate**

Run these commands sequentially:

```bash
uv run python -m compileall -q src tests
uv run pytest --cov=swipe_dating --cov-branch --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run swipe-governance
uv run swipe-simulate
uv pip check
git diff --check HEAD~1
git status --short --branch
```

Expected: every command exits 0 and the release state remains `PYTHON_RND_SYNTHETIC_ONLY`.

- [x] **Step 2: Push and wait for CI**

Run:

```bash
git push -u origin agent/python-rnd-rebuild
gh pr checks 1 --watch --interval 10
```

Expected: the draft PR updates and both Python 3.12 and 3.13 jobs pass.

- [x] **Step 3: Refresh the PR evidence**

Update draft PR #1 with the new test count, measured coverage, meetup behavior, and unchanged safety boundary. Preserve the worktree for the next narrow loop.
