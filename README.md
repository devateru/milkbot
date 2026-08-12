# milkbot
random personal discord bot

## environment

- `DISCORD_TOKEN`: Discord bot token
- `BOT_DEVELOPER_ID`: bot developer Discord user ID

## 글자 이모지 명령어

`/글자이모지`는 입력한 문자열의 각 글자를 Discord 애플리케이션 이모지로 변환해
실제 `<:name:id>` 이모지 메시지로 보냅니다. `compress`를 켜면 내용 전체를 128×128
애플리케이션 이모지 한 개에 맞춥니다.

- `background`: 투명, 우유색, 검정, 흰색, 분홍, 파랑, 초록
- `font`: 고딕, 굵은 고딕, 명조, 고정폭
- `effect`: 없음, 네온 글로우, 무지개 GIF, 불꽃 GIF
- `\n` 등의 이스케이프 시퀀스를 사용할 수 있습니다.
- 최대 64글자이며 긴 줄은 12글자마다 자동 줄바꿈됩니다.
- 생성한 이모지는 애플리케이션에 캐시됩니다. 기본 1,800개를 넘으면 마지막 사용
  시각이 가장 오래된 글자 이모지부터 삭제합니다. `MILK_EMOJI_CACHE_LIMIT`로 조절할 수 있습니다.

한글 렌더링은 저장소에 포함된 Noto Sans KR 폰트를 사용하므로 서버 글꼴 설치에
의존하지 않습니다. 폰트 라이선스는 `fonts/OFL-NotoSansKR.txt`에 있습니다.

## 밀크짱 로컬 LLM 구조

Ubuntu 서버에서는 Discord 봇만 실행합니다. 내 PC에서는 Ollama와 `tools/milk_local_agent` 로컬 에이전트를 실행하고, context 파일도 모두 PC의 로컬 파일시스템에 저장합니다. 서버 봇은 Discord 메시지를 읽은 뒤 reverse tunnel로 연결된 `http://127.0.0.1:18080` 로컬 에이전트에 요청합니다. PC나 tunnel, Ollama, 로컬 에이전트 중 하나라도 꺼져 있으면 Discord에는 정확히 `zzz (ollama 비활성화)`만 전송합니다.

네트워크는 다음처럼 둡니다.

- PC 로컬 에이전트: `127.0.0.1:18080`
- PC Ollama: `127.0.0.1:11434`
- Ubuntu 서버에서 접근하는 agent URL: `http://127.0.0.1:18080`
- PC의 `18080`, `11434`와 서버의 `18080`은 인터넷에 공개하지 않습니다.

## 밀크짱 호출

Discord 일반 메시지가 `밀크짱`으로 시작할 때만 반응합니다. 메시지 중간에 `밀크짱`이 있으면 무시합니다. 봇 자신의 메시지와 다른 봇 메시지는 무시합니다. `밀크짱` 뒤의 텍스트를 사용자 요청으로 사용하며, `밀크짱`만 보내면 짧게 무엇을 도와줄지 묻습니다.

최초 호출은 PC context가 없으므로 과거 Discord 메시지를 0개만 사용합니다. 이후 호출은 `recent_context.json`의 `last_processed_message_id` 이후 메시지를 최대 `MILK_MAX_MESSAGES_AFTER_LAST_CONTEXT`개, 기본 100개까지 시간순으로 전달합니다.

## 서버 봇 환경변수

서버 봇용 예시는 `.env.example`에 있습니다.

- `MILK_TRIGGER_PREFIX`: 기본값 `밀크짱`
- `MILK_AGENT_BASE_URL`: 기본값 `http://127.0.0.1:18080`
- `MILK_AGENT_TIMEOUT_SEC`: 기본값 `150`
- `MILK_AGENT_TOKEN`: 설정하면 agent 요청에 `Authorization: Bearer <token>`을 붙입니다.
- `MILK_MAX_MESSAGES_AFTER_LAST_CONTEXT`: 기본값 `100`
- `MILK_INCLUDE_BOT_MESSAGES_IN_CONTEXT`: 기본값 `true`. `밀크짱` 트리거는 봇 메시지를 무시하지만, 직전 context 이후 메시지 수집에는 다른 채팅봇 메시지를 포함합니다. 가능한 경우 밀크봇 자신의 이전 답변은 제외합니다.
- `ALLOWED_CHANNEL_IDS`: 쉼표로 구분한 허용 Discord 채널 ID
- `ALLOWED_ROLE_IDS`: 쉼표로 구분한 허용 Discord 역할 ID

## PC 로컬 에이전트 실행

PC 에이전트 문서와 env 예시는 `tools/milk_local_agent/README.md`, `tools/milk_local_agent/.env.example`에 있습니다. `OLLAMA_MODEL`은 필수입니다.

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
tools/milk_local_agent/scripts/start_agent.sh
curl http://127.0.0.1:18080/health
```

Windows PowerShell:

```powershell
.\tools\milk_local_agent\scripts\check_ollama.ps1
.\tools\milk_local_agent\scripts\start_agent.ps1
Invoke-RestMethod -Uri "http://127.0.0.1:18080/health"
```

### PC 에이전트 속도 설정

기본값은 빠른 응답 우선입니다. 최종 답변 생성을 제외한 추가 Ollama `/api/chat` 호출은 기본적으로 꺼져 있습니다.

- `OLLAMA_MAX_PROMPT_CHARS=8000`: prompt 최대 길이입니다. 답변이 느리면 `6000` 정도로 낮춰 테스트합니다.
- `OLLAMA_HEALTH_CACHE_TTL_SEC=10`: `/health`의 가벼운 `/api/tags` 확인 결과를 짧게 캐시합니다.
- `MILK_ENABLE_LLM_RELEVANCE_FILTER=false`: 기본값은 휴리스틱 관련 메시지 필터입니다.
- `MILK_ENABLE_LLM_CONTEXT_SUMMARY=false`: 기본값은 deterministic context 압축입니다.
- `MILK_MAX_RELATED_MESSAGES=10`: 최종 prompt에 넣는 관련 Discord 메시지 최대 개수입니다.

PC agent 로그에는 `/health`, `/state`, `/chat` 처리 시간, Ollama `/api/chat` 호출 시간, `/chat` 1회당 `ollama_chat_calls`가 출력됩니다.

## reverse tunnel

PC에서 Ubuntu 서버로 reverse tunnel을 엽니다.

```bash
ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -R 127.0.0.1:18080:127.0.0.1:18080 USER@SERVER_HOST
```

서버에서 tunnel을 확인합니다.

```bash
curl http://127.0.0.1:18080/health
```

서버 봇의 `MILK_AGENT_BASE_URL`은 `http://127.0.0.1:18080`으로 설정합니다.

## context 파일

기본 위치는 PC의 `data/milk_context`입니다. 이 경로는 git에 커밋하지 않습니다.

- `character.txt`: 캐릭터 특징, 말투, 금지/권장 표현. 자동 업데이트하지 않습니다.
- `channel_context.txt`: 채널 장기 context 요약. 성공 호출 뒤 업데이트하며 원문 전체 로그를 무한 저장하지 않습니다.
- `recent_context.txt`: 가장 최근 대화 context와 마지막 처리 메시지 정보.
- `recent_context.json`: `last_processed_message_id`, `last_processed_at`, `last_channel_id`, `last_summary`.
- `knowledge.txt`: 직접 적는 고정 지식. 자동 업데이트하지 않습니다.
- `context_log.txt`: context 업데이트 시각과 처리 메시지 범위를 짧게 append합니다.

## 웹 검색

웹 검색은 PC 로컬 에이전트에서만 수행합니다. 서버 봇에는 검색 API key를 두지 않습니다. 기본값은 비활성화입니다. 검색을 쓰려면 `WEB_SEARCH_ENABLED=true`와 provider별 key가 필요합니다.

- Google Custom Search: `GOOGLE_SEARCH_API_KEY`, `GOOGLE_SEARCH_ENGINE_ID`
- SerpAPI: `SERPAPI_API_KEY`
- Tavily: `TAVILY_API_KEY`

## 보안 주의

- Ollama `11434`를 `0.0.0.0`으로 공개하지 마세요.
- PC 로컬 에이전트 `18080`을 인터넷에 공개하지 마세요.
- reverse tunnel은 서버의 `127.0.0.1`에만 바인딩하세요.
- `MILK_AGENT_TOKEN`을 설정하세요.
- token/API key를 커밋하지 마세요.

## 수동 테스트 절차

1. PC에서 Ollama 실행
2. PC에서 `ollama list`로 모델 설치 확인
3. PC에서 `curl http://127.0.0.1:11434/api/tags`로 Ollama API 확인
4. PC에서 로컬 에이전트 실행
5. PC에서 `curl http://127.0.0.1:18080/health` 확인
6. PC에서 서버로 reverse tunnel 실행
7. Ubuntu 서버에서 `curl http://127.0.0.1:18080/health` 확인
8. 서버 봇 환경변수 `MILK_AGENT_BASE_URL=http://127.0.0.1:18080` 설정
9. 서버 봇 재시작
10. Discord 채널에서 `밀크짱 안녕` 입력
11. 응답 확인
12. PC 로컬 에이전트나 Ollama를 끈 뒤 `밀크짱 안녕` 입력
13. 정확히 `zzz (ollama 비활성화)`가 출력되는지 확인
14. PC의 `data/milk_context` 아래 context 파일 생성/업데이트 확인

ideas/TODOs

- v fix the gameplaza live checker thingy

- choose song by random \
  user can choose range of difficulty, randomly chooses ridiculus levels at small chance \
  maybe use zetaraku.dev (why make db when there is one publically)

- song finder
  based on user's filter setting, find in which index the designated song locates \
  e.g.) Based on rating sorting, "Enchanted Love" MAS will be at 187/365 on variety folder \
  -> maybe extend to find the most optimal way to find song?
  + make it possible to import json from zetaraku.dev

  thinking about using maishift for gathering user's exact score \
  sort only by general setting (date, etc) when maishift is not connected \
  ^ second thought, general sorting based indexing must always be visible \
  and... I do not have a db for now

- utage dict
  returns info about utage charts \
  filters utage for 2/3/4 players for 1/2 cabinet

- chiho calculator
  based on various conditions, calculate expected credit and time to finish each chiho \
  (or user can input current chiho + progressed km)

- clip generator (w/ external program)
  checks gameplay vid -> reports every play result recorded and timestamp
  (make external program that can generate gameplay clip with result above)

- dev debuging menu
  seperate every message visible to user as json file \
  allow me to check on milkbot dm \
  message should be legacy text command form? idk \
  iirc slash is visible to everyone \
  (and only i want to use those so) \
  ㄴ command to shift this to dm between me and milkbot to specific channel \
  way for me to message as milkbot

- git push notification
  dm me when bot gets update

- v check performai international account message

- smth fun idk
