# Swipe Dating Python R&D Rebuild Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task by task.

**Goal:** Replace the incomplete bootstrap shell with a pip-installable, synthetic-only Python recreation of the Swipe Dating R&D app, including domain parity, a FastAPI adapter, a deterministic simulator, a Tkinter laptop UI, governance checks, and verified repository delivery.

**Architecture:** Keep product rules in framework-independent frozen dataclasses and pure transition functions under `src/swipe_dating/domain`. Put file storage, cryptographic identifiers, HTTP, simulation, and Tkinter behind adapters. Persist only the approved non-sensitive profile/cosmetic/UI allowlist; all dating, discovery, match, message, phase, proximity, and location state remains session-only. The JavaScript repository at commit `5c6b35e8b133f4b34224785eb4fc1e7ab61423a4` and the supplied rebuild specification are the parity oracle.

**Tech Stack:** Python 3.12+, FastAPI/Pydantic v2, Uvicorn, Tkinter, pytest, Hypothesis, HTTPX, Ruff, mypy.

---

### Task 1: Establish the Python project and governance contract

**Files:**
- Delete: `.bootstrap`
- Delete: `bootstrap_payload/part_00`
- Delete: `bootstrap_payload/reconstruct.py`
- Replace: `README.md`
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.github/workflows/ci.yml`
- Create: `MISSION.md`
- Create: `docs/specs/current-objective.md`
- Create: `docs/ARCHITECTURE.md`
- Create: `docs/BASELINE.md`
- Create: `docs/PARITY_MATRIX.md`
- Create: `docs/PRIVACY_BOUNDARIES.md`
- Create: `docs/PRODUCTION_GAPS.md`

**Steps:**
1. Add package metadata, locked compatible dependency ranges, console scripts, strict lint/type/test configuration, and CI on Python 3.12 and 3.13.
2. Document the exact source commit and the `PYTHON_RND_SYNTHETIC_ONLY` / `REAL_USER_CLOSED_BETA_BLOCKED` / `PRODUCTION_BLOCKED_HUMAN_APPROVALS_REQUIRED` release state.
3. Remove the unusable partial archive only after the replacement structure is ready.
4. Verify project metadata with `python -m compileall src tests` once package files exist.

### Task 2: Port pure domain behavior with tests first

**Files:**
- Create: `src/swipe_dating/domain/{adult,alignment,preferences,matching,proximity,location_grants,risk,skin_shop,discovery,conversations,relationship_phases,local_state}.py`
- Create: `src/swipe_dating/domain/{models,errors}.py`
- Create: `src/swipe_dating/domain/__init__.py`
- Create: `src/swipe_dating/__init__.py`
- Create: `tests/unit/test_{adult_alignment,matching_safety,discovery,conversations,relationship_phases,local_state}.py`
- Create: `tests/property/test_domain_properties.py`

**Steps:**
1. Write failing parity tests for date/adult credentials, alignment, filter policy, rendezvous, proximity, location grants, risk, skins, discovery, conversations, phases, and local storage.
2. Implement typed error codes, enums, frozen models, deterministic sorting, and immutable transition results.
3. Preserve exact limits: adult boundary, 120-second presence TTL, discovery limit 20, 500-character messages, 300-character deeper answers, storage field limits, and Skin Shop bounds.
4. Run `pytest tests/unit tests/property -q` and `ruff check src tests`.

### Task 3: Add adapters and deterministic behavior vectors

**Files:**
- Create: `src/swipe_dating/adapters/crypto/identifiers.py`
- Create: `src/swipe_dating/adapters/storage.py`
- Create: `src/swipe_dating/fixtures.py`
- Create: `src/swipe_dating/simulation/run.py`
- Create: `tests/unit/test_crypto.py`
- Create: `tests/contract/test_behavior_vectors.py`
- Create: `tests/fixtures/behavior_vectors.json`

**Steps:**
1. Port the HMAC encounter/quota identifier helpers using Python standard-library cryptography primitives for synthetic test identifiers only.
2. Add memory and JSON-file allowlist repositories; prove forbidden fields never serialize.
3. Capture and replay canonical JSON parity vectors for critical JavaScript behavior.
4. Add a deterministic simulator command and compare its stable output in tests.
5. Run `pytest tests/unit/test_crypto.py tests/contract -q`.

### Task 4: Recreate the API contract

**Files:**
- Create: `src/swipe_dating/api/app.py`
- Create: `src/swipe_dating/api/run.py`
- Create: `src/swipe_dating/api/__init__.py`
- Create: `tests/integration/test_api.py`

**Steps:**
1. Write failing HTTP contract tests for health, presence publish/withdraw, discovery, reciprocal likes, blocks, invalid input, not-found, and the 65,536-byte body cap.
2. Implement dependency-injected FastAPI routes over the in-memory rendezvous store using camelCase wire fields.
3. Keep the API synthetic-only and make no authentication, verification, delivery, encryption, or production claims.
4. Run `pytest tests/integration/test_api.py -q`.

### Task 5: Build the laptop desktop recreation

**Files:**
- Create: `src/swipe_dating/application/session.py`
- Create: `src/swipe_dating/desktop/app.py`
- Create: `src/swipe_dating/desktop/__init__.py`
- Create: `tests/unit/test_session.py`
- Create: `tests/smoke/test_desktop_import.py`

**Steps:**
1. Write controller tests for adult gate, discovery/reveal, interest/match, required opener, unmatch/block, and bilateral Deepen Connection coordination.
2. Implement a Tkinter UI with adult gate and Discover, Matches, My Profile, Preferences, Skin Shop, and Matched Map tabs.
3. Label every fixture and simulated action as synthetic; keep Bluetooth and location collection disabled.
4. Store only the strict local allowlist under the user data directory and test the adapter with temporary directories.
5. Run `pytest tests/unit/test_session.py tests/smoke/test_desktop_import.py -q` and `python -m swipe_dating.simulation.run`.

### Task 6: Add fail-closed governance and complete repository delivery

**Files:**
- Create: `src/swipe_dating/governance/checks.py`
- Create: `tests/governance/test_governance.py`
- Update: `docs/PARITY_MATRIX.md`
- Update: `README.md`

**Steps:**
1. Add checks that reject production-enabling artifacts/claims, missing block statuses, disallowed persistence fields, and missing source-baseline documentation.
2. Run `python -m compileall src tests`, `pytest --cov=swipe_dating --cov-branch --cov-report=term-missing`, `ruff check .`, `ruff format --check .`, `mypy src`, `swipe-governance`, and `swipe-simulate`.
3. Inspect `git diff --check`, the full diff, and repository status; ensure source project files outside this worktree remain untouched.
4. Use the verification-before-completion and finishing-a-development-branch skills.
5. Commit the verified scope, push `agent/python-rnd-rebuild`, open a draft pull request against `main`, and inspect GitHub Actions results.
