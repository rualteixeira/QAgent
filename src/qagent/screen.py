"""Modelo do ecrã para o LLM, construído a partir do XML da página (UiAutomator2). Agnóstico à app.

Princípios (fase de generalização, 2026-11-12):
- Nada de conhecimento de apps concretas: só a estrutura Android (classes, texto, content-desc,
  resource-id, flags e posição).
- TODOS os elementos interativos entram, incluindo os só-ícone sem rótulo (comuns em banca/fintech,
  Flutter/React Native mal anotados), com posição e o nome do resource-id como pista.
- O LLM refere elementos por `ref` (e1, e2…). O QAgent converte a ref no locator mais estável:
  accessibility id > id > texto (uiautomator) > resourceId+instance (frágil) > coordenadas (frágil).
  O LLM nunca escreve locators → não os pode inventar.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field

from qagent.models import Locator

SYSTEM_PACKAGES = frozenset({"android", "com.android.systemui"})
# Diálogos de erro do Android ("app isn't responding" / "app has stopped"): os resource-ids aerr_*
# não dependem do idioma. Outras sobreposições do sistema (notificações, dicas, permissões) NÃO são erro.
ERROR_DIALOG_ID_PREFIX = "android:id/aerr_"


def has_error_dialog(xml: str) -> bool:
    return f'resource-id="{ERROR_DIALOG_ID_PREFIX}' in xml
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")
MAX_ELEMENTS = 70
MAX_TEXT = 60


def _short_class(cls: str) -> str:
    return cls.rsplit(".", 1)[-1] if cls else "View"


def _short_rid(rid: str) -> str:
    return rid.split(":id/", 1)[-1] if rid else ""


def _ui_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


@dataclass
class UiElement:
    ref: str
    cls: str
    text: str
    desc: str
    rid: str
    bounds: tuple[int, int, int, int]
    clickable: bool = False
    long_clickable: bool = False
    checkable: bool = False
    checked: bool = False
    selected: bool = False
    enabled: bool = True
    focused: bool = False
    password: bool = False
    scrollable: bool = False
    editable: bool = False
    inner_texts: list[str] = field(default_factory=list)
    locator: Locator | None = None
    fragile: bool = False

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def label(self) -> str:
        return self.text or self.desc or " / ".join(self.inner_texts)


@dataclass
class Screen:
    width: int
    height: int
    packages: set[str]
    elements: list[UiElement]
    truncated: int = 0
    error_dialog: bool = False

    def by_ref(self, ref: str) -> UiElement | None:
        return next((e for e in self.elements if e.ref == ref), None)

    @property
    def system_overlay(self) -> bool:
        return bool(self.packages) and self.packages <= SYSTEM_PACKAGES

    def texts(self) -> list[str]:
        out = []
        for e in self.elements:
            for t in (e.text, e.desc, *e.inner_texts):
                if t and t not in out:
                    out.append(t)
        return out

    def describe(self) -> str:
        lines = [f"Screen {self.width}x{self.height}, app package(s): {', '.join(sorted(self.packages)) or '?'}"]
        if self.error_dialog:
            lines.append("WARNING: an Android error dialog is shown (app not responding / app stopped).")
        elif self.system_overlay:
            lines.append("Note: a system overlay is in the foreground (notification, system hint or prompt), "
                         "not an app screen.")
        for e in self.elements:
            lines.append("- " + _describe_element(e, self.width, self.height))
        if self.truncated:
            lines.append(f"- … {self.truncated} more elements not listed (use get_screen with a filter)")
        if any(e.scrollable for e in self.elements):
            lines.append("Note: scrollable containers exist — content may continue off-screen (use scroll/scroll_to).")
        if not self.elements:
            lines.append("(no elements found — the screen may still be loading, or the UI is not exposed "
                         "to accessibility: use look_at_screen)")
        return "\n".join(lines)


def _region(e: UiElement, w: int, h: int) -> str:
    x, y = e.center
    v = "top" if y < h / 3 else "bottom" if y > 2 * h / 3 else "middle"
    hz = "left" if x < w / 3 else "right" if x > 2 * w / 3 else "center"
    return f"{v}-{hz}"


def _describe_element(e: UiElement, w: int, h: int) -> str:
    parts = [e.ref, _short_class(e.cls)]
    if e.text:
        parts.append(f'"{e.text[:MAX_TEXT]}"')
    if e.desc and e.desc != e.text:
        parts.append(f'desc="{e.desc[:MAX_TEXT]}"')
    if e.inner_texts and not (e.text or e.desc):
        parts.append(f'contains="{" / ".join(t[:40] for t in e.inner_texts[:3])}"')
    if not e.label:
        parts.append("(no label)")
    rid = _short_rid(e.rid)
    if rid:
        parts.append(f"id={rid}")
    flags = [f for f, on in (("editable", e.editable), ("password", e.password), ("clickable", e.clickable),
                             ("long-clickable", e.long_clickable), ("scrollable", e.scrollable),
                             ("checked" if e.checked else "unchecked", e.checkable), ("selected", e.selected),
                             ("focused", e.focused), ("DISABLED", not e.enabled)) if on]
    if flags:
        parts.append(f"[{', '.join(flags)}]")
    parts.append(f"@{_region(e, w, h)}")
    return " ".join(parts)


def _bool(node: ET.Element, attr: str) -> bool:
    return node.attrib.get(attr) == "true"


def parse_screen(xml: str, max_elements: int = MAX_ELEMENTS) -> Screen:
    root = ET.fromstring(xml)
    w = int(root.attrib.get("width", 0) or 0)
    h = int(root.attrib.get("height", 0) or 0)
    all_nodes = [n for n in root.iter() if n is not root]
    packages = {n.attrib["package"] for n in all_nodes if n.attrib.get("package")}
    # Contagens globais para decidir unicidade dos locators.
    desc_count = Counter(n.attrib.get("content-desc") for n in all_nodes if n.attrib.get("content-desc"))
    rid_count = Counter(n.attrib.get("resource-id") for n in all_nodes if n.attrib.get("resource-id"))
    text_count = Counter(n.attrib.get("text") for n in all_nodes if n.attrib.get("text"))
    rid_seen: Counter = Counter()

    elements: list[UiElement] = []
    truncated = 0

    def visit(node: ET.Element, ancestor: UiElement | None) -> None:
        nonlocal truncated
        a = node.attrib
        m = _BOUNDS_RE.match(a.get("bounds", ""))
        rid = a.get("resource-id", "")
        if rid:
            rid_seen[rid] += 1
        current = ancestor
        if m and a.get("displayed", "true") != "false":
            x1, y1, x2, y2 = map(int, m.groups())
            visible = x2 > x1 and y2 > y1 and x2 > 0 and y2 > 0 and (not w or x1 < w) and (not h or y1 < h)
            cls = a.get("class", "")
            text, desc = a.get("text", "").strip(), a.get("content-desc", "").strip()
            editable = "EditText" in cls or "TextField" in cls
            interactive = any(_bool(node, k) for k in ("clickable", "long-clickable", "checkable", "scrollable")) or editable
            if visible and (interactive or text or desc):
                if not interactive and ancestor is not None and not (ancestor.text or ancestor.desc):
                    # Texto dentro de um contentor clicável sem rótulo próprio → rótulo do contentor.
                    t = text or desc
                    if t and t not in ancestor.inner_texts and len(ancestor.inner_texts) < 4:
                        ancestor.inner_texts.append(t)
                elif len(elements) >= max_elements:
                    truncated += 1
                else:
                    el = UiElement(
                        ref=f"e{len(elements) + 1}", cls=cls, text=text, desc=desc, rid=rid,
                        bounds=(x1, y1, x2, y2), clickable=_bool(node, "clickable"),
                        long_clickable=_bool(node, "long-clickable"), checkable=_bool(node, "checkable"),
                        checked=_bool(node, "checked"), selected=_bool(node, "selected"),
                        enabled=a.get("enabled", "true") != "false", focused=_bool(node, "focused"),
                        password=_bool(node, "password"), scrollable=_bool(node, "scrollable"),
                        editable=editable)
                    el.locator, el.fragile = _best_locator(el, desc_count, rid_count, text_count,
                                                           rid_seen[rid] - 1 if rid else 0)
                    elements.append(el)
                    # Só contentores ACIONÁVEIS sem rótulo herdam o texto dos filhos (ex.: item de lista).
                    # Um contentor que só faz scroll não: o texto (ex.: mensagem de erro) tem de ficar visível.
                    actionable = el.clickable or el.long_clickable or el.checkable
                    if actionable and not (text or desc):
                        current = el
        for child in node:
            visit(child, current)

    visit(root, None)
    # Contentores sem rótulo próprio: locator pelo texto interior se for único.
    for e in elements:
        if e.fragile and e.inner_texts and text_count.get(e.inner_texts[0]) == 1:
            e.locator = Locator(strategy="-android uiautomator",
                                value=f'new UiSelector().text("{_ui_text(e.inner_texts[0])}")')
            e.fragile = False
    return Screen(w, h, packages, elements, truncated,
                  error_dialog=any(n.attrib.get("resource-id", "").startswith(ERROR_DIALOG_ID_PREFIX)
                                   for n in all_nodes))


_UI_TEXT_RE = re.compile(r'^new UiSelector\(\)\.text\("(.*)"\)$')
_UI_RID_RE = re.compile(r'^new UiSelector\(\)\.resourceId\("(.*)"\)\.instance\((\d+)\)$')


def _matches(e: UiElement, strategy: str, selector: str) -> bool:
    if strategy == "accessibility id":
        return e.desc == selector
    if strategy == "id":
        return e.rid == selector
    if strategy == "-android uiautomator":
        m = _UI_TEXT_RE.match(selector)
        if m:
            t = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
            return e.text == t or t in e.inner_texts
        m = _UI_RID_RE.match(selector)
        if m:
            return e.rid == m.group(1)
    return False


def verify_assertion(screen: "Screen", spec: dict) -> tuple[bool, str]:
    """Verifica uma asserção estruturada num ecrã (sem LLM). Devolve (ok, o que foi observado)."""
    kind, text = spec["kind"], spec.get("text")
    if kind in ("visible", "absent") and "selector" not in spec:
        present = any(text.lower() in t.lower() for t in screen.texts())
        return (present if kind == "visible" else not present), f"'{text}' {'present' if present else 'not present'}"
    if kind == "count":
        n = sum(1 for e in screen.elements if e.rid == spec["selector"])
        ok = n == spec["count"] if spec.get("op", "eq") == "eq" else n >= spec["count"]
        return ok, f"{n} element(s) with id {spec['selector']}"
    found = [e for e in screen.elements if _matches(e, spec["strategy"], spec["selector"])]
    if kind == "visible":
        return bool(found), f"{len(found)} match(es) for {spec['strategy']}={spec['selector']}"
    if not found:
        return False, f"element {spec['strategy']}={spec['selector']} not found"
    actual = found[0].label
    ok = actual == text if kind == "text_equals" else (text.lower() in actual.lower())
    return ok, f"text is {actual!r}"


def _best_locator(e: UiElement, desc_count: Counter, rid_count: Counter, text_count: Counter,
                  rid_index: int) -> tuple[Locator | None, bool]:
    # Textos/descrições com dígitos costumam ser dinâmicos (contadores, preços, "13 seconds remaining"):
    # preferir o resource-id; se não houver, usar o texto mas marcar como frágil.
    desc_dyn = any(c.isdigit() for c in e.desc)
    text_dyn = any(c.isdigit() for c in e.text)
    if e.desc and desc_count[e.desc] == 1 and not desc_dyn:
        return Locator(strategy="accessibility id", value=e.desc), False
    if e.rid and rid_count[e.rid] == 1:
        return Locator(strategy="id", value=e.rid), False
    if e.text and text_count[e.text] == 1 and not text_dyn:
        # Num campo editável o texto é a sugestão ou o valor atual — muda ao escrever → frágil.
        return Locator(strategy="-android uiautomator",
                       value=f'new UiSelector().text("{_ui_text(e.text)}")'), e.editable
    if e.desc and desc_count[e.desc] == 1:
        return Locator(strategy="accessibility id", value=e.desc), True
    if e.text and text_count[e.text] == 1:
        return Locator(strategy="-android uiautomator", value=f'new UiSelector().text("{_ui_text(e.text)}")'), True
    if e.rid:
        return Locator(strategy="-android uiautomator",
                       value=f'new UiSelector().resourceId("{e.rid}").instance({rid_index})'), True
    return None, True  # → coordenadas


# ---------- toques em elementos tapados ----------

Bounds = tuple[int, int, int, int]
_GRID = (0.5, 0.25, 0.75, 0.1, 0.9)


def _contains(b: Bounds, x: int, y: int) -> bool:
    return b[0] <= x <= b[2] and b[1] <= y <= b[3]


def _inside(a: Bounds, b: Bounds) -> bool:
    """a está dentro de b."""
    return b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3]


def free_point(target: Bounds, clickables: list[Bounds]) -> tuple[int, int] | None:
    """Ponto onde tocar no alvo quando o seu CENTRO está tapado por outro elemento clicável que não é o próprio,
    nem quem o contém, nem algo dentro dele (ex.: botão flutuante ou barra fixa por cima de uma lista).
    None = centro livre (tocar normalmente) ou nenhum ponto livre (tocar normalmente; nada a fazer)."""
    cx, cy = (target[0] + target[2]) // 2, (target[1] + target[3]) // 2
    covers = [b for b in clickables if _contains(b, cx, cy) and not _inside(target, b) and not _inside(b, target)]
    if not covers:
        return None
    w, h = target[2] - target[0], target[3] - target[1]
    for fy in _GRID:
        for fx in _GRID:
            x, y = int(target[0] + w * fx), int(target[1] + h * fy)
            if not any(_contains(b, x, y) for b in covers):
                return x, y
    return None


def node_at(xml: str, x: int, y: int) -> dict | None:
    """Nó visível mais interior (menor área) que contém o ponto, mesmo que não seja listado ao modelo (ex.: uma
    superfície desenhada sem acessibilidade). Serve para o script gerado confirmar o ecrã antes de tocar."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    best, best_area = None, None
    for n in root.iter():
        m = _BOUNDS_RE.match(n.attrib.get("bounds", ""))
        if not m or n.attrib.get("displayed", "true") == "false":
            continue
        b = tuple(map(int, m.groups()))
        if not _contains(b, x, y):
            continue
        area = (b[2] - b[0]) * (b[3] - b[1])
        if best_area is None or area < best_area:
            cls = n.attrib.get("class", n.tag)
            best, best_area = {"cls": cls, "bounds": list(b), "text": n.attrib.get("text", "").strip(),
                               "desc": n.attrib.get("content-desc", "").strip(),
                               "editable": "EditText" in cls or "TextField" in cls}, area
    return best


def png_size(data: bytes) -> tuple[int, int] | None:
    """(largura, altura) de um PNG pelo cabeçalho IHDR, sem bibliotecas de imagem."""
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None
