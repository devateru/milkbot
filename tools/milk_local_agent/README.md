# milk local agent

PC에서 실행하는 로컬 LLM 에이전트입니다. Ubuntu 서버의 Discord 봇은 이 에이전트에 HTTP로 요청하고, context 파일과 Ollama는 모두 PC에만 둡니다.

## 실행

1. Ollama를 실행하고 모델을 준비합니다.

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
```

2. `tools/milk_local_agent/.env.example`을 참고해 `tools/milk_local_agent/.env`를 만듭니다. `OLLAMA_MODEL`은 필수입니다.

3. PC에서 에이전트를 실행합니다.

```bash
tools/milk_local_agent/scripts/start_agent.sh
```

Windows PowerShell:

```powershell
.\tools\milk_local_agent\scripts\start_agent.ps1
```

4. PC에서 확인합니다.

```bash
curl http://127.0.0.1:18080/health
```

5. PC에서 Ubuntu 서버로 reverse tunnel을 엽니다.

```bash
ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -R 127.0.0.1:18080:127.0.0.1:18080 USER@SERVER_HOST
```

또는:

```bash
tools/milk_local_agent/scripts/start_tunnel.sh USER@SERVER_HOST
```

6. Ubuntu 서버에서 확인합니다.

```bash
curl http://127.0.0.1:18080/health
```

## API

- `GET /health`: 에이전트, Ollama, `OLLAMA_MODEL` 상태 확인
- `GET /state?channel_id=<channel_id>`: 최근 처리한 Discord 메시지 상태 확인
- `POST /chat`: Discord 메시지 payload를 받아 Ollama 답변 생성 및 context 업데이트

`MILK_AGENT_TOKEN`이 설정되어 있으면 모든 요청에 `Authorization: Bearer <token>`이 필요합니다.

## context 파일

기본 위치는 `data/milk_context`입니다.

- `character.txt`: 캐릭터 설정. 자동 업데이트하지 않습니다.
- `channel_context.txt`: 성공한 호출 뒤 요약된 장기 context를 누적합니다.
- `recent_context.txt`: 최근 처리한 요청의 사람이 읽는 요약입니다.
- `recent_context.json`: `last_processed_message_id`, `last_processed_at`, `last_channel_id`, `last_summary`를 저장합니다.
- `knowledge.txt`: 사용자가 직접 적는 고정 지식입니다. 자동 업데이트하지 않습니다.
- `context_log.txt`: context 업데이트 시각과 처리 메시지 범위를 짧게 append합니다.

최초 호출 때는 서버 봇이 과거 Discord 메시지를 읽지 않습니다. 이후 호출부터 `recent_context.json`의 `last_processed_message_id` 이후 메시지를 서버 봇이 최대 100개까지 모아 보냅니다.

## 보안

- Ollama `11434`를 `0.0.0.0`으로 공개하지 마세요.
- 로컬 에이전트 `18080`을 인터넷에 직접 공개하지 마세요.
- reverse tunnel은 서버의 `127.0.0.1:18080`에만 바인딩하세요.
- `MILK_AGENT_TOKEN`을 설정하고, token/API key를 커밋하지 마세요.
