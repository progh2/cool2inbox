"""쿨메신저 받은 쪽지 읽기 전용 리더 (#7, #8).

저장소: `%LOCALAPPDATA%\\CoolMessenger\\Memo\\<조직코드>_<계정ID>_LX.udb` — 암호화 없는 SQLite(WAL).

**원본은 절대 쓰기 모드로 열지 않는다.** udb + -wal + -shm 을 임시 폴더에 복사한 뒤 복사본을
`mode=ro` 로 연다. 사용 후 복사본 삭제. (dacisosl/coolm-helper, progh2/catmoa 참고, 둘 다 MIT)

실물 스키마는 PRD 4.1 절에 정리돼 있다. 함정 둘:
- 같은 Memo 폴더에 **0행짜리 빈 계정 DB** 가 함께 있다
- 설정 폴더(CustomDataLX)에 **파일 이름이 같은** `tbl_tabInfo` 짜리 udb 가 있다
→ 파일 이름·수정 시각이 아니라 **내용**(tbl_recv 존재 + 행 수)으로 고른다.
"""
from __future__ import annotations

import base64
import glob
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

REQUIRED_COLS = {"MessageKey", "Sender", "ReceiveDate", "Title", "MessageText",
                 "ReferenceList", "FilePath"}
DATE_FORMAT = "%Y/%m/%d %H:%M:%S"
WEEKDAYS = "월화수목금토일"


class CoolmError(Exception):
    """사용자에게 그대로 보여줄 오류 (폴더 없음, 스키마 불일치 등)."""


# ---------------------------------------------------------------- 값 파싱

def parse_receive_date(s: str) -> datetime:
    """'2026/09/02 15:55:52 (수)' → datetime. 요일 표기는 버린다."""
    return datetime.strptime(str(s)[:19], DATE_FORMAT)


def parse_keylist(s: str | None) -> tuple[int, list[int]]:
    """수신자/참조/발신자 목록 → (선언된 인원수, 멤버키 목록).

    형식은 `|3|75|12|48|` — 첫 토큰이 인원수, 나머지가 멤버키다.
    실제 데이터에서 인원수와 키 개수가 어긋나는 경우가 있어 **둘 다** 돌려준다.
    """
    toks = [t for t in (s or "").strip("|").split("|") if t.strip()]
    nums: list[int] = []
    for t in toks:
        try:
            nums.append(int(t))
        except ValueError:
            continue
    if not nums:
        return 0, []
    return nums[0], nums[1:]


@dataclass(frozen=True)
class Attachment:
    name: str
    size: int | None = None


def parse_filepath(s: str | None) -> list[Attachment]:
    """첨부 목록 → [Attachment].

    형식은 `|<개수>|<총크기>;<크기1>;<크기2>…||<파일명1>|<코드>||<파일명2>|<코드>|`.
    크기 목록의 첫 값은 총합이다 (파일이 1개면 총합과 개별이 같은 값으로 중복된다).
    파일명 뒤 숫자(50~57)는 용도 미상이라 쓰지 않는다.
    """
    parts = (s or "").split("|")
    if len(parts) < 5:
        return []
    sizes: list[int] = []
    for x in parts[2].split(";"):
        try:
            sizes.append(int(x))
        except ValueError:
            pass
    individual = sizes[1:] if len(sizes) > 1 else sizes[:1]
    rest = parts[3:]
    names = [rest[i + 1] for i in range(0, len(rest) - 2, 3) if rest[i + 1].strip()]
    return [Attachment(name=n, size=individual[i] if i < len(individual) else None)
            for i, n in enumerate(names)]


def decode_message_body(s: str | None) -> str:
    """`MessageBody` (base64 + zlib + UTF-16LE HTML) 를 푼다. 실패하면 빈 문자열.

    v1 은 평문 `MessageText` 를 쓰므로 여기는 아직 쓰이지 않는다 (서식 보존 옵션용).
    """
    if not s:
        return ""
    try:
        raw = zlib.decompress(base64.b64decode(s))
    except (ValueError, zlib.error, TypeError):
        return ""
    for enc in ("utf-16-le", "utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return ""


def split_sender(sender: str) -> tuple[str, str]:
    """'홍길동(hong)' → ('홍길동', 'hong'). 괄호가 없으면 (원문, '')."""
    m = re.match(r"^\s*(.*?)\s*\(([^()]*)\)\s*$", sender or "")
    return (m.group(1), m.group(2)) if m else ((sender or "").strip(), "")


# ---------------------------------------------------------------- 인용된 이전 대화

_QUOTE_LINE_RE = re.compile(
    r"^\s*("
    r"-{3,}\s*(original\s*message|원본\s*메시지|원본|이전\s*(메시지|쪽지|대화))\s*-{3,}"
    r"|[-=_─━]{6,}"
    r"|on\s.+\swrote:"
    r"|\d{4}[./-]\s?\d{1,2}[./-]\s?\d{1,2}.*(님이\s*(작성|씀)|wrote|작성함?)\s*[:：]?"
    r"|(re|회신|답장|fw|fwd|전달)\s*[:：]\s*$"
    r")\s*$",
    re.I,
)
# 쿨메신저 실제 표기 — 확인한 DB 에서 '님이 보낸글 >>' 274건, '메시지 전달 >>' 22건
_COOLM_MARK_RE = re.compile(r"^[^\n]{0,100}?(?:님이\s*보낸\s*글|보낸\s*메시지(?:\s*전달)?|메시지\s*전달)\s*>>")
_HEADER_KEY_RE = re.compile(
    r"^\s*(from|보낸\s*사람|발신|발신자|sent|보낸\s*날짜|날짜|date|to|받는\s*사람|수신|subject|제목)\s*[:：]", re.I)
_GT_RE = re.compile(r"^\s*>")


def split_recent(body: str) -> tuple[str, str]:
    """(최근 내용, 인용된 이전 대화). 인용이 없으면 두 번째는 ''."""
    lines = (body or "").replace("\r", "").split("\n")
    cut = None
    for i, line in enumerate(lines):
        if i == 0 and not line.strip():
            continue
        if _COOLM_MARK_RE.match(line):       # 본문이 비어 있는 단순 전달이면 첫 줄이어도 인용
            cut = i
            break
        if _QUOTE_LINE_RE.match(line):
            cut = i
            break
        if _HEADER_KEY_RE.match(line):       # '보낸 사람:' 류가 2줄 이상 연달아 오면 인용 시작
            window = [x for x in lines[i:i + 4] if x.strip()]
            if sum(1 for x in window if _HEADER_KEY_RE.match(x)) >= 2 and i > 0:
                cut = i
                break
        if _GT_RE.match(line) and i > 0:     # '>' 인용이 이후 대부분을 차지하면
            rest = [x for x in lines[i:] if x.strip()]
            if rest and sum(1 for x in rest if _GT_RE.match(x)) >= max(2, int(len(rest) * 0.6)):
                cut = i
                break
    if cut is None:
        return (body or "").strip(), ""
    recent = "\n".join(lines[:cut]).strip()
    older = "\n".join(lines[cut:]).strip()
    older = "\n".join(re.sub(r"^\s*(>\s?)+", "", x) for x in older.split("\n")).strip()
    return recent, older


# ---------------------------------------------------------------- 모델

@dataclass
class Message:
    key: int
    received: datetime                     # 받은 쪽지는 수신 시각, 보낸 쪽지는 발신 시각
    kind: str = "recv"                     # recv | send
    sender: str = ""                       # 받은 쪽지: 보낸 사람 '표시이름(로그인ID)'. 보낸 쪽지: 비어 있음
    title: str = ""
    body: str = ""                         # 평문 MessageText
    sender_key: int | None = None
    recipient_keys: list[int] = field(default_factory=list)
    recipient_count: int = 0               # DB 가 선언한 인원수 (키 개수와 다를 수 있다)
    recipients: list[str] = field(default_factory=list)   # 이름으로 푼 것 (실패 시 '#키')
    cc_keys: list[int] = field(default_factory=list)
    cc_count: int = 0
    cc: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    is_unread: bool = False
    message_type: int = 5
    html_body: str = ""                    # MessageBody 원문 (필요할 때만 decode)

    # ---- 파생

    @property
    def sender_name(self) -> str:
        return split_sender(self.sender)[0]

    @property
    def sender_login(self) -> str:
        return split_sender(self.sender)[1]

    @property
    def weekday(self) -> str:
        return WEEKDAYS[self.received.weekday()]

    @property
    def is_sent(self) -> bool:
        return self.kind == "send"

    @property
    def party(self) -> str:
        """파일명·표시에 쓸 '상대방'. 받은 쪽지는 보낸 사람, 보낸 쪽지는 받는 사람 요약."""
        if not self.is_sent:
            return self.sender_name or self.sender
        if not self.recipients:
            return "받는사람"
        first = self.recipients[0]
        return f"{first} 외 {len(self.recipients) - 1}" if len(self.recipients) > 1 else first

    @property
    def attachment_names(self) -> list[str]:
        return [a.name for a in self.attachments]

    def content_hash(self) -> str:
        """udb 가 재생성돼 MessageKey 가 바뀌어도 같은 쪽지를 알아보기 위한 지문 (FR-4.2).

        보낸 쪽지와 받은 쪽지가 우연히 같은 내용이어도 섞이지 않도록 kind 를 포함한다.
        """
        who = self.sender if not self.is_sent else "→" + "|".join(self.recipients)
        raw = "|".join([self.kind, who, self.received.strftime(DATE_FORMAT), self.title, self.body])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def split_body(self) -> tuple[str, str]:
        """(최근 내용, 인용된 이전 대화)."""
        return split_recent(self.body)

    @property
    def is_empty(self) -> bool:
        """제목·본문·첨부가 모두 없는 쪽지 (저장할 것이 없다)."""
        return not (self.title.strip() or self.body.strip() or self.attachments)


# ---------------------------------------------------------------- 폴더·파일 찾기

def memo_dir_candidates() -> list[Path]:
    """쪽지 폴더 후보. 실물에서 확인된 경로를 앞에 둔다."""
    subs = (
        ("CoolMessenger", "Memo"),                    # ★ 실제 확인된 경로 (%LOCALAPPDATA%)
        ("CoolMessenger Files", "Memo"),              # Documents 쪽 (실물에서는 비어 있었다)
        ("Documents", "CoolMessenger Files", "Memo"),
        ("Documents", "CoolMessenger", "Memo"),
        ("CoolMessenger",),
        ("Coolmessenger", "Memo"),
        ("CoolMessenger", "Data", "Memo"),
    )
    out: list[Path] = []
    for var in ("LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "USERPROFILE"):
        base = os.environ.get(var, "")
        if not base:
            continue
        for sub in subs:
            out.append(Path(base).joinpath(*sub))
    return out


def _count_recv(uri: str) -> int | None:
    """tbl_recv 행 수. 테이블이 없거나 열 수 없으면 None."""
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return None
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "tbl_recv" not in tables:
            return None
        return int(con.execute("SELECT COUNT(*) FROM tbl_recv").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        con.close()


def has_messages(udb: str | Path) -> int:
    """이 udb 가 받은 쪽지를 담고 있으면 행 수, 아니면 0.

    설정 폴더의 `tbl_tabInfo` 짜리 udb 와 0행짜리 빈 계정 DB 를 여기서 걸러낸다.

    **`immutable=1` 로 연다.** 평범한 `mode=ro` 로 열면 SQLite 가 WAL 처리를 위해 원본 폴더에
    `-shm`/`-wal` 파일을 만든다 — 읽기 전용이라도 사용자 폴더에 파일을 쓰는 셈이라 안 된다.
    immutable 은 WAL 을 무시하므로, 테이블은 있는데 0행으로 보이면 (WAL 에만 데이터가 있는 경우)
    복사본을 만들어 다시 센다.
    """
    n = _count_recv(f"file:{udb}?mode=ro&immutable=1")
    if n is None:
        return 0
    if n > 0:
        return n
    tmp = tempfile.mkdtemp(prefix="cool2inbox_probe_")
    try:
        dst = os.path.join(tmp, "probe.udb")
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(str(udb) + ext):
                _copy(str(udb) + ext, dst + ext)
        return _count_recv(f"file:{dst}?mode=ro") or 0
    except OSError:
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def find_message_udb(memo_dir: str | Path) -> str:
    """폴더에서 **쪽지가 든** udb 를 고른다. 이름·시각이 아니라 내용으로 판별한다."""
    if not memo_dir or not Path(memo_dir).is_dir():
        raise CoolmError(f"쿨메신저 쪽지 폴더가 없습니다: {memo_dir or '(미설정)'}")
    cands = sorted(glob.glob(os.path.join(str(memo_dir), "*.udb")))
    if not cands:
        raise CoolmError(f"쪽지 DB(.udb)를 찾을 수 없습니다: {memo_dir}")
    scored = [(has_messages(p), os.path.getmtime(p), p) for p in cands]
    usable = [x for x in scored if x[0] > 0]
    if not usable:
        raise CoolmError(
            f"쪽지가 들어 있는 DB 를 찾지 못했습니다 ({len(cands)}개 확인): {memo_dir}\n"
            "쿨메신저에 로그인한 적이 있는 계정의 폴더인지 확인해 주세요.")
    usable.sort(key=lambda x: (x[0], x[1]))       # 행 수 → 수정 시각 순
    return usable[-1][2]


def default_memo_dir() -> str:
    """자동 탐지. 쪽지가 든 udb 가 있는 첫 폴더. 없으면 관례 경로 문자열."""
    for d in memo_dir_candidates():
        try:
            if not d.is_dir():
                continue
            if any(has_messages(p) for p in d.glob("*.udb")):
                return str(d)
            for sub in sorted(x for x in d.iterdir() if x.is_dir()):   # 계정별 하위 폴더
                if any(has_messages(p) for p in sub.glob("*.udb")):
                    return str(sub)
        except OSError:
            continue
    base = os.environ.get("LOCALAPPDATA", "")
    return str(Path(base) / "CoolMessenger" / "Memo") if base else ""


# ---------------------------------------------------------------- 리더

_SELECT = ("SELECT MessageKey, Sender, SenderKey, ReceiveDate, Title, MessageText, MessageBody, "
           "ReferenceList, CCList, FilePath, IsUnRead, MessageType FROM tbl_recv")
# 보낸 쪽지: Sender→'', SenderKey 없음, ReceiveDate→SendDate, IsUnRead 없음(0), 수신자는 ReceiverKey
_SEND_SELECT = ("SELECT MessageKey, '' AS Sender, '' AS SenderKey, SendDate AS ReceiveDate, Title, "
                "MessageText, MessageBody, ReceiverKey AS ReferenceList, CCList, FilePath, "
                "0 AS IsUnRead, MessageType FROM tbl_send")


class CoolmReader:
    """with 문으로 사용한다. 원본을 복사해 읽기 전용으로 연다."""

    def __init__(self, memo_dir: str | Path):
        self.memo_dir = str(memo_dir)
        self._tmp: str | None = None
        self._con: sqlite3.Connection | None = None
        self._members: dict[int, str] = {}
        self._has_deleted = False

    def __enter__(self) -> "CoolmReader":
        src = find_message_udb(self.memo_dir)
        self._tmp = tempfile.mkdtemp(prefix="cool2inbox_")
        dst = os.path.join(self._tmp, "copy.udb")
        try:
            for ext in ("", "-wal", "-shm"):
                if os.path.exists(src + ext):
                    _copy(src + ext, dst + ext)
            self._con = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
            self._con.row_factory = sqlite3.Row
            self._validate()
            self._load_members()
        except CoolmError:
            self.__exit__(None, None, None)
            raise
        except (OSError, sqlite3.Error) as e:
            self.__exit__(None, None, None)
            raise CoolmError(f"쿨메신저 DB 를 열 수 없습니다: {e}") from e
        return self

    def __exit__(self, *exc) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
            self._tmp = None

    # ---- 준비

    def _validate(self) -> None:
        cur = self._con.cursor()
        tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "tbl_recv" not in tables:
            raise CoolmError("쿨메신저 DB 구조가 예상과 다릅니다 (tbl_recv 없음). "
                             "쿨메신저 버전이 바뀌었을 수 있습니다.")
        cols = {r[1] for r in cur.execute("PRAGMA table_info(tbl_recv)")}
        missing = REQUIRED_COLS - cols
        if missing:
            raise CoolmError(f"쿨메신저 DB 에 필요한 항목이 없습니다: {', '.join(sorted(missing))}. "
                             "쿨메신저 버전이 바뀌었을 수 있습니다.")
        # DeletedDate 는 확인한 버전에 없다. 있는 버전을 대비해 선택적으로 다룬다.
        self._has_deleted = "DeletedDate" in cols
        self._has_member = "tbl_member" in tables
        self._has_sent = "tbl_send" in tables

    def _load_members(self) -> None:
        """멤버키 → 표시 이름. 조인 실패가 흔하므로 있는 것만 담는다."""
        if not self._has_member:
            return
        try:
            for r in self._con.execute("SELECT K_MemberID, MemberID, MemberName FROM tbl_member"):
                name = (r["MemberName"] or "").strip() or (r["MemberID"] or "").strip()
                if name:
                    self._members[int(r["K_MemberID"])] = name
        except sqlite3.Error as e:
            log.warning("조직도(tbl_member)를 읽지 못했습니다: %s", e)

    def name_of(self, member_key: int) -> str:
        """이름을 못 찾으면 `#키` 로 돌려준다 (퇴직·전출·외부 조직에서 흔하다)."""
        return self._members.get(int(member_key), f"#{member_key}")

    @property
    def member_count(self) -> int:
        return len(self._members)

    # ---- 조회

    def _where(self) -> str:
        return " WHERE DeletedDate IS NULL" if self._has_deleted else ""

    def _and(self) -> str:
        return " AND DeletedDate IS NULL" if self._has_deleted else ""

    def count(self) -> int:
        return int(self._con.execute(f"SELECT COUNT(*) FROM tbl_recv{self._where()}").fetchone()[0])

    def latest_key(self) -> int:
        row = self._con.execute(f"SELECT MAX(MessageKey) FROM tbl_recv{self._where()}").fetchone()
        return int(row[0] or 0)

    def all_keys(self) -> list[int]:
        return [int(r[0]) for r in self._con.execute(
            f"SELECT MessageKey FROM tbl_recv{self._where()} ORDER BY MessageKey")]

    def messages_after(self, key: int, limit: int = 50) -> list[Message]:
        """MessageKey > key 인 쪽지 (오래된 순)."""
        rows = self._con.execute(
            f"{_SELECT} WHERE MessageKey > ?{self._and()} ORDER BY MessageKey ASC LIMIT ?",
            (int(key), int(limit))).fetchall()
        return self._rows(rows)

    def latest_messages(self, limit: int = 10) -> list[Message]:
        rows = self._con.execute(
            f"{_SELECT}{self._where()} ORDER BY MessageKey DESC LIMIT ?", (int(limit),)).fetchall()
        return self._rows(rows)

    def messages_page(self, offset: int = 0, limit: int = 200) -> list[Message]:
        """백필용 순차 조회 (오래된 순)."""
        rows = self._con.execute(
            f"{_SELECT}{self._where()} ORDER BY MessageKey ASC LIMIT ? OFFSET ?",
            (int(limit), int(offset))).fetchall()
        return self._rows(rows)

    def messages_by_keys(self, keys: list[int]) -> list[Message]:
        if not keys:
            return []
        marks = ",".join("?" * len(keys))
        rows = self._con.execute(
            f"{_SELECT} WHERE MessageKey IN ({marks}){self._and()} ORDER BY MessageKey ASC",
            [int(k) for k in keys]).fetchall()
        return self._rows(rows)

    # ---- 보낸 쪽지 (tbl_send)

    @property
    def has_sent(self) -> bool:
        return self._has_sent

    def latest_sent_key(self) -> int:
        if not self._has_sent:
            return 0
        row = self._con.execute("SELECT MAX(MessageKey) FROM tbl_send").fetchone()
        return int(row[0] or 0)

    def all_sent_keys(self) -> list[int]:
        if not self._has_sent:
            return []
        return [int(r[0]) for r in self._con.execute(
            "SELECT MessageKey FROM tbl_send ORDER BY MessageKey")]

    def sent_after(self, key: int, limit: int = 50) -> list[Message]:
        if not self._has_sent:
            return []
        rows = self._con.execute(
            f"{_SEND_SELECT} WHERE MessageKey > ? ORDER BY MessageKey ASC LIMIT ?",
            (int(key), int(limit))).fetchall()
        return self._rows(rows, kind="send")

    def sent_page(self, offset: int = 0, limit: int = 200) -> list[Message]:
        if not self._has_sent:
            return []
        rows = self._con.execute(
            f"{_SEND_SELECT} ORDER BY MessageKey ASC LIMIT ? OFFSET ?",
            (int(limit), int(offset))).fetchall()
        return self._rows(rows, kind="send")

    def sent_by_keys(self, keys: list[int]) -> list[Message]:
        if not self._has_sent or not keys:
            return []
        marks = ",".join("?" * len(keys))
        rows = self._con.execute(
            f"{_SEND_SELECT} WHERE MessageKey IN ({marks}) ORDER BY MessageKey ASC",
            [int(k) for k in keys]).fetchall()
        return self._rows(rows, kind="send")

    def summary(self) -> str:
        """'연결 테스트' 버튼에 보여줄 한 줄 (FR-6.2)."""
        n = self.count()
        latest = self.latest_messages(limit=1)
        if not latest:
            return f"연결 OK — 받은 쪽지가 없습니다 (조직도 {self.member_count}명)"
        m = latest[0]
        title = f" 「{m.title[:20]}」" if m.title.strip() else ""
        return (f"연결 OK — 쪽지 {n:,}건, 최근 {m.received:%Y-%m-%d %H:%M} "
                f"{m.sender_name or '?'}{title}")

    # ---- 행 → 모델

    def _rows(self, rows, kind: str = "recv") -> list[Message]:
        out = []
        for r in rows:
            m = self._to_message(r, kind)
            if m is not None:
                out.append(m)
        return out

    def _to_message(self, r, kind: str = "recv") -> Message | None:
        try:
            received = parse_receive_date(r["ReceiveDate"])
        except (ValueError, TypeError):
            log.warning("받은 시각을 해석하지 못해 건너뜁니다 (MessageKey=%s)", r["MessageKey"])
            return None
        rcount, rkeys = parse_keylist(r["ReferenceList"])
        ccount, cckeys = parse_keylist(r["CCList"])
        _, skeys = parse_keylist(r["SenderKey"])
        return Message(
            key=int(r["MessageKey"]),
            received=received,
            kind=kind,
            sender=r["Sender"] or "",
            title=r["Title"] or "",
            body=r["MessageText"] or "",
            sender_key=skeys[0] if skeys else None,
            recipient_keys=rkeys,
            recipient_count=rcount or len(rkeys),
            recipients=[self.name_of(k) for k in rkeys],
            cc_keys=cckeys,
            cc_count=ccount or len(cckeys),
            cc=[self.name_of(k) for k in cckeys],
            attachments=parse_filepath(r["FilePath"]),
            is_unread=bool(r["IsUnRead"]),
            message_type=int(r["MessageType"] or 0),
            html_body=r["MessageBody"] or "",
        )


def _copy(src: str, dst: str) -> None:
    """공유 모드로 읽어 복사한다 (쿨메신저가 열어 둔 파일도 읽을 수 있게)."""
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)
