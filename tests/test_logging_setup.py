"""로깅 설정 (#5)."""
from __future__ import annotations

import logging

from src.logging_setup import MAX_BYTES, log_path, setup_logging


def test_로그_파일은_설정_디렉터리에(isolated_dirs):
    assert log_path() == isolated_dirs / "cool2inbox.log"


def test_설정하면_파일이_생긴다():
    setup_logging()
    logging.getLogger("t").info("안녕")
    assert log_path().exists()
    assert "안녕" in log_path().read_text(encoding="utf-8")


def test_여러_번_불러도_핸들러가_겹치지_않는다():
    for _ in range(3):
        setup_logging(to_stderr=False)
    logging.getLogger("t").info("한 번만")
    assert log_path().read_text(encoding="utf-8").count("한 번만") == 1


def test_회전_설정():
    setup_logging(to_stderr=False)
    handlers = [h for h in logging.getLogger().handlers if hasattr(h, "maxBytes")]
    assert handlers and handlers[0].maxBytes == MAX_BYTES
    assert handlers[0].backupCount == 3


def test_로그를_못_쓰는_상황에서도_예외가_없다(monkeypatch, isolated_dirs):
    monkeypatch.setattr("src.logging_setup.RotatingFileHandler",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("디스크 가득")))
    setup_logging(to_stderr=False)          # 예외 없이 넘어가야 한다
    logging.getLogger("t").info("계속 돈다")
