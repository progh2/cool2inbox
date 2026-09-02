"""로깅 설정 (FR-9.1, FR-9.2).

**쪽지 본문과 제목은 로그에 남기지 않는다.** 로그는 캡처되고 공유되기 쉽다.
남겨도 되는 것: MessageKey, 보낸 사람, 시각, 저장한 파일명, 건수, 오류 사유.

회전 파일 1MB × 3. 위치는 설정 디렉터리 (트레이 메뉴 '로그 보기' 로 연다).
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src import config as cfg

LOG_NAME = "cool2inbox.log"
MAX_BYTES = 1024 * 1024
BACKUPS = 3
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def log_path() -> Path:
    return cfg.config_dir() / LOG_NAME


def setup_logging(level: int = logging.INFO, to_stderr: bool = True) -> Path:
    """루트 로거를 설정한다. 여러 번 불러도 핸들러가 겹치지 않는다."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()

    p = log_path()
    fmt = logging.Formatter(FORMAT)
    try:
        fh = RotatingFileHandler(p, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as e:                    # 디스크 가득·권한 없음 — 콘솔만으로 계속 간다
        print(f"로그 파일을 열 수 없습니다 ({p}): {e}", file=sys.stderr)

    if to_stderr:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    logging.getLogger(__name__).debug("로깅 시작: %s", p)
    return p
