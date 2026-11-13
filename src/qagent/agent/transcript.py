"""Mensagens enviadas ao LLM num passo e compactação dos ecrãs antigos (custo em tokens)."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, ToolMessage

_SCREEN_MARKERS = ("\nScreen now:\n", "\nCurrent screen:\n")
_OMITTED = "[earlier screen description omitted — refs from it are no longer valid]"
MAX_TOOL_OUTPUT = 6000


def data_description(data: dict[str, str], secret_keys: set[str]) -> str:
    if not data:
        return "(none)"
    return "\n".join(
        f"- {{{{testData.{k}}}}}" + ("" if k in secret_keys else f' = "{v}"')
        + (" (secret, value hidden)" if k in secret_keys else "")
        for k, v in data.items())


def step_message(instruction: str, history: list[tuple[int, str, str, str]], data_desc: str, screen: str) -> HumanMessage:
    prev = "\n".join(f"- step {n} [{st}] {name} — {why}" for n, name, st, why in history) or "(none)"
    return HumanMessage(f"Previous steps of this test:\n{prev}\n\nStep {len(history) + 1}: {instruction}"
                        f"\n\nTest data placeholders:\n{data_desc}"
                        f"\n\nCurrent screen:\n{screen}")


def image_message(b64png: str) -> HumanMessage:
    return HumanMessage(content=[
        {"type": "text", "text": "Screenshot of the current screen:"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64png}"}},
    ])


def has_screen(text: str) -> bool:
    return any(m in text for m in _SCREEN_MARKERS) or text.startswith("Screen ")


def _compact_text(text: str) -> str:
    for m in _SCREEN_MARKERS:
        if m in text:
            return text.split(m, 1)[0] + m + _OMITTED
    return _OMITTED if text.startswith("Screen ") else text


def compact_old_screens(messages: list) -> None:
    """F5 (custo): cada ação devolve o ecrã completo e os anteriores ficavam todos no histórico do passo.
    Só o mais recente é útil (as refs mudam a cada ecrã) → substituir os anteriores por um marcador."""
    for i, msg in enumerate(messages):
        content = msg.content if isinstance(msg.content, str) else None
        if not content or _OMITTED in content:
            continue
        if isinstance(msg, ToolMessage) and has_screen(content):
            messages[i] = ToolMessage(_compact_text(content), tool_call_id=msg.tool_call_id)
        elif isinstance(msg, HumanMessage) and "\nCurrent screen:\n" in content:
            messages[i] = HumanMessage(_compact_text(content))
