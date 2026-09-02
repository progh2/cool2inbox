"""테스트 공통 픽스처.

설정 디렉터리와 홈 디렉터리를 tmp_path 로 돌려 실제 사용자 환경을 건드리지 않게 한다.
GUI 는 offscreen 으로 띄운다 (헤드리스 CI/리눅스 개발 환경).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import autostart
from src import config as cfg


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """모든 테스트는 격리된 설정/홈 디렉터리를 쓴다."""
    d = tmp_path / "config"
    d.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv(cfg.ENV_CONFIG_DIR, str(d))
    monkeypatch.setenv(autostart.ENV_HOME, str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return d


@pytest.fixture(scope="session")
def qapp():
    """Qt 이벤트 루프가 필요한 테스트용 (소켓·시그널). 세션당 하나만 만든다.

    Qt GUI 는 리눅스에서 libxkbcommon 같은 시스템 라이브러리를 요구한다. 없으면 건너뛴다 —
    GUI 를 못 띄우는 환경에서도 나머지 테스트는 전부 돌아야 한다 (README '개발' 절 참고).
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as e:                      # pragma: no cover - 환경 의존
        pytest.skip(f"Qt GUI 를 띄울 수 없는 환경입니다: {e}")
    app = QApplication.instance() or QApplication([])
    yield app
