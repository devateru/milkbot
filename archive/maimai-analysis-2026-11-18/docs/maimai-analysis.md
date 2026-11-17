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

기존 서비스로 실행하는 경우 작업 디렉터리를 저장소 루트로 지정하고, 위 가상환경의 Python으로 `bot.py`를 실행합니다. `.env`에 기존 봇의 `DISCORD_TOKEN`과 `BOT_DEVELOPER_ID`를 설정합니다. 봇과 분석 작업은 같은 프로세스에서 실행합니다. YouTube 영상 입력은 yt-dlp로 열며, YouTube Data API 키는 기존 `/겜플라이브`에서 사용합니다.

YouTube 스트림을 받으려면 봇의 실행 환경에서 yt-dlp가 지원하는 Deno 또는 Node.js를 사용할 수 있게 설정합니다. Deno의 절대 경로는 `MAIMAI_YOUTUBE_DENO`로 지정할 수 있습니다. 스트림 추출이 실패하면 봇의 가상환경에서 `python -m pip install -U 'yt-dlp[default]>=2026.10.21'`을 실행한 뒤 `python -m yt_dlp --version`을 확인하고 서비스를 재시작합니다. `2026.10.21`은 Ubuntu 22.04 기본 Python 3.10에 설치되는 버전입니다. 추출 실패가 계속되면 봇 로그의 `maimai YouTube resolve failed` 줄에서 영상 ID, 사용 중인 yt-dlp 버전, YouTube의 응답을 확인합니다. [yt-dlp 런타임 설정](https://github.com/yt-dlp/yt-dlp/wiki/EJS)

YouTube가 서버에 로그인 확인을 요구하면 관리자가 YouTube 전용 Netscape 쿠키 파일을 지정할 수 있습니다. yt-dlp는 계정에 제한이 생길 수 있다고 안내하므로, 이 방식이 필요하면 본계정과 분리된 계정의 세션을 사용합니다. 파일은 봇 서비스 계정 소유로 저장소 밖에 보관하고 `chmod 600`을 적용합니다. 서버의 `.env`에 `MAIMAI_YOUTUBE_COOKIES=/home/ubuntu/.config/milkbot/youtube-cookies.txt`처럼 파일 경로를 설정하고 봇을 재시작합니다. 로그인 확인이 계속되면 YouTube가 그 서버에서 해당 세션을 받아들이는지 확인해야 합니다. [yt-dlp의 YouTube 인증 안내](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)

서버에서 YouTube 영상을 읽기 어렵다면 Windows PC에서 `python -m maimai_analysis.vod_relay --ssh-host ubuntu@서버 --ssh-key 키경로`를 실행합니다. PC의 Python 환경에는 `requests`, `yt-dlp[default]`, FFmpeg가 필요합니다. FFmpeg가 PATH에 없으면 `imageio-ffmpeg`로 제공할 수 있습니다. PC 실행 환경과 Ubuntu `.env`에 같은 `MAIMAI_VOD_RELAY_TOKEN`을 설정하고, Ubuntu에 `MAIMAI_VOD_RELAY_PORT=18765`를 추가한 뒤 봇을 재시작합니다. Ubuntu는 PC에서 다시보기와 라이브 프레임을 원본 영상 시각과 함께 받아 분석합니다. 다시보기는 2분씩 읽고, 전송이 멈추면 마지막으로 받은 시각부터 해당 구간을 다시 요청합니다. 새 요청에서 PC에 연결할 수 없으면 Ubuntu에서 YouTube에 직접 연결을 시도합니다.

| 환경 변수 | 기본값 | 용도 |
| --- | --- | --- |
| `MAIMAI_ANALYSIS_DB` | `data/maimai-analysis.sqlite3` | 재시작 후에도 유지되는 파일 경로 |
| `MAIMAI_FPS` | `8` | 디코딩한 영상에서 가져오는 초당 표본 |
| `MAIMAI_WIDTH` / `MAIMAI_HEIGHT` | `1280` / `720` | FFmpeg 출력 및 입력 스트림 높이 상한 |
| `MAIMAI_OCR_LANG` | `eng+jpn+kor` | Tesseract 언어 |
| `MAIMAI_FFMPEG` | `ffmpeg` | FFmpeg 실행 파일 경로 |
| `MAIMAI_VISION_PROFILE` | | 기본 1인 화면과 다른 방송에 맞춘 JSON 경로 |

SQLite는 WAL 모드로 동작합니다. 백업에는 SQLite의 온라인 백업을 사용하거나 봇을 종료한 뒤 DB와 남아 있는 WAL 파일을 함께 복사합니다. 일반 디코딩은 영상 파일을 저장하지 않고 메모리와 파이프로 전달합니다.

## Discord에서 사용하기

1. `/목표설정`의 `곡`에 `Credits` 또는 `[ST] Credits`처럼 직접 입력할 수 있습니다. 같은 제목의 ST와 DX가 모두 있으면 제목 앞에 `[ST]` 또는 `[DX]`를 붙입니다. `구간목표`에 `100개:-0.1, 나머지:-0.05`를 입력하면 첫 100노트는 0.1%p, 이후는 0.05%p의 허용 감점으로 즉시 저장합니다. 시작 노트 번호를 쓰려면 `1:-0.1, 101:-0.05`를 입력합니다. 각 구간은 쉼표, 줄바꿈 또는 공백으로 구분합니다. 난이도 기본값은 MASTER이고 `채보링크`는 자동 조회합니다. `구간목표`를 비우면 기존 목표를 보거나 **구간 편집** 버튼으로 수정할 수 있습니다.
2. `/구간확인`은 영상 링크와 `02:10, 02:42.500, 03:17`처럼 여러 시각을 받아 해당하는 노트 번호를 보여줍니다. 목표 등록 없이 사용합니다. 원형 플레이 화면만 있는 채보 캡처도 자동 동기화할 수 있습니다. 원형 판정선이 보이는 첫 플레이 구간을 포함하고 원래 재생 속도로 올린 영상을 사용합니다. 노트 패턴이 충분히 일치하지 않거나 스트림을 열 수 없으면 `첫노트시간`에 첫 노트의 영상 시각을 입력합니다. 이 값을 입력하면 YouTube 스트림을 열지 않고 계산합니다.
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
- `/구간확인`에서는 원형 판정선 주변에 나타나는 여러 노트의 위치와 영상 시각을 simai의 초반 레인 및 노트 간격과 대조할 수 있습니다. 여러 기준 시각이 비슷하게 일치하면 수동 입력을 안내합니다.
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

라이브 DVR의 0번 세그먼트가 있으면 프로그램 시각을 기준점으로 사용합니다. 앞부분이 잘렸다면 수신기가 보고한 방송 시작 시각과 YouTube Data API의 실제 시작 시각이 일치할 때 공개된 구간을 사용합니다. 기준을 확인할 수 없거나 명시한 시각이 공개 구간 밖이면 오류를 표시합니다. 연결이 끊기면 최신 공개 프레임으로 재연결합니다. 현재 시점부터 보기 시작한 방송은 처리 대기 중인 세그먼트가 최신 세그먼트보다 두 개 이상 뒤처지면 최신 세그먼트로 건너뜁니다.

건너뛴 뒤 같은 자리에서 이어지는 채보를 최대 20초 시차 안에서 확인하면 같은 판으로 기록합니다. 양쪽 구간 경계의 누적 달성률이 있으면 중간 프레임 유실 후에도 감점량을 계산합니다. 유실 때문에 경계 점수를 확인할 수 없는 구간은 `영상 유실로 분석 불가`로 표시합니다.

영상 입력을 사용하는 분석은 한 번에 하나만 실행합니다. 새 분석을 요청하면 기존 작업을 요청한 사람이 **중단하고 시작** 또는 **현재 작업 유지**를 선택할 수 있습니다. 같은 분석을 공유 중이라면 중단은 그 분석의 모든 참가자에게 적용됩니다. 자동 `/구간확인`이 시간 초과되면 프레임 읽기를 정리하고 다음 작업이 슬롯을 사용할 수 있게 합니다.

SQLite에는 닉네임, 목표, 검증한 채보만 저장합니다. 플레이, 점수 관측, 작업과 DM 갱신 정보는 분석 실행 중 메모리에 둡니다. 봇이 재시작되거나 완료된 영상을 다시 분석하려면 명령을 새로 실행합니다. 이미 발송한 Discord 메시지는 DM에서 볼 수 있습니다.

`maimai resources` 로그에 CPU와 프로세스 RSS, `maimai decode` 로그에 처리한 영상 길이와 실제 경과 시간이 나옵니다. Ubuntu 봇의 Tesseract 스레드 기본값은 `OMP_THREAD_LIMIT=1`입니다. `maimai DM`의 `youtube_seconds`는 결과 화면의 캡처 시각 또는 HLS 프로그램 시각과 결과 프레임 도착 시각의 차이입니다. `result_wait_seconds`는 플레이 화면 종료 표식에서 결과 화면이 나올 때까지의 시간이며, `processing_dm_seconds`는 결과 프레임 도착부터 DM 반영까지 걸린 시간입니다. 합계인 `total_seconds`를 20초 목표와 비교합니다.

## 검증

```sh
python -m unittest discover -s tests -p 'test_maimai*.py' -v
python -m unittest discover -s tests -v
```

Credits MASTER의 733노트와 BIRTH·宙天의 실제 채보를 읽어 manifest와 대조했습니다. 게임플라자 공개 영상의 프로필 화면, 라이브 DVR의 점수와 판정 카운터, HLS 세그먼트의 타임라인을 확인했습니다. 테스트의 `tests/fixtures/maimai-gameplaza-rois.pgm`에는 점수 숫자와 판정 카운터 영역만 들어 있습니다. 실 Discord 계정에 발송하는 작업과 Oracle 서버에서 20초 목표를 달성하는지 확인하는 작업은 아직 필요합니다. [검증한 다시보기](https://www.youtube.com/watch?v=lxMVGRpRHiM) · [검증한 라이브](https://www.youtube.com/watch?v=NvCoTWtRJH0)

별도 다시보기에서 좌우 자리 표식과 첫 판의 `GUEST`·레이팅 0 OCR을 확인했습니다. 좌우에 서로 다른 점수를 넣은 화면으로 선택한 자리의 점수만 추적하는 경로를 자동 테스트했습니다. 2P 실경기의 처음부터 끝까지 구간 평가와 DM 전달을 연결하는 검증은 아직 필요합니다. [게스트와 좌우 배치 검증 영상](https://www.youtube.com/watch?v=OmgjyveF12Q)
