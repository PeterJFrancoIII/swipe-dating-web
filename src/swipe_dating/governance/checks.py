"""Executable governance contract for the synthetic-only Python rebuild."""

from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from swipe_dating import RELEASE_STATE
from swipe_dating.api.app import create_app
from swipe_dating.domain.local_state import serialize_local_state

SOURCE_COMMIT: Final = "5c6b35e8b133f4b34224785eb4fc1e7ab61423a4"
RELEASE_BLOCKS: Final = (
    "PYTHON_RND_SYNTHETIC_ONLY",
    "REAL_USER_CLOSED_BETA_BLOCKED",
    "PRODUCTION_BLOCKED_HUMAN_APPROVALS_REQUIRED",
)
FORBIDDEN_SOURCE_SUFFIXES: Final = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".go",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".mjs",
        ".rs",
        ".sh",
        ".swift",
        ".tf",
        ".ts",
        ".tsx",
    }
)
IGNORED_PARTS: Final = frozenset(
    {
        ".git",
        ".hypothesis",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def run_checks(root: Path | None = None) -> tuple[CheckResult, ...]:
    repository = root if root is not None else Path(__file__).resolve().parents[3]
    return (
        _release_blocks(repository),
        _baseline_binding(repository),
        _bootstrap_replaced(repository),
        _python_only_surface(repository),
        _deleted_product_surfaces(repository),
        _storage_allowlist(),
        _api_surface(),
        _ci_contract(repository),
        _production_approvals_absent(repository),
    )


def _release_blocks(root: Path) -> CheckResult:
    mission = _read(root / "MISSION.md")
    readme = _read(root / "README.md")
    missing = [value for value in RELEASE_BLOCKS if value not in mission or value not in readme]
    passed = not missing and RELEASE_BLOCKS[0] == RELEASE_STATE
    detail = "all release blocks present" if passed else f"missing or inconsistent: {missing}"
    return CheckResult("release-blocks", passed, detail)


def _baseline_binding(root: Path) -> CheckResult:
    baseline = _read(root / "docs" / "BASELINE.md")
    vectors_path = root / "tests" / "fixtures" / "behavior_vectors.json"
    vector_commit = ""
    with suppress(FileNotFoundError, KeyError, json.JSONDecodeError, TypeError):
        vector_commit = json.loads(vectors_path.read_text(encoding="utf-8"))["metadata"][
            "sourceCommit"
        ]
    passed = SOURCE_COMMIT in baseline and vector_commit == SOURCE_COMMIT
    detail = "baseline and vectors pinned" if passed else "source commit evidence missing"
    return CheckResult("baseline-binding", passed, detail)


def _bootstrap_replaced(root: Path) -> CheckResult:
    payload = root / "bootstrap_payload"
    payload_files = (
        tuple(path for path in payload.rglob("*") if path.is_file()) if payload.exists() else ()
    )
    passed = not (root / ".bootstrap").exists() and not payload_files
    return CheckResult(
        "bootstrap-replaced",
        passed,
        "partial payload absent" if passed else "incomplete bootstrap artifacts remain",
    )


def _python_only_surface(root: Path) -> CheckResult:
    violations: list[str] = []
    forbidden_names = {"Cargo.toml", "Makefile", "package.json", "package-lock.json"}
    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file() or any(part in IGNORED_PARTS for part in path.parts):
                continue
            if path.suffix.lower() in FORBIDDEN_SOURCE_SUFFIXES or path.name in forbidden_names:
                violations.append(str(path.relative_to(root)))
    return CheckResult(
        "python-only-surface",
        not violations,
        "no prohibited implementation files" if not violations else ", ".join(violations[:10]),
    )


def _deleted_product_surfaces(root: Path) -> CheckResult:
    forbidden_paths = (
        root / "src" / "swipe_dating" / "domain" / "relationship_phases.py",
        root / "tests" / "unit" / "test_relationship_phases.py",
    )
    remaining = [str(path.relative_to(root)) for path in forbidden_paths if path.exists()]
    banned_tokens = ("relationship_phases", "request_deepen", "advance_profile_reveal")
    source_hits: list[str] = []
    for path in (root / "src").rglob("*.py"):
        if path.name == "checks.py" and path.parent.name == "governance":
            continue
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in banned_tokens):
            source_hits.append(str(path.relative_to(root)))
    passed = not remaining and not source_hits
    detail = (
        "Deepen Connection / progressive reveal absent"
        if passed
        else f"remaining: {remaining + source_hits[:8]}"
    )
    return CheckResult("deleted-product-surfaces", passed, detail)


def _storage_allowlist() -> CheckResult:
    raw = json.loads(
        serialize_local_state(
            {
                "profile": {"displayName": "Synthetic", "about": "R&D", "pronouns": ""},
                "messages": ["private"],
                "matches": ["match:p1"],
                "birthDate": "2000-01-01",
                "relationshipPhase": "deepened",
                "location": {"latitude": 1},
                "keys": ["secret"],
            },
            now_ms=0,
        )
    )
    expected = {"schemaVersion", "savedAt", "profile", "cosmetics", "ui"}
    passed = set(raw) == expected
    return CheckResult(
        "storage-allowlist",
        passed,
        "strict top-level allowlist"
        if passed
        else f"unexpected keys: {sorted(set(raw) - expected)}",
    )


def _api_surface() -> CheckResult:
    paths = set(create_app().openapi()["paths"])
    expected = {
        "/healthz",
        "/v1/presence",
        "/v1/presence/{profile_id}",
        "/v1/discovery",
        "/v1/likes",
        "/v1/blocks",
    }
    passed = paths == expected
    return CheckResult(
        "api-surface",
        passed,
        "synthetic parity routes only" if passed else f"route drift: {sorted(paths ^ expected)}",
    )


def _ci_contract(root: Path) -> CheckResult:
    workflow = _read(root / ".github" / "workflows" / "ci.yml")
    required = (
        "pytest",
        "ruff check",
        "ruff format --check",
        "mypy src",
        "swipe-governance",
        "swipe-simulate",
    )
    missing = [command for command in required if command not in workflow]
    return CheckResult(
        "ci-contract",
        not missing,
        "all verification commands present" if not missing else f"missing: {missing}",
    )


def _production_approvals_absent(root: Path) -> CheckResult:
    approvals = root / "approvals" / "production"
    artifacts = (
        tuple(path for path in approvals.rglob("*") if path.is_file()) if approvals.exists() else ()
    )
    passed = not artifacts
    return CheckResult(
        "production-approvals",
        passed,
        "no fabricated production approval"
        if passed
        else "production artifacts require human review",
    )


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def main() -> None:
    results = run_checks()
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"{marker} {result.name}: {result.detail}")
    if not all(result.passed for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
