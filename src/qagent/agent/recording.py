"""Registo das ações e dos locators de um passo (base do relatório e do script gerado) e máscara de segredos."""

from __future__ import annotations

from qagent.models import ActionRecord, ElementSignature, LocatorRecord, StepResult
from qagent.screen import UiElement


class Secrets:
    """Valores de testData marcados como segredo: nunca aparecem em registos nem em mensagens."""

    def __init__(self, data: dict[str, str], secret_keys: set[str]) -> None:
        self.data = data
        self.keys = secret_keys

    def mask(self, text: str) -> str:
        for k in self.keys:
            v = self.data.get(k)
            if v and len(v) >= 3:
                text = text.replace(v, "***")
        return text


def _stable(s: str, editable: bool) -> str | None:
    """Texto que serve para reconhecer o elemento noutra execução: não editável e sem dígitos (contadores,
    preços e horas mudam) — a mesma regra dos locators (qagent.screen)."""
    return s if s and not editable and not any(c.isdigit() for c in s) else None


def signature(el: UiElement) -> ElementSignature:
    return ElementSignature(cls=el.cls, bounds=list(el.bounds), text=_stable(el.text, el.editable),
                            desc=_stable(el.desc, False))


def record_point(result: StepResult, tool: str, x: int, y: int, node: dict | None) -> None:
    """Ação num ponto do ecrã (sem elemento listado): coordenadas (frágeis) + o nó que lá estava, para o script
    gerado confirmar o ecrã antes de repetir o toque."""
    target = None
    if node:
        target = ElementSignature(cls=node["cls"], bounds=node["bounds"], text=_stable(node["text"], node["editable"]),
                                  desc=_stable(node["desc"], False))
    sel = f"{x},{y}"
    result.actions.append(ActionRecord(tool=tool, strategy="coordinates", selector=sel, result="ok", target=target))
    if not any(l.strategy == "coordinates" and l.value == sel for l in result.locators):
        result.locators.append(LocatorRecord(strategy="coordinates", value=sel, fragile=True,
                                             element=node["cls"].rsplit(".", 1)[-1] if node else None))


def record(result: StepResult, tool: str, el: UiElement | None, outcome: str = "ok",
           value: str | None = None) -> None:
    """Ação sobre um elemento → locator mais estável (ou coordenadas, frágil) + registo do locator usado."""
    value_arg = value
    if el is None:
        result.actions.append(ActionRecord(tool=tool, result=outcome, value=value_arg))
        return
    target = None
    if el.locator:
        strat, value, fragile = el.locator.strategy, el.locator.value, el.fragile
    else:
        x, y = el.center
        strat, value, fragile = "coordinates", f"{x},{y}", True
        target = signature(el)
    result.actions.append(ActionRecord(tool=tool, strategy=strat, selector=value, result=outcome,
                                       value=None if value_arg is None else value_arg, target=target))
    if not any(l.strategy == strat and l.value == value for l in result.locators):
        result.locators.append(LocatorRecord(strategy=strat, value=value, element=el.cls.rsplit(".", 1)[-1],
                                             fragile=fragile or strat == "xpath"))
