from __future__ import annotations

from pathlib import Path

from swipe_dating.governance.checks import run_checks

ROOT = Path(__file__).parents[2]


def test_repository_governance_contracts_pass() -> None:
    results = run_checks(ROOT)
    assert results
    assert all(result.passed for result in results), [
        f"{result.name}: {result.detail}" for result in results if not result.passed
    ]


def test_missing_governance_evidence_fails_closed(tmp_path: Path) -> None:
    results = run_checks(tmp_path)
    assert any(not result.passed for result in results)
    assert any(result.name == "release-blocks" and not result.passed for result in results)
    assert any(result.name == "baseline-binding" and not result.passed for result in results)
