# 게임플라자 maimai 영상 분석

## Ubuntu 22.04 설치

```sh
sudo apt update
sudo apt install -y ffmpeg python3-venv tesseract-ocr tesseract-ocr-eng tesseract-ocr-jpn tesseract-ocr-kor
cd /opt/milkbot
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-maimai.txt
ffmpeg -version
tesseract --list-langs
python bot.py
```

기존 서비스로 실행하는 경우 작업 디렉터리를 저장소 루트로 지정하고, 위 가상환경의 Python으로 `bot.py`를 실행합니다. `.env`에 기존 봇의 `DISCORD_TOKEN`과 `BOT_DEVELOPER_ID`를 설정합니다. 봇과 분석 작업은 같은 프로세스에서 실행합니다. YouTube 영상 입력은 yt-dlp로 열며, YouTube Data API 키는 기존 `/겜플라이브`에서 사용합니다. YouTube가 JavaScript 처리를 요구하는 환경에서는 yt-dlp가 지원하는 Deno를 설치하고 필요하면 절대 경로를 `MAIMAI_YOUTUBE_DENO`에 지정합니다. [yt-dlp 문서](https://github.com/yt-dlp/yt-dlp#dependencies)

| 환경 변수 | 기본값 | 용도 |
| --- | --- | --- |
| `MAIMAI_ANALYSIS_DB` | `data/maimai-analysis.sqlite3` | 재시작 후에도 유지되는 파일 경로 |
| `MAIMAI_MAX_LIVE` | `1` | 동시에 수신할 방송 수 |
| `MAIMAI_FPS` | `8` | 디코딩한 영상에서 가져오는 초당 표본 |
| `MAIMAI_WIDTH` / `MAIMAI_HEIGHT` | `1280` / `720` | FFmpeg 출력 및 입력 스트림 높이 상한 |
| `MAIMAI_OCR_LANG` | `eng+jpn+kor` | Tesseract 언어 |
| `MAIMAI_FFMPEG` | `ffmpeg` | FFmpeg 실행 파일 경로 |
| `MAIMAI_VISION_PROFILE` | | 기본 1인 화면과 다른 방송에 맞춘 JSON 경로 |

SQLite는 WAL 모드로 동작합니다. 백업에는 SQLite의 온라인 백업을 사용하거나 봇을 종료한 뒤 DB와 남아 있는 WAL 파일을 함께 복사합니다. 일반 디코딩은 영상 파일을 저장하지 않고 메모리와 파이프로 전달합니다.

## Discord에서 사용하기

1. `/목표설정`에서 ST/DX 채보를 선택하고 `구간목표`에 `100개:-0.1, 나머지:-0.05`를 입력하면 즉시 저장합니다. 첫 100노트의 허용 감점은 0.1%p, 이후의 허용 감점은 0.05%p입니다. 시작 노트 번호를 쓰려면 `1:-0.1, 101:-0.05`를 입력합니다. 난이도 기본값은 MASTER이고 `채보링크`는 자동 조회합니다. `구간목표`를 비우면 기존 목표를 보거나 **구간 편집** 버튼으로 수정할 수 있습니다.
2. `/구간확인`은 영상 링크와 `02:10, 02:42.500, 03:17`처럼 여러 시각을 받아 해당하는 노트 번호를 보여줍니다. 목표 등록 없이 사용합니다. 자동 동기화가 어려우면 `첫노트시간`에 첫 노트가 판정선에 도달한 영상 시각을 입력합니다.
3. `/영상분석`은 `영상링크`와 선택 옵션 `종료시간`, `플레이어명`, `게스트허용`을 받습니다. 등록된 계정과 일치하는 플레이를 모두 기록하고, 그중 목표를 등록한 곡의 구간 결과를 DM으로 보냅니다. `게스트허용`을 켜면 게스트도 포함합니다. 저장된 닉네임이 없다면 이 옵션으로 게스트만 분석할 수 있습니다.
4. 다시보기에서 YouTube 링크의 `t`가 분석 시작 시각이며 `종료시간`을 생략하면 영상 끝까지 읽습니다. `/라이브분석`은 현재 공개된 구간에서 시작합니다. DVR에 속하는 이전 시각부터 시작하려면 새 분석의 라이브 링크에 `t`를 포함합니다. 필요하면 `곡`과 `난이도`로 라이브를 필터링합니다.
5. `/라이브분석-게스트토글`을 실행하면 내 분석의 다음 판부터 게스트를 포함하거나 제외합니다. 라이브 등록 시 기본값은 제외입니다. 내 분석이 여러 방송에 걸쳐 진행 중이면 변경할 `라이브링크`를 입력합니다.

게스트는 같은 자리의 첫 판에서 이름이 `GUEST`이고 레이팅이 0일 때 판별하고, 해당 크레딧의 후속 곡에서도 인식합니다. 첫 판이 분석 범위에 포함되어야 합니다. 양쪽이 게스트이거나 기록을 받을 사용자를 한 명으로 확인할 수 없는 경우는 개인 기록에서 제외합니다. 2P에서 맞은편 자리에 본인 닉네임이 확인되면 상대 편 게스트도 본인 기록에서 제외합니다.

닉네임 확인에는 프로필 또는 크레딧 중 이름표의 연속 OCR 판독이 필요합니다. 닉네임이 가려지거나 일부만 읽히면 해당 플레이는 내부 기록에 남습니다. ST/DX와 난이도는 기존 곡 목록에서 검증하며, 일치하는 채보를 하나로 좁힐 수 없는 경우 곡 정보 확인 불가로 표시합니다.

## 점수와 시간

- mai-notes manifest와 플레이어 페이지의 `textarea#simaiInput`을 검증하고 원문과 파싱 결과를 캐시합니다. 채보 ID의 곡, 아티스트, 종류, 난이도를 확인하고 유형별 노트 수를 비교합니다. 페이지 구조나 simai 문법이 바뀌어 검증에 실패하면 목표 설정에서 오류를 표시합니다. [Credits MASTER](https://mai-notes.com/player/f4d21b1b-683b-4245-996a-dad171796d60) · [simai 문법](https://w.atwiki.jp/simai/pages/1003.html)
- 노트 번호는 simai에 나타나는 순서입니다. SLIDE의 별 머리가 있는 경우 TAP과 SLIDE를 각각 한 노트로 셉니다. 구간 경계는 동시치기를 나누지 않고, 앞 구간의 HOLD/SLIDE가 판정될 수 있는 시각도 고려합니다. 구간 표시에는 원본과 보정된 시작 번호를 사용하며 마지막 구간은 실제 마지막 번호로 끝납니다.
- 누적 획득량 `(+)`은 유형별 배점과 BREAK 보너스에서 역산합니다. `(-)②`는 관측값의 감소를 사용합니다. 캡처한 점수의 모드, 목표의 앞뒤 값 또는 타이밍을 확인할 수 없으면 해당 구간을 분석 불확실로 표시합니다. 모드 자동 판별에는 시작부의 반복된 `101.0000`이나 `0.0000`에서 시작하는 증가가 필요합니다.
- 자동 동기화는 판정 카운터가 0에서 첫 동시 판정 묶음의 개수로 바뀐 때를 simai의 첫 노트에 맞춥니다. 카운터가 없으면 `(+)`의 첫 증가량과 뒤따르는 패턴을 대조합니다. 첫 판정이 늦게 반영되는 채보나 근거가 부족한 영상은 구간 결과를 분석 불확실로 표시합니다. 분석 중 목표를 수정하면 판이 끝날 때 최신 목표를 적용할 수 있습니다. 완료된 다시보기의 결과를 새 기준으로 확인하려면 `/영상분석`을 다시 실행합니다.
- 영상 링크는 YouTube 타임라인 기준 정수 초입니다. 미달성 구간은 보정된 구간 시작의 2초 전으로 연결합니다. 라이브 시작 메시지의 시계는 서울 시간으로 표시합니다.

## 화면 설정과 운영 확인

게임플라자 1P 레이아웃에서는 상단 스코어보드와 원형 게임 화면을 사용합니다. 2P 레이아웃에서는 왼쪽 `Player 1`과 오른쪽 `Player 2`의 상단 패널에서 이름, 채보 정보, ACHIEVEMENT를 각각 읽습니다. 기본 영역은 게임플라자 화면에 맞춘 값이며 1P 영역은 `MAIMAI_VISION_PROFILE` JSON으로 조정할 수 있습니다. 좌표는 1280×720 기준 `[왼쪽, 위, 오른쪽, 아래]`입니다.

```json
{
  "regions": {
    "title": [201, 155, 477, 169],
    "upper_score": [244, 181, 443, 223],
    "center_score": [782, 307, 1070, 400]
  },
  "modes": {
    "upper_score": "auto",
    "center_score": "auto"
  }
}
```

고정된 방송 설정에서 화면에 실제로 출력되는 점수 모드를 확인했다면 `modes`에 `+` 또는 `-`를 지정할 수 있습니다. 첫 판정을 직접 확인하지 못했을 때 쓸 `chart_origin_offset`은 게임 화면 첫 프레임과 채보 원점의 차이를 여러 샘플로 측정한 환경에만 지정합니다. `origin_error`는 그 보정 오차의 상한(초)입니다. 2P에서는 `seats.left`와 `seats.right`에 자리별 `regions`, `modes`, `chart_origin_offset`, `origin_error`를 설정할 수 있습니다. 판정 카운터 없이 `(-)②`만 표시되는 2P 영상은 검증한 보정값이 있어야 구간을 평가할 수 있습니다.

라이브 DVR에서 0번 세그먼트의 프로그램 시각을 기준점으로 사용합니다. DVR 뒤쪽만 공개되어 기준점을 처음 확보할 수 없거나 요청 시각이 공개 구간 밖이라면 오류를 표시합니다. 다시보기는 한 작업 큐에서 진행하며 라이브 세그먼트를 처리하는 동안 다시보기 소비를 잠시 늦춥니다.

SQLite에는 닉네임, 목표, 검증한 채보만 저장합니다. 플레이, 점수 관측, 작업과 DM 갱신 정보는 분석 실행 중 메모리에 둡니다. 봇이 재시작되거나 완료된 영상을 다시 분석하려면 명령을 새로 실행합니다. 이미 발송한 Discord 메시지는 DM에서 볼 수 있습니다.

`maimai resources` 로그에 CPU와 프로세스 RSS, `maimai decode` 로그에 처리한 영상 길이와 실제 경과 시간이 나옵니다. `maimai DM`의 `youtube_seconds`는 결과 화면의 캡처 시각 또는 HLS 프로그램 시각과 결과 프레임 도착 시각의 차이입니다. `result_wait_seconds`는 플레이 화면 종료 표식에서 결과 화면이 나올 때까지의 시간이며, `processing_dm_seconds`는 결과 프레임 도착부터 DM 반영까지 걸린 시간입니다. 합계인 `total_seconds`를 20초 목표와 비교합니다. Oracle 인스턴스에서 점수를 수집하는 곡을 실제 방송으로 분석한 뒤 용량을 확인하고 `MAIMAI_MAX_LIVE`를 조정합니다.

## 검증

```sh
python -m unittest discover -s tests -p 'test_maimai*.py' -v
python -m unittest discover -s tests -v
```

Credits MASTER의 733노트와 BIRTH·宙天의 실제 채보를 읽어 manifest와 대조했습니다. 게임플라자 공개 영상의 프로필 화면, 라이브 DVR의 점수와 판정 카운터, HLS 세그먼트의 타임라인을 확인했습니다. 테스트의 `tests/fixtures/maimai-gameplaza-rois.pgm`에는 점수 숫자와 판정 카운터 영역만 들어 있습니다. 실 Discord 계정에 발송하는 작업과 Oracle 서버에서 20초 목표를 달성하는지 확인하는 작업은 아직 필요합니다. [검증한 다시보기](https://www.youtube.com/watch?v=lxMVGRpRHiM) · [검증한 라이브](https://www.youtube.com/watch?v=NvCoTWtRJH0)

별도 다시보기에서 좌우 자리 표식과 첫 판의 `GUEST`·레이팅 0 OCR을 확인했습니다. 좌우에 서로 다른 점수를 넣은 화면으로 선택한 자리의 점수만 추적하는 경로를 자동 테스트했습니다. 2P 실경기의 처음부터 끝까지 구간 평가와 DM 전달을 연결하는 검증은 아직 필요합니다. [게스트와 좌우 배치 검증 영상](https://www.youtube.com/watch?v=OmgjyveF12Q)
