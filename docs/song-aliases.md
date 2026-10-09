# 마이마이 곡 대체어 수집

`collect_song_aliases.py`는 밀크봇을 실행하거나 import하지 않는 독립 실행 스크립트입니다.

나무위키 [maimai 시리즈/수록곡](https://namu.wiki/w/maimai%20%EC%8B%9C%EB%A6%AC%EC%A6%88/%EC%88%98%EB%A1%9D%EA%B3%A1)의 곡명 열에서 원제를 가져옵니다. 각 곡 문서의 **문서 이름공간 / redirect 역링크**에서 별칭을 모읍니다. 곡을 언급한 일반 문서, 작곡가 이름, 틀, 사용자 문서는 대체어로 넣지 않습니다. 표에 있는 삭제곡도 포함합니다.

결과는 UTF-8 JSON 리스트입니다. 아래는 형식 예시입니다.

곡명 끝의 `(DX)` / `(STD)`는 제거한 뒤 중복을 합칩니다. 예를 들어 `39`, `39(DX)`, `39 (STD)`는 `39` 한 곡으로 저장하고 한 번만 수집합니다. 리믹스 등 다른 괄호 표기는 유지합니다.

```json
[
  {"title": "Glorious Crown", "aliases": ["글크"]}
]
```

원제는 표에 표시된 곡명을 유지합니다. 나무위키 문서명과 다르면 문서명도 별칭으로 포함합니다. 같은 곡명은 합치고 별칭은 중복 제거 후 정렬합니다. 곡 문서 링크가 없거나 앨범 등의 특정 절(`#...`)로 연결되면 원제만 저장하고 별칭은 빈 리스트로 둡니다. 번역, 발음, 특수 문자 제거 별칭을 자동 생성하지는 않습니다. 리다이렉트에는 리믹스나 다른 버전 제목도 있을 수 있으므로 검색 연동 전에 결과를 검토하세요.

## 준비

Python 3.10 이상에서 저장소 디렉터리를 열고 실행합니다.

```powershell
python -m pip install -r requirements-song-aliases.txt
```

## 실행

```powershell
python collect_song_aliases.py
```

전체 수집 성공 후 스크립트 옆에 `song_aliases.json`을 저장합니다. 토큰이나 `.env` 설정은 필요 없습니다.

일부 곡만 시험 수집하려면:

```powershell
python collect_song_aliases.py --limit 5 --output aliases-preview.json
```

`--limit`를 생략하면 전체 수집합니다. 저장 경로는 `--output`으로 지정합니다. 부분 수집도 지정한 파일을 덮어쓰므로 시험 결과에는 별도 파일명을 쓰세요.

## 재실행 및 오류

기본 요청 간격은 1.5초입니다. 전체 수집은 곡 수에 따라 오래 걸립니다. 완료된 문서별 별칭은 `.song_aliases_cache.json`에 저장되므로 중단 후 같은 명령을 실행하면 이어서 수집합니다. 새로 추가된 별칭까지 다시 확인하려면 `--refresh`를 사용하세요.

```powershell
python collect_song_aliases.py --refresh
```

곡 문서가 없어서 404를 반환하면 해당 곡은 대체어를 빈 목록으로 저장하고 다음 곡을 수집합니다. 접속 차단, 타임아웃, HTML 구조 변경, 파싱 실패 시 실행을 실패 처리하고 부분 수집 결과로 기존 JSON을 덮어쓰지 않습니다. 차단을 우회하는 기능은 없으며, 나무위키가 정상적인 HTML을 제공하는 환경에서 실행해야 합니다.

검증:

```powershell
python -m unittest discover -s tests -v
```
