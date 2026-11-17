# maimai 영상·라이브 분석 보관본

2026-11-18 사용자 요청으로 운영을 중단했습니다. 당시 구현과 테스트를 다시 검토할 수 있도록 이 폴더에 보관합니다. 기준 커밋은 `aa43e6e598249ffe22977598b2362d7466308b0a`입니다. 마지막으로 로컬에서 수정한 C 등급 결과 화면 탐지와 회귀 테스트도 포함합니다. 그 수정은 운영에 배포하기 전에 보관했습니다.

## 보관한 항목

- `maimai_analysis/`에 simai 파서, mai-notes 연동, 영상 수신, OCR, 좌우 플레이 추적, 점수 평가, Discord 명령과 DM 보고서 코드가 있습니다.
- `bot.py`는 당시 봇 통합 상태의 스냅샷입니다.
- `tests/`에 분석 자동 테스트와 실제 화면에서 추출한 최소 영역 이미지가 있습니다.
- `requirements-maimai.txt`와 `requirements.txt`에 당시 Python 의존성이 있습니다.
- `docs/maimai-analysis.md`에 기존 명령 설명, 설치 방법, 환경 변수와 검증 기록이 있습니다.

중단한 명령은 `/목표설정`, `/구간확인`, `/영상분석`, `/라이브분석`, `/라이브분석-게스트토글`입니다. 운영 봇에서 명령 등록과 분석 초기화를 제거했습니다. Windows의 `Milkbot Video Relay` 예약 작업도 중지하고 비활성화합니다.

닉네임·목표·채보 캐시 SQLite는 기존 서버의 `data/maimai-analysis.sqlite3` 또는 `MAIMAI_ANALYSIS_DB` 지정 경로에 보존합니다. 인증 파일과 `.env`는 기존 컴퓨터의 비공개 경로에 보존합니다. Discord에 이미 보낸 결과와 요청 기록은 그대로 보존합니다.

## 중단 시점의 문제

실시간 분석에서 Oracle 서버의 OCR 처리 속도가 입력 프레임 속도를 따라가지 못했습니다. 최신 프레임으로 이동하면서 곡 시작이나 게스트 신원 확인 구간을 놓칠 수 있었습니다. `☆ΣΣ` 명찰은 실제 1P 프레임과 2P 크기로 재배치한 샘플에서 확인했습니다. 실제 2P 경기 전체와 DM 보고서를 연결하는 검증은 남아 있습니다.

`Credits` 게스트 플레이의 C 등급 결과 화면을 탐지하지 못하는 문제를 재현했습니다. 보관본에는 반전·이진화한 `TRACK 01` 또는 `TRACK 02` 표식으로 현재 트랙 종료를 확인하는 수정이 포함됩니다. 수정 후 연속 샘플에서는 종료 이벤트가 나왔습니다. 시작 구간을 건너뛴 샘플에서는 플레이 기록을 만들지 못했습니다.

현재 구조에서 게임 종료부터 DM까지 20초 목표는 검증을 완료하지 못했습니다. 다시보기의 느린 소비 중 FFmpeg 연결 리셋과 디코딩 오류도 확인했습니다. 진전이 있으면 재시도 횟수를 초기화하도록 수정한 상태입니다.

## 보관본 테스트

저장소 루트의 공통 곡 검색·배점 모듈을 사용합니다. 분석 의존성과 FFmpeg를 준비한 Python 환경에서 실행합니다. 아래 명령은 분석 봇을 Discord에 연결하지 않고 테스트합니다.

PowerShell에서 저장소 루트부터 실행합니다.

```powershell
$env:PYTHONPATH = (Get-Location).Path
Push-Location archive/maimai-analysis-2026-11-18
python -X utf8 -m unittest discover -s tests -q
Pop-Location
```

Ubuntu에서 저장소 루트부터 실행합니다.

```sh
repo_root="$PWD"
cd archive/maimai-analysis-2026-11-18
PYTHONPATH="$repo_root" "$repo_root/.venv/bin/python" -m unittest discover -s tests -q
```

## 다시 검토할 때

이 폴더의 `bot.py`에서 기존 명령 연결부를 참고하고, 필요한 모듈과 의존성만 운영 코드로 다시 가져옵니다. 현재 운영 `bot.py`와 통합 상태를 비교해서 반영합니다. SQLite 설정과 Windows 중계 설정은 기존 경로를 확인합니다. 운영 복귀 전에는 실제 방송의 곡 시작, 게스트 확인, 좌우 구분, 종료 감지, 구간 점수와 DM 지연을 함께 검증합니다.
