"""qagent.log por execução (JSON lines). Segredos mascarados antes de escrever."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MASK = "***"


class RunLog:
    def __init__(self, path: Path, secrets: set[str] | None = None) -> None:
        self.path = path
        # Só valores não triviais; ordenar do maior para o menor evita mascarar parcialmente.
        self._secrets = sorted({s for s in (secrets or set()) if len(s) >= 3}, key=len, reverse=True)

    def mask(self, value: Any) -> Any:
        if isinstance(value, str):
            for s in self._secrets:
                value = value.replace(s, MASK)
            return value
        if isinstance(value, dict):
            return {k: self.mask(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.mask(v) for v in value]
        return value

    def write(self, event: str, **fields: Any) -> None:
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": event}
        rec.update(self.mask(fields))
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
