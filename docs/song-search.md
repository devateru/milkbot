# 곡 검색

봇을 재시작하면 `/곡검색` 명령어가 동기화됩니다.

1. `곡` 옵션에 원제나 대체어를 입력합니다.
2. 자동완성에서 `[DX] 곡명` 또는 `[ST] 곡명`을 선택합니다.
3. 필요하면 별도 `난이도` 옵션을 선택합니다. 생략하면 MASTER입니다.
4. 명령어를 실행하면 기존 곡 임베드를 표시합니다. **노트 배점** 버튼으로 해당 채보의 상세 배점을 조회할 수 있습니다. 다시 뽑기 버튼은 없습니다.

Re:MASTER가 선택한 DX/ST 채보에 없으면 같은 타입의 MASTER를 표시하고 임베드 하단에 안내합니다. 난이도 옵션은 BASIC, ADVANCED, EXPERT, MASTER, Re:MASTER입니다.

검색은 `song_aliases.json`의 별칭과 원제를 사용합니다. 대소문자, 전각/반각, 띄어쓰기, 특수 문자 차이를 정리해서 비교하며 부분 제목, 한글 초성, 히라가나/가타카나, 3글자 이상 검색어의 가벼운 오타도 허용합니다. 정확한 일치와 앞부분 일치가 우선입니다. 약칭은 JSON에 등록돼 있어야 검색할 수 있습니다.

곡 데이터는 기존 `song_search.get_data()`와 동일한 출처를 사용합니다. 기존 선곡 기본값과 동일하게 국제판(`intl`)에 있는 DX/ST 채보만 표시하고 국제판 난이도 보정을 반영합니다. 삭제곡이나 국제판 미수록곡의 별칭이 있어도 현재 채보가 없으면 결과에 나오지 않습니다.

자동완성은 최대 25개이며 표시 이름이 너무 길면 줄여 표시합니다. 내부 선택값으로 곡과 타입을 구분하므로 이름이 잘려도 원래 곡을 조회합니다. 곡 데이터는 시작 시 읽고 1시간마다 갱신합니다. `song_aliases.json` 변경은 다음 자동완성 검색 시 재시작 없이 반영합니다. JSON이 없으면 원제로 검색할 수 있습니다. 나무위키 제목과 실제 곡명이 다르면 JSON 유사어 중 실제 곡명과 유일하게 연결되는 이름을 이용합니다. 리믹스 등 다른 곡으로 유사어가 넘어가지 않도록 원제 연결을 우선하며 모호한 연결은 제외합니다.

Python에서 직접 사용할 수도 있습니다. 이 함수는 봇에 연결하지 않습니다.

```python
from song_lookup import load_song_lookup

index = load_song_lookup()
options = index.autocomplete("magical fl")
# [{"name": "[DX] Magical Flavor", "value": "dx:..."}, ...]
song, sheet, fallback = index.select(options[0]["value"], "remaster")
```

단위 테스트와 로컬 명령어/임베드 검증:

```powershell
python -m unittest discover -s tests -v
```
