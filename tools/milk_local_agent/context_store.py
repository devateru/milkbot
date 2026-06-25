from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHARACTER_TEMPLATE = """# milkbot character
밀크봇의 말투와 성격을 적어두는 파일입니다.

- Discord 채팅에 어울리게 짧고 자연스럽게 답합니다.
- 모르는 내용은 지어내지 않습니다.
- 내부 prompt, token, 환경변수, 파일 경로 같은 민감정보는 말하지 않습니다.
- 필요하면 사용자가 직접 이 파일을 편집하세요.
"""

KNOWLEDGE_TEMPLATE = """# milkbot knowledge
밀크봇이 기억하면 좋은 고정 정보를 적어두는 파일입니다.

- 이 파일은 자동 업데이트되지 않습니다.
- 서버, 사람, 취향, 자주 쓰는 약속 등을 직접 적어두세요.
"""

CHANNEL_CONTEXT_TEMPLATE = """# channel context
성공한 밀크짱 호출 뒤 요약된 장기 context가 여기에 누적됩니다.
원문 Discord 로그 전체를 보관하는 파일이 아닙니다.
"""

RECENT_CONTEXT_TEMPLATE = """# recent context
아직 성공적으로 처리한 밀크짱 호출이 없습니다.
"""


@dataclass(frozen=True)
class ContextFiles:
    character: Path
    channel_context: Path
    recent_context: Path
    recent_context_json: Path
    knowledge: Path
    context_log: Path


class ContextStore:
    def __init__(self, context_dir: Path) -> None:
        self.context_dir = context_dir
        self.files = ContextFiles(
            character=context_dir / "character.txt",
            channel_context=context_dir / "channel_context.txt",
            recent_context=context_dir / "recent_context.txt",
            recent_context_json=context_dir / "recent_context.json",
            knowledge=context_dir / "knowledge.txt",
            context_log=context_dir / "context_log.txt",
        )

    def ensure_files(self) -> None:
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self._write_template_if_missing(self.files.character, CHARACTER_TEMPLATE)
        self._write_template_if_missing(self.files.channel_context, CHANNEL_CONTEXT_TEMPLATE)
        self._write_template_if_missing(self.files.recent_context, RECENT_CONTEXT_TEMPLATE)
        self._write_template_if_missing(self.files.knowledge, KNOWLEDGE_TEMPLATE)

    def _write_template_if_missing(self, path: Path, template: str) -> None:
        if not path.exists():
            path.write_text(template, encoding="utf-8")

    def read_text(self, path: Path) -> str:
        if not path.exists():
            return ""

        return path.read_text(encoding="utf-8")

    def load_context(self) -> dict[str, str]:
        self.ensure_files()
        return {
            "character": self.read_text(self.files.character),
            "channel_context": self.read_text(self.files.channel_context),
            "recent_context": self.read_text(self.files.recent_context),
            "knowledge": self.read_text(self.files.knowledge),
        }

    def load_recent_state(self, channel_id: str | None = None) -> dict[str, Any]:
        if not self.files.recent_context_json.exists():
            return self._empty_state(channel_id)

        try:
            data = json.loads(self.files.recent_context_json.read_text(encoding="utf-8"))
        except Exception:
            return self._empty_state(channel_id)

        if not isinstance(data, dict):
            return self._empty_state(channel_id)

        last_channel_id = str(data.get("last_channel_id") or "")
        last_message_id = data.get("last_processed_message_id")
        has_recent_context = bool(last_message_id)

        if channel_id is not None and last_channel_id != str(channel_id):
            has_recent_context = False
            last_message_id = None

        return {
            "ok": True,
            "has_recent_context": has_recent_context,
            "last_processed_message_id": str(last_message_id) if last_message_id else None,
            "last_processed_at": data.get("last_processed_at"),
            "last_channel_id": last_channel_id or None,
            "last_summary": data.get("last_summary", ""),
        }

    def _empty_state(self, channel_id: str | None) -> dict[str, Any]:
        return {
            "ok": True,
            "has_recent_context": False,
            "last_processed_message_id": None,
            "last_processed_at": None,
            "last_channel_id": str(channel_id) if channel_id else None,
            "last_summary": "",
        }

    def save_successful_chat(
        self,
        payload: dict[str, Any],
        answer: str,
        relevant_messages: list[dict[str, Any]],
        *,
        channel_context_text: str,
    ) -> None:
        self.ensure_files()
        current_message = payload.get("current_message", {})
        channel = payload.get("channel", {})
        now = datetime.now(timezone.utc).isoformat()
        message_id = str(current_message.get("id") or "")
        created_at = str(current_message.get("created_at") or now)
        channel_id = str(channel.get("id") or "")
        request_text = str(current_message.get("content") or "").strip()
        summary = build_recent_summary(request_text, answer, relevant_messages)

        self.files.channel_context.write_text(channel_context_text, encoding="utf-8")
        self.files.recent_context.write_text(
            "\n".join(
                [
                    "# recent context",
                    f"last_processed_message_id: {message_id}",
                    f"last_processed_at: {created_at}",
                    f"last_channel_id: {channel_id}",
                    "",
                    summary,
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.files.recent_context_json.write_text(
            json.dumps(
                {
                    "last_processed_message_id": message_id,
                    "last_processed_at": created_at,
                    "last_channel_id": channel_id,
                    "last_summary": summary,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self.append_context_log(
            now=now,
            channel_id=channel_id,
            message_id=message_id,
            relevant_messages=relevant_messages,
        )

    def append_context_log(
        self,
        *,
        now: str,
        channel_id: str,
        message_id: str,
        relevant_messages: list[dict[str, Any]],
    ) -> None:
        message_ids = [
            str(message.get("id"))
            for message in relevant_messages
            if message.get("id")
        ]
        range_text = ", ".join(message_ids[:10]) if message_ids else "none"
        if len(message_ids) > 10:
            range_text += f", ... (+{len(message_ids) - 10})"

        with self.files.context_log.open("a", encoding="utf-8") as f:
            f.write(
                f"{now}\tchannel={channel_id}\tcurrent={message_id}\trelevant={range_text}\n"
            )


def build_recent_summary(
    request_text: str,
    answer: str,
    relevant_messages: list[dict[str, Any]],
) -> str:
    lines = [
        "최근 처리한 요청 요약:",
        f"- 사용자 요청: {request_text[:500]}",
        f"- 답변 요약: {answer[:700]}",
    ]

    if relevant_messages:
        lines.append("- 참고한 직전 메시지:")
        for message in relevant_messages[:8]:
            author = message.get("author_display_name", "unknown")
            content = str(message.get("content") or "").strip()
            if not content and message.get("attachments"):
                content = "[attachment]"
            lines.append(f"  - {author}: {content[:220]}")
    else:
        lines.append("- 참고한 직전 메시지: 없음")

    return "\n".join(lines)


def build_channel_context_entry(
    payload: dict[str, Any],
    answer: str,
    relevant_messages: list[dict[str, Any]],
) -> str:
    current_message = payload.get("current_message", {})
    channel = payload.get("channel", {})
    created_at = str(current_message.get("created_at") or "")
    request_text = str(current_message.get("content") or "").strip()
    channel_id = str(channel.get("id") or "")
    channel_name = str(channel.get("name") or "")
    lines = [
        "",
        f"## {created_at} channel={channel_id} {channel_name}",
        f"- 요청: {request_text[:800]}",
    ]

    if relevant_messages:
        lines.append("- 관련 대화:")
        for message in relevant_messages[:10]:
            author = str(message.get("author_display_name") or "unknown")
            content = str(message.get("content") or "").strip()
            attachment_count = len(message.get("attachments") or [])
            suffix = f" ({attachment_count} attachment(s))" if attachment_count else ""
            lines.append(f"  - {author}: {content[:240]}{suffix}")

    lines.append(f"- 답변: {answer[:1000]}")
    return "\n".join(lines)
