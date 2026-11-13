"""Exceções de um passo LLM."""

from __future__ import annotations


class HumanInputRequired(Exception):
    """O passo precisa de uma ação do QA no dispositivo (ex.: autenticação). Tratado pelo orquestrador."""

    def __init__(self, instruction: str) -> None:
        super().__init__(instruction)
        self.instruction = instruction


class PreexistingState(RuntimeError):
    """Passo de ação satisfeito por estado anterior ao teste → erro de ambiente (não é sucesso nem falha da app)."""


class ToolMisuse(Exception):
    """Uso incorreto de uma ferramenta pelo LLM (ex.: ref inexistente) — devolvido como ERROR, sem falhar o passo."""
