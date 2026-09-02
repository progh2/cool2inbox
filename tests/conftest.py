"""테스트 공통 픽스처.

설정 디렉터리를 tmp_path 로 돌려 실제 사용자 설정을 건드리지 않게 한다.
"""
from __future__ import annotations

import pytest

from src import config as cfg


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """모든 테스트는 격리된 설정 디렉터리를 쓴다."""
    d = tmp_path / "config"
    d.mkdir()
    monkeypatch.setenv(cfg.ENV_CONFIG_DIR, str(d))
    return d
