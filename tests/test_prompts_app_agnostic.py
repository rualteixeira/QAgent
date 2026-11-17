"""O agente tem de ser universal: nenhum prompt/descrição de ferramenta pode conter termos das apps usadas nos
testes do projeto (evita afinar o agente para uma app concreta)."""

import re
from pathlib import Path

import qagent.agent
from qagent import ai_executor, normalizer, prompts
from qagent.agent import schemas

# Termos das apps de exemplo usadas no desenvolvimento (nenhum pode chegar ao LLM).
FORBIDDEN = ["eshop", "payu", "saucelabs", "mydemo", "my demo", "deskclock", "contact", "cart", "carrinho",
             "timer", "temporizador", "product", "catalog", "backpack", "dark theme", "tema escuro", "bod@",
             "alice@", "sweatshirt", "locked out"]


def _texts() -> dict[str, str]:
    out = {f"executor:{v}": t for v, t in prompts.EXECUTOR_PROMPTS.items()}
    out |= {f"normalizer:{v}": t for v, t in prompts.NORMALIZER_PROMPTS.items()}
    for cls in schemas.ALL_SCHEMAS:  # descrições dos argumentos das ferramentas (vão para o LLM)
        for fname, f in cls.model_fields.items():
            out[f"{cls.__name__}.{fname}"] = f.description or ""
    for fname, f in normalizer.NormalizedStep.model_fields.items():
        out[f"NormalizedStep.{fname}"] = f.description or ""
    return out


def test_prompts_contain_no_test_app_terms():
    leaks = {k: t for k, v in _texts().items() for t in FORBIDDEN if re.search(re.escape(t), v, re.IGNORECASE)}
    assert not leaks, f"termos específicos de apps de teste nos prompts: {leaks}"


def test_tool_descriptions_in_code_are_generic():
    # Descrições das ferramentas e mensagens enviadas ao LLM em todo o executor (qagent/agent/).
    files = [Path(ai_executor.__file__), *Path(qagent.agent.__file__).parent.glob("*.py")]
    src = "\n".join(f.read_text(encoding="utf-8") for f in files)
    descs = re.findall(r'description="([^"]+)"', src)
    assert len(descs) >= 16, "descrições das ferramentas não encontradas"
    leaks = [d for d in descs for t in FORBIDDEN if t in d.lower()]
    assert not leaks, leaks


def _llm_facing_strings(path: Path) -> list[str]:
    """Todas as constantes de texto do módulo, exceto docstrings (documentação, não vai para o LLM): mensagens
    de rejeição/contestação do veredicto, avisos das ferramentas, mensagens do ciclo."""
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_every_message_sent_to_the_llm_is_generic():
    # As regras do veredicto (verdict.py) e os avisos das ferramentas também chegam ao LLM — têm de
    # servir qualquer app, como os prompts.
    files = [Path(ai_executor.__file__), *Path(qagent.agent.__file__).parent.glob("*.py")]
    leaks = {f"{f.name}: {s[:80]!r}": t for f in files for s in _llm_facing_strings(f)
             for t in FORBIDDEN if re.search(r"\b" + re.escape(t), s, re.IGNORECASE)}
    assert not leaks, leaks


def test_every_executor_prompt_version_resolves_language():
    for v in prompts.EXECUTOR_PROMPTS:
        version, text = prompts.executor_prompt(v, "LANG-X")
        assert version == v and "LANG-X" in text and "{report_language}" not in text


# Além dos nomes das apps de teste, as versões em uso não podem ter vocabulário de domínio (o agente
# não sabe que tipo de app vai testar): só conceitos de interface do Android.
DOMAIN = ["shop", "shopping", "cart", "checkout", "purchase", "payments?", "pay", "orders?", "products?", "prices?",
          "bank", "banking", "invoice", "booking", "login", "log in", "sign in", "e-?commerce", "e-?mail", "password",
          "username", "credit card", "wallet", "subscription", "carousel"]


def test_default_prompts_and_llm_messages_have_no_domain_vocabulary():
    texts = {f"executor:{prompts.DEFAULT_EXECUTOR}": prompts.executor_prompt(None, "pt-PT")[1],
             f"normalizer:{prompts.DEFAULT_NORMALIZER}": prompts.normalizer_prompt()[1]}
    for cls in schemas.ALL_SCHEMAS:
        for fname, f in cls.model_fields.items():
            texts[f"{cls.__name__}.{fname}"] = f.description or ""
    files = [Path(ai_executor.__file__), *Path(qagent.agent.__file__).parent.glob("*.py")]
    for f in files:
        for i, s in enumerate(_llm_facing_strings(f)):
            texts[f"{f.name}#{i}"] = s
    leaks = {k: m.group(0) for k, v in texts.items() for d in DOMAIN
             for m in [re.search(r"\b" + d + r"\b", v, re.IGNORECASE)] if m}
    assert not leaks, f"vocabulário de domínio no que vai para o LLM: {leaks}"
