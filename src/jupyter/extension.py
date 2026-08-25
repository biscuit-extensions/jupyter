from __future__ import annotations

import typing

from biscuit.extensions import Extension

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI


import json

class Jupyter(Extension):
    """Interactive Jupyter notebook runner and cell-based Python execution."""

    def __init__(self, api: ExtensionsAPI) -> None:
        super().__init__(api)
        self.api = api
        self.api.logger.info("Jupyter extension initialised.")

    def parse_cells(self, raw_notebook: str) -> list[dict]:
        nb = json.loads(raw_notebook)
        cells = []
        for c in nb.get("cells", []):
            cells.append({
                "cell_type": c.get("cell_type", "code"),
                "source": "".join(c.get("source", [])),
                "execution_count": c.get("execution_count")
            })
        return cells

    def execute_cell_code(self, source: str) -> dict:
        try:
            val = eval(source.strip())
            return {"status": "ok", "output": repr(val)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def install(self) -> None:
        self.api.logger.info("Jupyter extension installed.")
