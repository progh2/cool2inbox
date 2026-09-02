"""진입점 배선 (#5).

app.exec() 를 돌리지 않고 main() 의 앞부분만 확인한다.
"""
from __future__ import annotations

import main as entry
from src import single_instance as si


def test_이미_실행_중이면_조용히_0으로_끝난다(qapp, monkeypatch):
    monkeypatch.setattr(si, "acquire", lambda on_show=None, name=None: None)
    assert entry.main([]) == 0


def test_main은_인자를_받을_수_있다():
    import inspect

    assert "argv" in inspect.signature(entry.main).parameters
