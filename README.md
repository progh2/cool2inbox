# cool2inbox 🐧📮

**[📖 소개 페이지 보기](https://progh2.github.io/cool2inbox/)** · **[⬇︎ 내려받기](../../releases/latest)**

> **쿨메신저 쪽지를 드롭박스 인박스로 배달하는 펭귄.**
> 쪽지 1건 = 마크다운 파일 1개. 첨부파일까지 통째로.

<p align="center">
  <img src="assets/penguin/idle.png" width="140" alt="cool2inbox 마스코트 — 가방 멘 펭귄 배달부">
</p>

<p align="center">
  <img src="assets/penguin/idle.png" width="56" alt="대기">
  <img src="assets/penguin/working.png" width="56" alt="배달 중">
  <img src="assets/penguin/paused.png" width="56" alt="일시정지">
  <img src="assets/penguin/error.png" width="56" alt="오류">
  <img src="assets/penguin/setup.png" width="56" alt="설정 필요">
  <br>
  <sub>대기 · 배달 중 · 일시정지 · 오류 · 설정 필요</sub>
</p>

> **현재 상태: v0.9.0 테스트 릴리스 공개.** [릴리스](../../releases/latest)에서 `cool2inbox.exe` 를 받아 실행할 수 있습니다.
> 기능은 완성됐고 테스트 416개 통과, CI 초록불입니다. Windows 실기기 검증([#24](../../issues/24))이 끝나면 1.0.0 으로 정식 릴리스합니다.
>
> 실제 데이터로 검증했습니다 — 쪽지 **1,076건 → 마크다운 1,075개, 실패 0건, 0.9초**.
> 재실행해도 중복 0건. 쿨메신저 원본 폴더는 해시까지 그대로였습니다.

---

## 무엇을 해결하나요?

쿨메신저로 오는 쪽지는 메신저 안에 갇혀 있습니다.

- 검색이 불편하고, 백업되지 않습니다.
- PC를 옮기면 과거 쪽지가 통째로 사라지기도 합니다.
- 옵시디언·인박스·AI 도구에서 쓰려면 매번 손으로 복사해야 합니다.
- 첨부파일은 다른 폴더에 흩어져, 나중엔 어느 쪽지의 파일이었는지 알 수 없습니다.

**cool2inbox**는 트레이에 조용히 상주하면서 새 쪽지를 마크다운으로 바꿔 드롭박스 인박스에 넣어 둡니다.
드롭박스가 알아서 동기화하니 사용자가 할 일은 없습니다.

## 핵심 기능

| | 기능 | 설명 |
|---|---|---|
| 🐧 | **트레이 상주** | 창 없이 트레이에만. 우클릭으로 모든 조작 |
| ⏱ | **주기적 확인** | 기본 5분 (1~120분 설정 가능) |
| 📝 | **쪽지 → 마크다운** | 제목·보낸 사람·보낸 시각·받는 사람 목록·본문·첨부파일명까지 담은 `.md` 파일 1개 |
| 📎 | **첨부파일 함께 저장** | 쪽지별 하위 폴더로 **복사**(원본은 그대로)하고 본문에서 상대 링크로 연결. 쿨메신저에서 첨부를 열어 받으면 다음 확인 때 자동으로 붙습니다 |
| 🔁 | **중복 없음** | 쪽지 고유번호 + 내용 해시 + 인박스 실사, 3중 판정 |
| 📚 | **이전 쪽지 전부 가져오기** | 몇 년치 이력도 한 번에. 진행률 표시, 취소 가능, 이미 있는 건 건너뜀 |
| ⏸ | **일시정지 / 재개** | 트레이에서 바로. 재개하면 밀린 쪽지를 한 번에 배달 |
| 🧙 | **첫 실행 마법사** | 쿨메신저 폴더·드롭박스 폴더를 자동으로 찾아 제안 |
| 📤 | **보낸 쪽지도 (선택)** | 설정에서 켜면 내가 보낸 쪽지도 `보낸쪽지` 폴더에 따로 저장합니다 |
| 🔒 | **원본 무손상** | 쿨메신저 DB와 수신 파일은 **읽기만** 합니다. 쓰기·삭제·이동 없음 |

## 저장되는 모습

```
D:\Dropbox\Inbox\
└── 쿨메신저\
    ├── 2026-09-02_1704_홍길동_2학기_교육과정_협의회_#1234.md
    ├── 2026-09-02_1830_김철수_무제_#1235.md
    └── 첨부파일\
        └── 2026-09-02_1704_홍길동_#1234\
            ├── 협의회자료.hwp
            └── 참석자명단.xlsx
```

파일 하나를 열면 이렇게 생겼습니다.

```markdown
---
source: coolmessenger
message_key: 1234
title: 2학기 교육과정 협의회
sender: 홍길동
received: 2026-09-02 17:04:52
received_weekday: 화
recipients: [김철수, 이영희, …]
recipient_count: 27
attachments: [협의회자료.hwp, 참석자명단.xlsx]
imported_at: 2026-09-02 17:10:03
---

# 2학기 교육과정 협의회

내일 오후 3시 시청각실에서 2학기 교육과정 협의회를 진행합니다.
첨부된 자료를 미리 읽어 오세요.

## 첨부파일

- [협의회자료.hwp](첨부파일/2026-09-02_1704_홍길동_#1234/협의회자료.hwp)
```

본문은 **가공하지 않습니다.** 요약도, 마스킹도, 재배치도 없습니다. 인박스는 원본 아카이브니까요.

## 설정할 수 있는 것

- **폴더** — 쿨메신저 쪽지 폴더 / 쿨메신저 수신 파일 폴더 / 인박스 루트 / 쿨메신저 폴더명 / 첨부파일 폴더명
- **주기** — 확인 간격(기본 5분), 1회 최대 처리 건수, Windows 시작 시 자동 실행, 알림 표시
- **출력** — 파일명 서식(`{date}` `{time}` `{sender}` `{title}` `{key}`), 머리말 항목, 인용된 이전 대화 분리
- **가져오기** — 이전 쪽지 모두 가져오기 / 인박스에서 이력 다시 읽기 / 이력 초기화

## 동작 방식

트레이 앱이 주기마다 쿨메신저의 로컬 쪽지 DB(`%LOCALAPPDATA%\CoolMessenger\Memo\*.udb`, 암호화 없는 SQLite)를
**임시 폴더에 복사한 뒤 읽기 전용으로** 열어 새 쪽지만 가져옵니다. 원본은 손대지 않습니다.

자세한 흐름(시퀀스·상태·클래스 다이어그램)은 **[PRD의 동작 UML](docs/PRD.md#6-동작-uml)** 을 보세요.

## 기술 스택

- **Python 3.11+ / PySide6** — 시스템 트레이, 설정 창, 마법사
- **표준 라이브러리** — `sqlite3`(udb 읽기·중복 이력), `pathlib`, `shutil`
- **platformdirs** — OS별 설정 디렉터리
- **PyInstaller** — Windows 단일 exe 배포 (GitHub Actions 자동 빌드)
- 외부 바이너리 의존성 없음 (순수 Python wheel만)

## 개발

개발은 Linux/macOS에서, 검증은 Windows에서 합니다.
쿨메신저가 없는 환경에서도 **가짜 udb 생성기**로 전 기능 테스트가 돌아갑니다.

### 내려받아 쓰기

[릴리스](../../releases)에서 `cool2inbox.exe` 를 받아 실행하면 됩니다. Python 설치가 필요 없습니다.
처음 실행하면 마법사가 쿨메신저 폴더와 드롭박스 인박스를 자동으로 찾아 제안합니다.

> Windows SmartScreen 경고가 뜨면 **추가 정보 → 실행**을 눌러 주세요. 코드 서명 인증서가 없어 생기는 경고입니다.

### 소스에서 실행하기

```bash
git clone https://github.com/progh2/cool2inbox.git
cd cool2inbox
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py          # 실행
pytest                  # 테스트
```

리눅스에서 Qt GUI 를 띄우려면 시스템 라이브러리가 필요합니다 (헤드리스 서버·컨테이너에서 자주 빠져 있습니다).

```bash
sudo apt install libxkbcommon0 libegl1 libgl1        # Debian/Ubuntu
export QT_QPA_PLATFORM=offscreen                     # 화면 없는 환경에서 테스트할 때
```

없어도 GUI 를 쓰지 않는 테스트는 전부 돌아갑니다 — `qapp` 픽스처가 알아서 건너뜁니다.

배포용 실행 파일은 `python build.py` 로 만듭니다 (`pip install -r requirements-dev.txt` 필요).
Windows exe 는 `v*` 태그를 붙이면 GitHub Actions 가 만들어 릴리스에 첨부합니다.

개발 규칙, 진행 상황, 결정 기록은 [`CLAUDE.md`](CLAUDE.md) 와 [`docs/PRD.md`](docs/PRD.md) 에 있습니다.
작업은 **이슈 단위**로 하고 커밋 메시지에 `(closes #N)` 을 붙입니다.

## 한계와 주의사항

- **Windows 전용 기능입니다.** 쿨메신저가 Windows용이라서요. 코드는 크로스 플랫폼이지만 실사용은 Windows입니다.
- 쿨메신저 버전이 바뀌어 DB 구조가 달라지면 동작하지 않을 수 있습니다. 그때는 오류 대신 안내 메시지가 뜹니다.
- 받은 쪽지만 가져옵니다. 보낸 쪽지는 v2.0 예정입니다.
- 쪽지 본문은 로그에 남기지 않지만, **저장되는 파일은 드롭박스로 동기화됩니다.**
  업무 쪽지의 외부 클라우드 동기화가 조직 규정에 어긋나지 않는지 먼저 확인하세요.
- 이 프로그램은 쿨메신저를 **읽기만** 합니다. 쪽지를 보내거나, 읽음 처리하거나, 삭제하지 않습니다.

## 라이선스와 참고

MIT License. © 2026 Gihun Ham

- 쿨메신저 `.udb` 읽기 방식은 [dacisosl/coolm-helper](https://github.com/dacisosl/coolm-helper) (MIT) 와
  [progh2/catmoa](https://github.com/progh2/catmoa) (MIT) 를 참고했습니다.
- 쿨메신저는 각 제작사의 상표이며, 이 프로젝트는 해당 제작사와 무관합니다.
