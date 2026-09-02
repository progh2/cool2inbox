"""테스트·데모용 가짜 쿨메신저 udb 생성기 (#9).

쿨메신저가 없는 환경(리눅스/macOS 개발, CI)에서도 전 기능을 검증하기 위한 것이다.
**실제 DB에서 확인한 스키마를 그대로** 재현한다 (PRD 4.1) — 컬럼 이름·순서·타입까지 같게 둬야
리더가 실물에서 다르게 동작하는 일이 없다.

저장소 테스트는 오직 이 가짜 데이터만 쓴다. 실제 쪽지 데이터에 의존하는 테스트는 만들지 않는다.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

# 실제 DB 원문 그대로 (공백만 정리)
DDL = [
    """CREATE TABLE IF NOT EXISTS tbl_recv(
        MessageKey INTEGER PRIMARY KEY AUTOINCREMENT,
        MessageBody TEXT, Title TEXT, Sender TEXT, SenderKey TEXT, ReferenceList TEXT, CCList TEXT,
        MessageType INTEGER, ReceiveDate DATE,
        FilePath TEXT, CoolFile2SessionID TEXT, LinkURL TEXT, FileHost TEXT, IsUnRead INTEGER,
        MessageText TEXT, MemoID INTEGER, IsChecked INTEGER, IsMoved INTEGER,
        MessageCategory INTEGER)""",
    """CREATE TABLE IF NOT EXISTS tbl_send(
        MessageKey INTEGER PRIMARY KEY AUTOINCREMENT,
        MessageBody TEXT, Title TEXT, Receiver TEXT, ReceiverKey TEXT, ReferenceList TEXT, CCList TEXT,
        MessageType INTEGER, SendDate DATE,
        FilePath TEXT, FileHost TEXT, AnswerBack TEXT, CoolFile2SessionID TEXT, ScheduledDate DATE,
        MessageText TEXT, MemoID INTEGER, IsChecked INTEGER, IsMoved INTEGER, LinkURL TEXT,
        MessageCategory INTEGER)""",
    """CREATE TABLE IF NOT EXISTS tbl_member(
        K_MemberID INTEGER PRIMARY KEY, MemberID TEXT, MemberName TEXT,
        Gender INTEGER, ProfileCreateAt TEXT, HP TEXT)""",
    """CREATE TABLE IF NOT EXISTS tbl_group(
        GroupID INTEGER PRIMARY KEY, GroupID_p INTEGER, GroupName TEXT, Depth INTEGER, Position INTEGER)""",
    """CREATE TABLE IF NOT EXISTS tbl_rank(
        RankID INTEGER PRIMARY KEY, RankName TEXT, Position INTEGER)""",
    """CREATE TABLE IF NOT EXISTS tbl_relation(
        MemberKey INTEGER, GroupID INTEGER, RankID INTEGER, IsDefault INTEGER, Position INTEGER)""",
    """CREATE TABLE IF NOT EXISTS tbl_dbInfo(
        dummyKey INTEGER, LatestRevKey INTEGER, LatestRecvStatus INTEGER,
        LatestSchedule INTEGER, LatestRecovery INTEGER, LatestToDoKey INTEGER)""",
]

WEEKDAYS = "월화수목금토일"


def format_receive_date(dt: datetime) -> str:
    """쿨메신저 형식: '2026/09/02 15:55:52 (수)'."""
    return f"{dt:%Y/%m/%d %H:%M:%S} ({WEEKDAYS[dt.weekday()]})"


def key_list(keys: list[int]) -> str:
    """수신자 목록 형식: [75, 12] → '|2|75|12|'."""
    return "|" + "|".join(str(x) for x in [len(keys), *keys]) + "|"


def file_list(files: list[tuple[str, int]], code: int = 50) -> str:
    """첨부 형식: [('a.hwp', 100), ('b.hwp', 200)] → '|2|300;100;200||a.hwp|50||b.hwp|50|'.

    파일이 1개면 실제 DB 처럼 크기가 '총합;개별' 로 중복된다.
    """
    if not files:
        return ""
    sizes = [s for _, s in files]
    head = [str(sum(sizes)), *[str(s) for s in sizes]] if len(files) > 1 else [str(sizes[0]), str(sizes[0])]
    parts = [f"|{len(files)}|{';'.join(head)}|"]
    for name, _ in files:
        parts.append(f"|{name}|{code}|")
    return "".join(parts)


def create_fake_udb(memo_dir: str | Path, messages: list[dict] | None = None,
                    members: list[dict] | None = None, name: str = "1000000_test_LX.udb") -> Path:
    """쿨메신저와 같은 구조의 udb 를 만든다.

    messages: [{"sender", "sender_key", "title", "body", "received": datetime,
                "recipients": [멤버키], "cc": [멤버키], "files": [(이름, 크기)], "unread": bool}]
    members:  [{"key", "id", "name"}]
    """
    d = Path(memo_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    for sql in DDL:
        con.execute(sql)
    for m in members or []:
        add_fake_member(con, m)
    for m in messages or []:
        append_fake_message(con, m)
    con.commit()
    con.close()
    return path


def add_fake_member(con_or_path, m: dict) -> None:
    own = isinstance(con_or_path, (str, Path))
    con = sqlite3.connect(con_or_path) if own else con_or_path
    con.execute("INSERT OR REPLACE INTO tbl_member (K_MemberID, MemberID, MemberName, Gender, ProfileCreateAt, HP) "
                "VALUES (?,?,?,?,?,?)",
                (int(m["key"]), m.get("id", f"user{m['key']}"), m.get("name", f"이름{m['key']}"),
                 m.get("gender", 0), m.get("profile_at", ""), m.get("hp", "")))
    if own:
        con.commit()
        con.close()


def append_fake_message(con_or_path, m: dict) -> int:
    """받은 쪽지 1건 추가. 반환값은 MessageKey."""
    own = isinstance(con_or_path, (str, Path))
    con = sqlite3.connect(con_or_path) if own else con_or_path
    received: datetime = m.get("received") or datetime.now()
    files = m.get("files") or []
    cur = con.execute(
        "INSERT INTO tbl_recv (MessageKey, MessageBody, Title, Sender, SenderKey, ReferenceList, CCList, "
        "MessageType, ReceiveDate, FilePath, CoolFile2SessionID, LinkURL, FileHost, IsUnRead, "
        "MessageText, MemoID, IsChecked, IsMoved, MessageCategory) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (m.get("key"), m.get("html", ""), m.get("title", ""), m.get("sender", "홍길동(hong)"),
         key_list([m.get("sender_key", 1)]),
         key_list(m.get("recipients", [1])),
         key_list(m["cc"]) if m.get("cc") else None,
         m.get("type", 5), format_receive_date(received),
         file_list(files), m.get("session_id", "0"), "",
         "coolmsgrfilea.coolmessenger.com:46001" if files else "",
         1 if m.get("unread") else 0,
         m.get("body", ""), m.get("memo_id", 50000000 + (m.get("key") or 0)),
         1 if m.get("checked") else 0, None, 0))
    key = int(cur.lastrowid)
    if own:
        con.commit()
        con.close()
    return key


def create_empty_account_udb(memo_dir: str | Path, name: str = "1000000_other_LX.udb") -> Path:
    """로그인 이력만 있는 **0행 계정 DB**. 실제 PC 에 이런 파일이 함께 있었다 (리더가 걸러야 한다)."""
    return create_fake_udb(memo_dir, messages=[], members=[], name=name)


def create_settings_udb(folder: str | Path, name: str = "1000000_test_LX.udb") -> Path:
    """설정 폴더(CustomDataLX)에 있는 `tbl_tabInfo` 짜리 가짜 udb.

    쪽지 DB 와 **파일 이름이 같다.** 이름으로 고르면 이걸 잡는다 — 리더가 내용으로 판별해야 한다.
    """
    d = Path(folder)
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE IF NOT EXISTS tbl_tabInfo (
        TabKey INTEGER PRIMARY KEY, Position INTEGER, IsHidden INTEGER,
        Title TEXT, Title_EN TEXT, Title_JP TEXT, LinkUrl TEXT, CallbackUrl TEXT,
        AutoLogin INTEGER, Keyword TEXT)""")
    con.execute("INSERT OR REPLACE INTO tbl_tabInfo (TabKey, Position) VALUES (0, 0)")
    con.commit()
    con.close()
    return path
