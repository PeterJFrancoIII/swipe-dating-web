from __future__ import annotations

from swipe_dating.web.app import app
from swipe_dating.web.run import main


def test_web_app_and_launcher_import() -> None:
    assert app.title == "Swipe Dating Bot-Control R&D"
    assert callable(main)
