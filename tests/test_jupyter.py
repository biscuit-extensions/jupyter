from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.jupyter import setup
from src.jupyter.extension import Jupyter


class TestJupyterExtension:
    def test_extension_setup(self, app_instance) -> None:
        setup(app_instance.api)
        ext = Jupyter(app_instance.api)
        nb = '{"cells": [{"cell_type": "code", "source": ["2 + 3"]}]}'
        cells = ext.parse_cells(nb)
        assert len(cells) == 1
        res = ext.execute_cell_code(cells[0]["source"])
        assert res["output"] == "5"
