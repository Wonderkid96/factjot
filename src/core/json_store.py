from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonStore:
    def __init__(self, path: str, default: Any) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.write(default)

    def read(self) -> Any:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def write(self, payload: Any) -> None:
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
