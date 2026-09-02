"""배포 설정 (#22, #23).

빌드 자체는 CI 가 한다. 여기서는 **틀리면 릴리스가 통째로 실패하는 것들**만 검사한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_spec_이_있고_필요한_설정이_들어있다():
    spec = (ROOT / "cool2inbox.spec").read_text(encoding="utf-8")
    assert "console=False" in spec          # 트레이 앱 — 검은 콘솔 창 금지
    assert "assets" in spec                 # 마스코트가 번들에 들어가야 한다
    assert "PySide6.QtNetwork" in spec      # 단일 인스턴스 확인에 필요


def test_아이콘이_있어야_빌드된다():
    assert (ROOT / "assets" / "icon.ico").exists()


def test_버전_형식():
    from src import __version__

    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_워크플로가_태그와_버전을_대조한다():
    """이게 없으면 v1.2.3 태그에 1.0.0 짜리 exe 가 붙는 사고가 난다."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "__version__" in ci
    assert "GITHUB_REF_NAME" in ci


def test_워크플로에_Qt_시스템_의존성이_있다():
    """빠뜨리면 GUI 테스트가 조용히 전부 건너뛰어진다 — 통과처럼 보여서 더 위험하다."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "libxkbcommon0" in ci
    assert "QT_QPA_PLATFORM: offscreen" in ci


def test_워크플로는_테스트가_통과해야_빌드한다():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "needs: test" in ci


def test_개발용_의존성에_pyinstaller():
    dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "pyinstaller" in dev
    assert "-r requirements.txt" in dev


def test_빌드_산출물은_커밋되지_않는다():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "build/" in ignore and "dist/" in ignore
