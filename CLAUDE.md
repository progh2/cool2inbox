# cool2inbox — 프로젝트 지침

쿨메신저 받은 쪽지를 마크다운 1건/1파일로 만들어 드롭박스 인박스에 적재하는 Windows 트레이 앱.
마스코트는 펭귄 배달부. GUI는 PySide6.

## 개발 규칙
- **이슈 단위 작업** — 사용자 요청은 먼저 이슈로 등록하고, 커밋 메시지에 `<type>: 설명 (closes #N)`
- 마일스톤 v0.1 → v1.0 순서대로. 마일스톤을 건너뛰지 않는다
- **원본 무손상 원칙**: 쿨메신저 udb·수신 파일에 대한 쓰기 코드는 존재해서는 안 된다. 반드시 임시 복사 후 `mode=ro`
- **로그에 쪽지 본문·제목을 남기지 않는다** (키·발신자·시각·파일명까지)
- `.udb`, 실제 쪽지 샘플, 스키마 덤프는 절대 커밋하지 않는다 (`.gitignore` 확인)
- 워커 스레드에서 GUI를 직접 건드리지 않는다 — `QTimer.singleShot(0, ...)` 으로 메인 스레드에 넘긴다
  (catmoa #52에서 똑같이 당했다)
- 순수 Python wheel 의존성만 (PyInstaller 단일 exe 빌드 때문)
- 파일 쓰기는 원자적으로 (`.tmp` → `os.replace`) — 드롭박스 부분 동기화 방지
- 테스트: `pytest`. 쿨메신저 없이도 돌도록 `create_fake_udb()` 사용
- 상세 요구사항·UML·결정 기록은 `docs/PRD.md`

## 참고 코드
- [progh2/catmoa](https://github.com/progh2/catmoa) `src/sources/coolm.py` — udb 리더, `split_recent()`,
  `default_memo_dir()`, `create_fake_udb()`. `src/single_instance.py`, `src/autostart.py`, `src/ui/tray.py` 도 이식 대상
- [dacisosl/coolm-helper](https://github.com/dacisosl/coolm-helper) (MIT) — udb 접근 방식 원출처

## 컨텍스트 앵커
- intent: 기획 완료, **개발 착수 전 승인 대기**. README + PRD 작성, 저장소·마일스톤·이슈 등록까지 완료
- **최우선 미해결(R1)**: 받은 쪽지의 **수신자 목록**과 **첨부파일 메타데이터**가 udb 어느 테이블/컬럼에 있는지 미확인.
  catmoa는 `MessageKey/Sender/ReceiveDate/Title/MessageText` 만 읽었다. 쿨메신저 **수신 파일 저장 폴더** 위치도 미확인(R2).
  → v0.2 첫 작업으로 `tools/dump_coolm_schema.py` 를 만들어 사용자가 Windows에서 실행 → 결과로 스키마 확정
- decisions: 출력 `.md` + YAML 머리말 / 파일명 `날짜_시각_보낸사람_제목_#키.md` / 첨부는 쪽지별 하위 폴더 /
  드롭박스 API 미사용(로컬 동기화 폴더에 쓰기만) / 받은 쪽지만(보낸 쪽지는 v2) / 마스코트는 AI 생성 이미지
- 개발 환경: 코딩은 Linux 세션, 실사용 검증은 사용자의 Windows PC
- next_steps: 사용자 승인 → v0.1 골격(설정·상태DB·트레이) → v0.2 스키마 덤프로 R1 해소 → v0.3 쓰기
