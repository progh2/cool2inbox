"""트레이 아이콘과 메뉴 (#5).

트레이는 시그널만 낸다 — 그 계약을 지키는지 본다.
"""
from __future__ import annotations

import pytest

from src.ui.tray import AppState, Tray, assets_dir, state_icon


@pytest.fixture
def tray(qapp):
    t = Tray()
    yield t
    t.hide()


def test_아이콘_파일이_다섯_상태_모두_있다():
    for st in AppState:
        assert (assets_dir() / "penguin" / f"{st.value}.png").exists(), st


def test_상태_아이콘은_비어있지_않다(qapp):
    for st in AppState:
        assert not state_icon(st).isNull(), st


def test_메뉴_구성(tray):
    labels = [a.text() for a in tray.contextMenu().actions() if a.text()]
    assert "지금 확인" in labels
    assert "일시정지" in labels
    assert "인박스 폴더 열기" in labels
    assert "설정…" in labels
    assert "로그 보기" in labels
    assert "종료" in labels
    assert any("정보" in x for x in labels)


def test_상태_요약_항목은_누를_수_없다(tray):
    assert tray.act_status.isEnabled() is False


def test_초기_상태는_대기(tray):
    assert tray.state is AppState.IDLE
    assert tray.paused is False


def test_툴팁_기본(tray):
    assert tray.tooltip_text() == "cool2inbox — 대기 중\n아직 확인하지 않았습니다"


def test_요약을_넣으면_툴팁에_나온다(tray):
    tray.set_summary("17:04", 3)
    assert "마지막 확인 17:04, 오늘 3건 배달" in tray.tooltip_text()
    assert "마지막 확인 17:04" in tray.act_status.text()


def test_요약을_비우면_원래대로(tray):
    tray.set_summary("17:04", 3)
    tray.set_summary()
    assert "아직 확인하지 않았습니다" in tray.tooltip_text()


def test_오류_상세는_툴팁_셋째_줄(tray):
    tray.set_state(AppState.ERROR, "쪽지 폴더가 없습니다")
    lines = tray.tooltip_text().split("\n")
    assert lines[0].endswith("오류")
    assert lines[2] == "쪽지 폴더가 없습니다"


def test_상태를_바꾸면_아이콘도_바뀐다(tray):
    before = tray.icon().cacheKey()
    tray.set_state(AppState.ERROR)
    assert tray.icon().cacheKey() != before


# ---------------------------------------------------------------- 일시정지

def test_일시정지하면_메뉴_글자와_아이콘이_바뀐다(tray):
    tray.set_paused(True)
    assert tray.paused is True
    assert tray.state is AppState.PAUSED
    assert tray.act_pause.text() == "재개"
    assert tray.act_check.isEnabled() is False


def test_재개하면_대기로_돌아온다(tray):
    tray.set_paused(True)
    tray.set_paused(False)
    assert tray.state is AppState.IDLE
    assert tray.act_pause.text() == "일시정지"
    assert tray.act_check.isEnabled() is True


def test_재개는_설정필요_상태를_덮지_않는다(tray):
    """설정이 안 된 상태에서 재개해도 '설정 필요'가 유지돼야 한다."""
    tray.set_state(AppState.SETUP)
    tray.set_paused(False)
    assert tray.state is AppState.SETUP


# ---------------------------------------------------------------- 시그널

def test_일시정지_메뉴는_반대값을_내보낸다(tray):
    got = []
    tray.pause_toggled.connect(got.append)
    tray.act_pause.trigger()
    assert got == [True]
    tray.set_paused(True)
    tray.act_pause.trigger()
    assert got == [True, False]


def test_지금_확인_시그널(tray):
    got = []
    tray.check_now_requested.connect(lambda: got.append(1))
    tray.act_check.trigger()
    assert got == [1]


def test_트레이는_스스로_아무_일도_하지_않는다(tray, monkeypatch):
    """시그널을 아무도 안 받아도 예외가 나면 안 된다."""
    for a in tray.contextMenu().actions():
        if a.isEnabled() and a.text():
            a.trigger()
