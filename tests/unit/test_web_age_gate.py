from __future__ import annotations

from datetime import date

from swipe_dating.web.app import (
    birth_date_parts,
    birth_year_choices,
    compose_submitted_birth_date,
)


def test_compose_submitted_birth_date_prefers_direct_iso_value() -> None:
    assert (
        compose_submitted_birth_date(
            birth_date=" 2000-01-02 ",
            birth_month="12",
            birth_day="31",
            birth_year="1999",
        )
        == "2000-01-02"
    )


def test_compose_submitted_birth_date_builds_iso_from_wheel_values() -> None:
    assert (
        compose_submitted_birth_date(
            birth_date="",
            birth_month="3",
            birth_day="9",
            birth_year="2001",
        )
        == "2001-03-09"
    )


def test_compose_submitted_birth_date_fails_closed_for_partial_wheels() -> None:
    assert (
        compose_submitted_birth_date(
            birth_date="",
            birth_month="01",
            birth_day="",
            birth_year="2000",
        )
        == ""
    )


def test_birth_date_parts_split_valid_iso_and_ignore_invalid() -> None:
    assert birth_date_parts("2010-01-01") == ("01", "01", "2010")
    assert birth_date_parts("not-a-date") == ("", "", "")


def test_birth_year_choices_put_adult_cohort_first() -> None:
    years = birth_year_choices("2026-07-22")
    assert years[0] == "2008"
    assert "2000" in years
    assert years[-1] == "2026"
    assert years.index("2008") < years.index("2000") < years.index("2010")


def test_birth_year_choices_falls_back_when_today_is_invalid() -> None:
    years = birth_year_choices("not-a-date")
    assert years[-1] == f"{date.today().year:04d}"
    assert years[0] == f"{date.today().year - 18:04d}"
