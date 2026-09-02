"""설정 저장/복원 (#2).

관대한 로드가 핵심이다 — 사용자가 손으로 고친 JSON, 구버전 키, 깨진 파일 어느 것도
프로그램을 못 뜨게 만들면 안 된다.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.config import (DEFAULT_FILENAME_FORMAT, POLL_MAX, POLL_MIN, Config,
                        config_dir, config_path)


# ---------------------------------------------------------------- 기본값

def test_기본값():
    c = Config()
    assert c.schedule.poll_minutes == 5           # PRD 기본 5분
    assert c.schedule.max_per_poll == 50
    assert c.schedule.paused is False
    assert c.schedule.notify is True
    assert c.inbox.coolm_folder_name == "쿨메신저"
    assert c.inbox.attach_folder_name == "첨부파일"
    assert c.inbox.max_attach_mb == 200
    assert c.coolm.attach_match_minutes == 30
    assert c.coolm.last_message_key == 0
    assert c.output.filename_format == DEFAULT_FILENAME_FORMAT
    assert c.output.split_quoted is True
    assert c.ui.first_run_done is False


def test_설정_디렉터리는_환경변수를_따른다(isolated_config_dir):
    assert config_dir() == isolated_config_dir
    assert config_path() == isolated_config_dir / "config.json"


# ---------------------------------------------------------------- 왕복

def test_저장_로드_왕복():
    c = Config()
    c.coolm.memo_dir = r"C:\Users\me\AppData\Local\CoolMessenger\Memo"
    c.coolm.last_message_key = 1076
    c.inbox.root_dir = r"D:\Dropbox\Inbox"
    c.schedule.poll_minutes = 10
    c.schedule.paused = True
    c.output.filename_format = "{date}_{sender}"
    c.ui.last_check_at = "2026-09-02 17:04"
    c.save()

    got = Config.load()
    assert got == c


def test_저장은_원자적이고_tmp를_남기지_않는다():
    Config().save()
    names = {p.name for p in config_path().parent.iterdir()}
    assert names == {"config.json"}


def test_저장_파일은_사람이_읽을_수_있는_UTF8_JSON():
    c = Config()
    c.inbox.root_dir = "/tmp/인박스"
    p = c.save()
    text = p.read_text(encoding="utf-8")
    assert "쿨메신저" in text          # 한글이 이스케이프되지 않는다
    assert json.loads(text)["inbox"]["root_dir"] == "/tmp/인박스"


def test_파일이_없으면_기본값():
    assert Config.load() == Config()


# ---------------------------------------------------------------- 관대한 로드

def test_모르는_키는_무시한다():
    config_path().write_text(json.dumps({
        "schedule": {"poll_minutes": 7, "미래에_생길_설정": True},
        "완전히_모르는_섹션": {"x": 1},
    }), encoding="utf-8")
    c = Config.load()
    assert c.schedule.poll_minutes == 7
    assert c.schedule.max_per_poll == 50          # 빠진 키는 기본값


def test_섹션이_통째로_빠져도_기본값():
    config_path().write_text(json.dumps({"coolm": {"memo_dir": "/x"}}), encoding="utf-8")
    c = Config.load()
    assert c.coolm.memo_dir == "/x"
    assert c.inbox == Config().inbox
    assert c.output == Config().output


def test_타입이_어긋나면_기본값이나_변환():
    config_path().write_text(json.dumps({
        "schedule": {"poll_minutes": "9", "paused": "true", "notify": 0},
        "inbox": {"max_attach_mb": None, "root_dir": 123},
    }), encoding="utf-8")
    c = Config.load()
    assert c.schedule.poll_minutes == 9           # "9" → 9
    assert c.schedule.paused is True              # "true" → True
    assert c.schedule.notify is False             # 0 → False
    assert c.inbox.max_attach_mb == 200           # None → 기본값
    assert c.inbox.root_dir == "123"              # 123 → "123"


def test_bool_자리에_bool을_넣어도_int로_새지_않는다():
    config_path().write_text(json.dumps({"schedule": {"max_per_poll": True}}), encoding="utf-8")
    assert Config.load().schedule.max_per_poll == 50


def test_섹션이_dict가_아니면_기본값():
    config_path().write_text(json.dumps({"inbox": "이건 문자열"}), encoding="utf-8")
    assert Config.load().inbox == Config().inbox


def test_깨진_JSON은_기본값에_백업본을_남긴다():
    config_path().write_text("{ 이건 JSON 이 아니다 ", encoding="utf-8")
    assert Config.load() == Config()
    assert config_path().with_name("config.json.broken").exists()


def test_최상위가_dict가_아니면_기본값():
    config_path().write_text("[1, 2, 3]", encoding="utf-8")
    assert Config.load() == Config()


# ---------------------------------------------------------------- 정규화

def test_주기는_허용_범위로_잘린다():
    c = Config()
    c.schedule.poll_minutes = 0
    c.normalize()
    assert c.schedule.poll_minutes == POLL_MIN
    c.schedule.poll_minutes = 9999
    c.normalize()
    assert c.schedule.poll_minutes == POLL_MAX


def test_로드할_때도_정규화된다():
    config_path().write_text(json.dumps({"schedule": {"poll_minutes": 9999}}), encoding="utf-8")
    assert Config.load().schedule.poll_minutes == POLL_MAX


def test_폴더명이_비면_기본값으로_되돌린다():
    c = Config()
    c.inbox.coolm_folder_name = "   "
    c.inbox.attach_folder_name = ""
    c.output.filename_format = "  "
    c.normalize()
    assert c.inbox.coolm_folder_name == "쿨메신저"
    assert c.inbox.attach_folder_name == "첨부파일"
    assert c.output.filename_format == DEFAULT_FILENAME_FORMAT


def test_음수는_0으로():
    c = Config()
    c.coolm.last_message_key = -5
    c.inbox.max_attach_mb = -1
    c.coolm.attach_match_minutes = -10
    c.normalize()
    assert c.coolm.last_message_key == 0
    assert c.inbox.max_attach_mb == 0             # 0 = 무제한
    assert c.coolm.attach_match_minutes == 0


# ---------------------------------------------------------------- 경로 조립

def test_인박스_경로_조립():
    c = Config()
    c.inbox.root_dir = "/dropbox/Inbox"
    assert c.inbox.coolm_dir() == Path("/dropbox/Inbox/쿨메신저")
    assert c.inbox.attach_dir() == Path("/dropbox/Inbox/쿨메신저/첨부파일")


def test_폴더명을_바꾸면_경로도_따라간다():
    c = Config()
    c.inbox.root_dir = "/x"
    c.inbox.coolm_folder_name = "CoolMessenger"
    c.inbox.attach_folder_name = "files"
    assert c.inbox.attach_dir() == Path("/x/CoolMessenger/files")


# ---------------------------------------------------------------- 설정 완료 판정

def test_is_configured():
    c = Config()
    assert not c.is_configured()
    c.coolm.memo_dir = "/memo"
    assert not c.is_configured()
    c.inbox.root_dir = "/inbox"
    assert c.is_configured()
    c.coolm.memo_dir = "   "                      # 공백만 있으면 미설정
    assert not c.is_configured()


def test_수신_파일_폴더는_없어도_설정_완료():
    c = Config()
    c.coolm.memo_dir, c.inbox.root_dir = "/memo", "/inbox"
    assert c.coolm.recv_file_dir == ""
    assert c.is_configured()


# ---------------------------------------------------------------- 문제 안내

def test_problems_빈_설정():
    msgs = Config().problems()
    assert any("쪽지 폴더" in m for m in msgs)
    assert any("인박스 폴더" in m for m in msgs)


def test_problems_정상이면_비어있다(tmp_path):
    c = Config()
    c.coolm.memo_dir = str(tmp_path)
    c.inbox.root_dir = str(tmp_path)
    assert c.problems() == []


def test_problems_없는_폴더를_짚어준다(tmp_path):
    c = Config()
    c.coolm.memo_dir = str(tmp_path / "없음")
    c.inbox.root_dir = str(tmp_path)
    c.coolm.recv_file_dir = str(tmp_path / "이것도없음")
    msgs = c.problems()
    assert any("쪽지 폴더가 없습니다" in m for m in msgs)
    assert any("수신 파일 폴더가 없습니다" in m for m in msgs)
