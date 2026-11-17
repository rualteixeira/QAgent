"""Estado de um passo LLM (recriado em cada run_instruction)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StepState:
    instruction: str
    is_when: bool = False
    is_then: bool = False
    successes: int = 0          # ferramentas bem-sucedidas (ações + observações)
    action_successes: int = 0   # ações reais bem-sucedidas
    action_failures: int = 0
    when_fail_challenged: bool = False  # falha de WHEN com ações bem-sucedidas contestada uma vez
    then_fail_challenged: bool = False  # falha de THEN sem asserção / contraditória contestada uma vez
    preexisting_challenged: bool = False  # WHEN declarado "já existia antes do teste" contestado uma vez
    pending_image: str | None = None    # screenshot a anexar na próxima mensagem (look_at_screen)
    shot_size: tuple[int, int] | None = None  # tamanho da última captura vista pelo modelo (px)

    @classmethod
    def for_instruction(cls, instruction: str) -> "StepState":
        head = instruction.lstrip().upper()
        return cls(instruction=instruction, is_when=head.startswith("[WHEN]"), is_then=head.startswith("[THEN]"))
