"""로그 보기 창 (#20)."""
from __future__ import annotations

import logging

import pytest

from src.logging_setup import log_path, setup_logging
from src.ui.log_dialog import TAIL_LINES, LogDialog, tail


def test_없는_파일은_안내(tmp_path):
    assert "아직 기록된 로그가 없습니다" in tail(tmp_path / "없음.log")


def test_끝부분만_읽는다(tmp_path):
    p = tmp_path / "a.log"
    p.write_text("\n".join(f"줄 {i}" for i in range(2000)), encoding="utf-8")
    got = tail(p).splitlines()
    assert len(got) == TAIL_LINES
    assert got[-1] == "줄 1999"


def test_짧은_파일은_통째로(tmp_path):
    p = tmp_path / "a.log"
    p.write_text("한 줄\n두 줄\n", encoding="utf-8")
    assert tail(p).splitlines() == ["한 줄", "두 줄"]


def test_큰_파일도_끝만_읽어서_빠르다(tmp_path):
    p = tmp_path / "big.log"
    p.write_text("x" * 2_000_000 + "\n마지막 줄\n", encoding="utf-8")
    assert tail(p).splitlines()[-1] == "마지막 줄"


def test_깨진_바이트가_있어도_읽는다(tmp_path):
    p = tmp_path / "a.log"
    p.write_bytes("정상 줄\n".encode("utf-8") + b"\xff\xfe" + " 깨짐\n".encode("utf-8"))
    assert "정상 줄" in tail(p)


def test_창에_로그가_보인다(qapp):
    setup_logging(to_stderr=False)
    logging.getLogger("t").info("쪽지 3건 저장")
    d = LogDialog(log_path())
    assert "쪽지 3건 저장" in d.view.toPlainText()
    d.close()


def test_새로_고치면_최신_내용이_들어온다(qapp):
    setup_logging(to_stderr=False)
    d = LogDialog(log_path())
    logging.getLogger("t").info("나중에 생긴 줄")
    assert "나중에 생긴 줄" not in d.view.toPlainText()
    d.reload()
    assert "나중에 생긴 줄" in d.view.toPlainText()
    d.close()


def test_폴더_열기_시그널(qapp):
    d = LogDialog(log_path())
    got = []
    d.open_folder_requested.connect(lambda: got.append(1))
    d.btn_folder.click()
    assert got == [1]
    d.close()


def test_읽기_전용이다(qapp):
    d = LogDialog(log_path())
    assert d.view.isReadOnly()
    d.close()


def test_컨트롤러가_로그_창을_연다(qapp, tmp_path):
    from src.app import AppController
    from src.config import Config

    c = Config()
    c.coolm.memo_dir, c.inbox.root_dir = str(tmp_path), str(tmp_path)
    ctl = AppController(qapp, config=c)
    ctl.open_logs()
    assert ctl._logs is not None
    first = ctl._logs
    ctl.open_logs()                       # 두 번 열어도 창은 하나
    assert ctl._logs is first
    ctl._logs.close()
    ctl.tray.hide()
