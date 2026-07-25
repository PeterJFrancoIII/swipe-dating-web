# Profile Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Help a laptop R&D user supply enough self-authored, non-visual profile context for bio-first discovery with a transparent two-item checklist.

**Architecture:** Add one pure readiness assessment over the existing display-name and about fields, expose it through `ResearchSession`, and render it in the existing My Profile tab. The checklist is advisory, makes no match-quality prediction, does not score pronouns, and adds no field to local storage.

**Tech Stack:** Python 3.12/3.13, frozen dataclasses, pytest, Tkinter, Ruff, mypy, uv, GitHub Actions.

---

### Task 1: Add the pure profile-readiness assessment

**Files:**
- Create: `tests/unit/test_profile_readiness.py`
- Create: `src/swipe_dating/domain/profile_readiness.py`

- [x] **Step 1: Write the failing domain test**

Cover whitespace-only input, a partial profile, the exact 80-character about boundary, stable item order, and the fact that only user-supplied completeness is measured.

```python
def test_profile_readiness_tracks_two_transparent_basics() -> None:
    empty = assess_profile_readiness("   ", "   ")
    assert empty.completed == ()
    assert empty.missing == ("display_name", "about_context")
    assert empty.completed_count == 0
    assert empty.total_count == 2
    assert empty.ready is False

    partial = assess_profile_readiness(" Riley ", "Short and honest")
    assert partial.completed == ("display_name",)
    assert partial.missing == ("about_context",)

    ready = assess_profile_readiness("Riley", "x" * MIN_PROFILE_ABOUT_CHARS)
    assert ready.completed == ("display_name", "about_context")
    assert ready.missing == ()
    assert ready.ready is True
```

- [x] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/unit/test_profile_readiness.py -q`

Expected: collection fails because the profile-readiness module does not exist.

- [x] **Step 3: Implement the smallest pure model**

Create a frozen `ProfileReadiness` result and `assess_profile_readiness` function. Use two fixed item keys in this order:

1. `display_name`: trimmed display name is non-empty.
2. `about_context`: trimmed about text contains at least 80 characters.

Expose `completed_count`, `total_count`, and `ready` as derived properties. Do not inspect language, sentiment, identity, attractiveness, health, intent, or pronouns.

- [x] **Step 4: Run the test and verify GREEN**

Run: `uv run pytest tests/unit/test_profile_readiness.py -q`

Expected: PASS.

### Task 2: Derive readiness through the session without expanding storage

**Files:**
- Modify: `tests/unit/test_session.py`
- Modify: `src/swipe_dating/application/session.py`

- [x] **Step 1: Write the failing session and persistence test**

```python
def test_profile_readiness_is_derived_and_never_persisted() -> None:
    session, adapter = create_session()
    session.update_profile(display_name="Riley", about="x" * 80, pronouns="")

    readiness = session.profile_readiness()

    assert readiness.ready is True
    raw = json.loads(adapter.inspect())
    assert "readiness" not in raw
    assert set(raw["profile"]) == {"displayName", "about", "pronouns"}
```

- [x] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/unit/test_session.py::test_profile_readiness_is_derived_and_never_persisted -q`

Expected: FAIL with `AttributeError` because the session method does not exist.

- [x] **Step 3: Add the narrow session method**

Import the pure assessment and return an assessment of `self.local_state.profile`. Do not add mutable session state or repository fields.

- [x] **Step 4: Run the session test and verify GREEN**

Run: `uv run pytest tests/unit/test_session.py::test_profile_readiness_is_derived_and_never_persisted -q`

Expected: PASS and the local payload remains unchanged.

### Task 3: Render the advisory checklist

**Files:**
- Modify: `src/swipe_dating/desktop/app.py`
- Modify: `tests/smoke/test_desktop_import.py`

- [x] **Step 1: Add a smoke assertion for the readiness renderer**

Verify `DesktopApp` exposes the small readiness-rendering helper before editing Tkinter behavior.

- [x] **Step 2: Run the smoke test and verify RED**

Run: `uv run pytest tests/smoke/test_desktop_import.py -q`

Expected: FAIL because the helper is absent.

- [x] **Step 3: Render two explicit checklist rows in My Profile**

Show:

- display name supplied;
- about text containing at least 80 self-authored characters.

Use the copy “advisory only,” “does not predict matches or profile quality,” and “adds no stored field.” Keep pronouns visibly optional and do not block saving or browsing.

- [x] **Step 4: Run focused UI and session tests**

Run: `uv run pytest tests/unit/test_profile_readiness.py tests/unit/test_session.py tests/smoke/test_desktop_import.py -q`

Expected: PASS.

### Task 4: Document, verify, and deploy Loop 3

**Files:**
- Modify: `README.md`
- Modify: `docs/specs/current-objective.md`
- Verify: entire repository

- [x] **Step 1: Document the feature and unchanged boundary**

Add the advisory readiness checklist to the laptop client summary and set the current objective to this plan. State that it derives from existing fields and is not persisted separately.

- [x] **Step 2: Run the complete local release gate**

Run sequentially:

```bash
uv run python -m compileall -q src tests
uv run pytest --cov=swipe_dating --cov-branch --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run swipe-governance
uv run swipe-simulate
uv pip check
git diff --check
```

Expected: every command exits 0, coverage remains at least 90%, and the release state remains `PYTHON_RND_SYNTHETIC_ONLY`.

- [x] **Step 3: Commit and push the slice**

```bash
git add README.md docs/specs/current-objective.md docs/superpowers/plans/2026-07-22-profile-readiness.md src/swipe_dating/domain/profile_readiness.py src/swipe_dating/application/session.py src/swipe_dating/desktop/app.py tests/unit/test_profile_readiness.py tests/unit/test_session.py tests/smoke/test_desktop_import.py
git commit -m "Add advisory profile readiness"
git push
```

- [x] **Step 4: Wait for both GitHub lanes and refresh the draft PR**

Run: `gh pr checks 1 --watch --interval 10`

Expected: Python 3.12 and 3.13 both pass. Refresh the PR with the exact test count, measured coverage, feature summary, and unchanged safety boundary.
