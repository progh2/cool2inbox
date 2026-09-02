"""시작 프로그램 등록 (#4).

Windows 레지스트리 분기는 이 환경에서 실행할 수 없다 — Linux/macOS 경로로 왕복만 검증한다.
"""
from __future__ import annotations

import platform
import sys

import pytest

from src import autostart


def test_소스_실행이면_python과_main을_등록한다():
    cmd = autostart.launch_command()
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("main.py")


def test_frozen이면_실행파일_하나(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/opt/cool2inbox/cool2inbox", raising=False)
    if platform.system() != "Darwin":
        assert autostart.launch_command() == ["/opt/cool2inbox/cool2inbox"]


def test_등록_해제_왕복():
    assert autostart.is_enabled() is False
    autostart.enable()
    assert autostart.is_enabled() is True
    autostart.disable()
    assert autostart.is_enabled() is False


def test_두_번_등록해도_문제없다():
    autostart.enable()
    autostart.enable()
    assert autostart.is_enabled() is True


def test_등록하지_않은_상태에서_해제해도_조용하다():
    autostart.disable()
    assert autostart.is_enabled() is False


def test_set_enabled():
    autostart.set_enabled(True)
    assert autostart.is_enabled()
    autostart.set_enabled(False)
    assert not autostart.is_enabled()


@pytest.mark.skipif(platform.system() != "Linux", reason="XDG autostart 는 Linux 전용")
def test_desktop_파일_내용():
    autostart.enable()
    text = autostart._desktop_path().read_text(encoding="utf-8")
    assert "[Desktop Entry]" in text
    assert "Name=cool2inbox" in text
    assert "main.py" in text


@pytest.mark.skipif(platform.system() != "Linux", reason="XDG autostart 는 Linux 전용")
def test_XDG_CONFIG_HOME을_존중한다(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    autostart.enable()
    assert (xdg / "autostart" / "cool2inbox.desktop").exists()


def test_공백_있는_경로는_따옴표로_감싼다():
    assert autostart._quoted(["/opt/my app/x", "-q"]) == '"/opt/my app/x" -q'
