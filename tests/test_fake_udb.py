"""가짜 udb 생성기 (#9).

이 생성기가 실물과 다르면 나머지 테스트가 전부 거짓말이 된다. 형식부터 못 박는다.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from src.sources.fake_udb import (append_fake_message, create_empty_account_udb, create_fake_udb,
                                  create_settings_udb, file_list, format_receive_date, key_list)


def test_받은_시각_형식():
    assert format_receive_date(datetime(2026, 9, 2, 15, 55, 52)) == "2026/09/02 15:55:52 (수)"
    assert format_receive_date(datetime(2025, 3, 24, 9, 40, 40)) == "2025/03/24 09:40:40 (월)"


def test_수신자_목록_형식():
    assert key_list([75, 12, 48]) == "|3|75|12|48|"
    assert key_list([1]) == "|1|1|"


def test_첨부_형식_한_개는_크기가_중복된다():
    """실물이 그렇다 — '총합;개별' 인데 개별이 하나뿐이라 같은 값이 두 번 나온다."""
    assert file_list([("문서.hwpx", 32001)]) == "|1|32001;32001||문서.hwpx|50|"


def test_첨부_형식_여러_개는_총합이_앞에():
    assert file_list([("계획서.hwp", 717824), ("공문.hwp", 194048)]) == \
        "|2|911872;717824;194048||계획서.hwp|51|" .replace("|51|", "|50|") + "|공문.hwp|50|"


def test_첨부_없으면_빈_문자열():
    assert file_list([]) == ""


def test_스키마가_실물과_같다(tmp_path):
    p = create_fake_udb(tmp_path)
    con = sqlite3.connect(p)
    cols = [c[1] for c in con.execute("PRAGMA table_info(tbl_recv)")]
    assert cols == ["MessageKey", "MessageBody", "Title", "Sender", "SenderKey", "ReferenceList",
                    "CCList", "MessageType", "ReceiveDate", "FilePath", "CoolFile2SessionID",
                    "LinkURL", "FileHost", "IsUnRead", "MessageText", "MemoID", "IsChecked",
                    "IsMoved", "MessageCategory"]
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"tbl_recv", "tbl_send", "tbl_member", "tbl_group", "tbl_rank"} <= tables
    assert "DeletedDate" not in cols          # 실물에 없다


def test_쪽지를_넣으면_읽힌다(tmp_path):
    p = create_fake_udb(tmp_path, [
        {"title": "협의회", "body": "내일 3시", "received": datetime(2026, 9, 2, 15, 0, 0),
         "recipients": [1, 2], "cc": [3], "files": [("a.hwp", 100), ("b.hwp", 200)]},
    ])
    con = sqlite3.connect(p)
    r = con.execute("SELECT Title, ReceiveDate, ReferenceList, CCList, FilePath FROM tbl_recv").fetchone()
    assert r[0] == "협의회"
    assert r[1] == "2026/09/02 15:00:00 (수)"
    assert r[2] == "|2|1|2|"
    assert r[3] == "|1|3|"
    assert r[4].startswith("|2|300;100;200||a.hwp|")


def test_참조가_없으면_NULL이다(tmp_path):
    """실물에서 CCList 는 68% 가 NULL 이다."""
    p = create_fake_udb(tmp_path, [{"title": "x"}])
    con = sqlite3.connect(p)
    assert con.execute("SELECT CCList FROM tbl_recv").fetchone()[0] is None


def test_키는_자동_증가한다(tmp_path):
    p = create_fake_udb(tmp_path, [{"title": "1"}, {"title": "2"}])
    assert append_fake_message(p, {"title": "3"}) == 3


def test_빈_계정_DB는_구조만_있고_0행(tmp_path):
    p = create_empty_account_udb(tmp_path)
    con = sqlite3.connect(p)
    assert con.execute("SELECT COUNT(*) FROM tbl_recv").fetchone()[0] == 0


def test_설정용_udb는_tbl_tabInfo만_있다(tmp_path):
    p = create_settings_udb(tmp_path)
    con = sqlite3.connect(p)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"tbl_tabInfo"}


def test_조직도_등록(tmp_path):
    p = create_fake_udb(tmp_path, members=[{"key": 7, "id": "kim", "name": "김철수"}])
    con = sqlite3.connect(p)
    assert con.execute("SELECT MemberName FROM tbl_member WHERE K_MemberID=7").fetchone()[0] == "김철수"
