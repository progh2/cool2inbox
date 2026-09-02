"""설정 저장/복원.

- JSON 파일 하나 (`platformdirs` 사용자 설정 디렉터리)
- 환경변수 `COOL2INBOX_CONFIG_DIR` 로 설정 디렉터리를 바꿀 수 있다 (테스트/휴대용 실행)
- 비밀값은 다루지 않는다 — 이 앱은 로컬 파일만 읽고 쓴다

로드는 관대하게 한다: 모르는 키는 무시하고, 빠진 키는 기본값을 쓰고, 타입이 어긋나면 기본값으로
되돌린다. 설정 파일이 깨져 있어도 프로그램이 뜨지 않는 일은 없어야 한다 (FR-6.1).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, get_type_hints

from platformdirs import user_config_dir

from src import APP_NAME

log = logging.getLogger(__name__)

ENV_CONFIG_DIR = "COOL2INBOX_CONFIG_DIR"

# 확인 주기 허용 범위 (분) — FR-5.1
POLL_MIN, POLL_MAX = 1, 120
DEFAULT_FILENAME_FORMAT = "{date}_{time}_{sender}_{title}_#{key}"


# ---------------------------------------------------------------- 경로

def config_dir() -> Path:
    """설정 디렉터리. 없으면 만든다."""
    override = os.environ.get(ENV_CONFIG_DIR)
    d = Path(override) if override else Path(user_config_dir(APP_NAME, appauthor=False))
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.json"


def state_path() -> Path:
    """중복 방지 이력 DB."""
    return config_dir() / "state.sqlite3"


# ---------------------------------------------------------------- 설정 모델

@dataclass
class CoolmSettings:
    """쿨메신저 원본 읽기 관련. 모두 읽기 전용 대상이다."""

    memo_dir: str = ""                  # %LOCALAPPDATA%\CoolMessenger\Memo
    recv_file_dir: str = ""             # %USERPROFILE%\Documents\CoolMessenger Files\Received Files
    last_message_key: int = 0           # 여기까지 처리했다 (MessageKey)
    attach_match_minutes: int = 30      # 첨부 시각 매칭 허용 오차 (FR-2.4 2순위)


@dataclass
class InboxSettings:
    """드롭박스 인박스 출력 위치."""

    root_dir: str = ""                  # 예: D:\Dropbox\Inbox
    coolm_folder_name: str = "쿨메신저"
    attach_folder_name: str = "첨부파일"
    max_attach_mb: int = 200            # 0 = 무제한 (FR-2.8)

    def coolm_dir(self) -> Path:
        """쪽지 md 가 쌓이는 폴더."""
        return Path(self.root_dir) / self.coolm_folder_name

    def attach_dir(self) -> Path:
        """첨부파일 폴더 (쪽지별 하위 폴더의 부모)."""
        return self.coolm_dir() / self.attach_folder_name


@dataclass
class ScheduleSettings:
    """폴링 주기와 실행 제어."""

    poll_minutes: int = 5               # FR-5.1
    max_per_poll: int = 50              # FR-5.5
    paused: bool = False                # FR-5.2
    autostart: bool = False             # FR-5.8
    notify: bool = True                 # FR-8.6


@dataclass
class OutputSettings:
    """마크다운 출력 형식."""

    filename_format: str = DEFAULT_FILENAME_FORMAT
    split_quoted: bool = True           # 인용된 이전 대화 분리 (FR-4.3 / 4.3절)
    include_recipients: bool = True     # 머리말에 받는 사람 목록
    include_cc: bool = True             # 머리말에 참조 목록
    include_attachments: bool = True    # 머리말·본문에 첨부파일


@dataclass
class UiSettings:
    """UI 상태 (기능 설정이 아니라 기억해 두는 값)."""

    first_run_done: bool = False        # 마법사를 끝냈는가 (FR-7.1)
    last_check_at: str = ""             # 마지막 확인 시각, 툴팁용 (FR-8.4)


@dataclass
class Config:
    coolm: CoolmSettings = field(default_factory=CoolmSettings)
    inbox: InboxSettings = field(default_factory=InboxSettings)
    schedule: ScheduleSettings = field(default_factory=ScheduleSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    ui: UiSettings = field(default_factory=UiSettings)

    # ---- 입출력

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """설정을 읽는다. 파일이 없거나 깨졌으면 기본값을 돌려준다 (예외를 던지지 않는다)."""
        p = Path(path) if path else config_path()
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("설정 파일을 읽을 수 없어 기본값을 씁니다 (%s): %s", p, e)
            _backup_broken(p)
            return cls()
        if not isinstance(data, dict):
            log.warning("설정 파일 형식이 올바르지 않아 기본값을 씁니다: %s", p)
            _backup_broken(p)
            return cls()
        cfg = _from_dict(cls, data)
        cfg.normalize()
        return cfg

    def save(self, path: str | Path | None = None) -> Path:
        """원자적으로 저장한다 (.tmp → replace). 저장 전에 값을 정규화한다."""
        self.normalize()
        p = Path(path) if path else config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, p)
        return p

    # ---- 검증

    def normalize(self) -> None:
        """범위를 벗어난 값을 제자리로 돌린다. 사용자가 손으로 고친 JSON도 안전해진다."""
        s = self.schedule
        s.poll_minutes = _clamp(s.poll_minutes, POLL_MIN, POLL_MAX, 5)
        s.max_per_poll = _clamp(s.max_per_poll, 1, 1000, 50)
        c = self.coolm
        c.last_message_key = max(0, _int(c.last_message_key, 0))
        c.attach_match_minutes = _clamp(c.attach_match_minutes, 0, 24 * 60, 30)
        i = self.inbox
        i.max_attach_mb = max(0, _int(i.max_attach_mb, 200))
        i.coolm_folder_name = i.coolm_folder_name.strip() or "쿨메신저"
        i.attach_folder_name = i.attach_folder_name.strip() or "첨부파일"
        o = self.output
        o.filename_format = o.filename_format.strip() or DEFAULT_FILENAME_FORMAT

    def is_configured(self) -> bool:
        """마법사를 띄우지 않아도 되는 상태인가 (FR-7.1).

        수신 파일 폴더는 없어도 동작한다 (첨부 이름만 기록). 쪽지 폴더와 인박스만 필수.
        """
        return bool(self.coolm.memo_dir.strip() and self.inbox.root_dir.strip())

    def problems(self) -> list[str]:
        """설정 저장 시 사용자에게 보여줄 문제 목록. 비어 있으면 정상 (FR-6.7)."""
        out: list[str] = []
        memo = self.coolm.memo_dir.strip()
        if not memo:
            out.append("쿨메신저 쪽지 폴더를 지정해 주세요.")
        elif not Path(memo).is_dir():
            out.append(f"쿨메신저 쪽지 폴더가 없습니다: {memo}")
        recv = self.coolm.recv_file_dir.strip()
        if recv and not Path(recv).is_dir():
            out.append(f"쿨메신저 수신 파일 폴더가 없습니다: {recv}")
        root = self.inbox.root_dir.strip()
        if not root:
            out.append("인박스 폴더를 지정해 주세요.")
        elif not Path(root).is_dir():
            out.append(f"인박스 폴더가 없습니다: {root}")
        elif not os.access(root, os.W_OK):
            out.append(f"인박스 폴더에 쓸 수 없습니다: {root}")
        return out


# ---------------------------------------------------------------- 내부 도구

def _int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: Any, lo: int, hi: int, default: int) -> int:
    return min(hi, max(lo, _int(v, default)))


def _backup_broken(p: Path) -> None:
    """깨진 설정 파일을 덮어쓰기 전에 옆에 치워 둔다 (사용자가 되살릴 수 있게)."""
    try:
        p.replace(p.with_name(p.name + ".broken"))
    except OSError as e:
        log.warning("깨진 설정 파일을 백업하지 못했습니다: %s", e)


def _coerce(value: Any, typ: Any, default: Any) -> Any:
    """JSON 값을 dataclass 필드 타입에 맞춘다. 못 맞추면 기본값."""
    if typ is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(value, (int, float)):
            return bool(value)
        return default
    if typ is int:
        if isinstance(value, bool):     # bool 은 int 의 하위형이라 먼저 걸러낸다
            return default
        return _int(value, default)
    if typ is str:
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return str(value)
        return default
    return value if isinstance(value, type(default)) else default


def _from_dict(cls: type, data: dict) -> Any:
    """dataclass 를 dict 에서 만든다. 모르는 키는 무시, 빠진 키는 기본값."""
    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        typ = hints.get(f.name, str)
        default = f.default_factory() if f.default_factory is not MISSING else f.default
        if is_dataclass(typ):
            sub = data.get(f.name)
            kwargs[f.name] = _from_dict(typ, sub) if isinstance(sub, dict) else default
        elif f.name in data:
            kwargs[f.name] = _coerce(data[f.name], typ, default)
    return cls(**kwargs)
