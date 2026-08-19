from __future__ import annotations

import pytest

from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.swipe_allotment import (
    charges_daily_swipe,
    consume_daily_swipe,
    refund_daily_swipe,
    swipes_remaining,
)


def test_thirty_free_swipes_then_fail_closed() -> None:
    day, used = "", 0
    for _ in range(30):
        day, used = consume_daily_swipe(day, used, "2026-08-16", limit=30)
    assert used == 30
    assert swipes_remaining(day, used, "2026-08-16", limit=30) == 0
    with pytest.raises(DomainError) as error:
        consume_daily_swipe(day, used, "2026-08-16", limit=30)
    assert error.value.code == "daily_swipe_limit"


def test_new_day_resets_and_undo_refunds() -> None:
    day, used = consume_daily_swipe("2026-08-15", 30, "2026-08-16", limit=30)
    assert (day, used) == ("2026-08-16", 1)
    day, used = refund_daily_swipe(day, used, "2026-08-16")
    assert used == 0


def test_synthetic_cards_do_not_charge_the_daily_allotment() -> None:
    assert charges_daily_swipe(type("Real", (), {"synthetic": False})()) is True
    assert charges_daily_swipe(type("Fake", (), {"synthetic": True})()) is False
    assert charges_daily_swipe(object()) is True
