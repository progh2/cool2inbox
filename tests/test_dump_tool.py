"""스키마 덤프 도구 (#6) — 개인정보를 흘리지 않는지가 핵심."""
from __future__ import annotations

import io
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import dump_coolm_schema as dump  # noqa: E402

from src.sources.fake_udb import create_fake_udb  # noqa: E402


def test_값의_형태만_남기고_내용은_가린다():
    assert "홍길동" not in dump.shape("홍길동")
    assert dump.shape("홍길동") == "3자 [가가가]"
    assert dump.shape("hong2026") == "8자 [aaaa9999]"
    assert dump.shape(None) == "NULL"
    assert dump.shape("") == "빈 문자열"


def test_긴_값도_잘라서_가린다():
    got = dump.shape("가" * 200)
    assert "가" * 61 not in got
    assert got.startswith("200자")


def test_큰_수는_자릿수만():
    assert dump.shape(59_492_968) == "수(8자리)"
    assert dump.shape(5) == "수 5"


def test_BLOB은_앞부분_헥스만():
    assert dump.shape(b"\x00\x01secret") .startswith("BLOB 8바이트")


def test_덤프에_실제_쪽지_내용이_들어가지_않는다(tmp_path):
    memo = tmp_path / "Memo"
    create_fake_udb(memo, [{"title": "대외비 협의회", "body": "비밀번호는 1234입니다",
                            "sender": "홍길동(hong)", "received": datetime(2026, 9, 2, 10, 0)}],
                    members=[{"key": 1, "id": "ham", "name": "함기훈"}])
    buf = io.StringIO()
    dump.dump_db(next(memo.glob("*.udb")), buf)
    text = buf.getvalue()
    assert "tbl_recv" in text and "ReferenceList" in text     # 구조는 나온다
    for secret in ("대외비", "비밀번호", "1234", "홍길동", "함기훈", "hong"):
        assert secret not in text, secret                     # 내용은 안 나온다
