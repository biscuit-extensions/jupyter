from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.jupyter import setup
from src.jupyter.extension import Jupyter, KernelSession


class TestJupyterExtension:
    def test_setup_and_registration(self, mock_api) -> None:
        setup(mock_api)
        assert "jupyter" in mock_api.registered_extensions
        ext = mock_api.registered_extensions["jupyter"]
        assert isinstance(ext, Jupyter)

    def test_install_registers_commands_and_statusbar(self, mock_api) -> None:
        ext = Jupyter(mock_api)
        ext.install()

        # Commands
        commands = mock_api.commands.commands
        assert "jupyter.run_current_cell" in commands
        assert "jupyter.run_all_cells" in commands
        assert "jupyter.restart_kernel" in commands
        assert "jupyter.clear_outputs" in commands
        assert "jupyter.export_python" in commands
        assert "jupyter.new_notebook" in commands

        # Statusbar
        assert ext.statusbar_button is not None
        assert ext.statusbar_button.visible is True
        assert "Jupyter" in ext.statusbar_button.text

    def test_parse_notebook_and_cells(self, mock_api) -> None:
        ext = Jupyter(mock_api)
        raw_nb = """{
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": ["# Analysis\\n", "First section."]
  },
  {
   "cell_type": "code",
   "execution_count": 1,
   "metadata": {},
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": ["Calculated\\n"]
    }
   ],
   "source": ["x = 10\\n", "print('Calculated')"]
  }
 ],
 "metadata": {},
 "nbformat": 4,
 "nbformat_minor": 2
}"""
        cells = ext.parse_cells(raw_nb)
        assert len(cells) == 2
        assert cells[0]["cell_type"] == "markdown"
        assert "# Analysis" in cells[0]["source"]

        assert cells[1]["cell_type"] == "code"
        assert cells[1]["execution_count"] == 1
        assert "x = 10" in cells[1]["source"]
        assert len(cells[1]["outputs"]) == 1

    def test_create_blank_notebook_and_save(self, mock_api, tmp_path) -> None:
        ext = Jupyter(mock_api)
        nb = ext.create_blank_notebook("python3")
        assert nb["nbformat"] == 4
        assert len(nb["cells"]) == 2

        file_target = tmp_path / "test.ipynb"
        saved_text = ext.save_notebook(nb, filepath=file_target)
        assert file_target.exists()

        reloaded = ext.parse_notebook(file_target)
        assert reloaded["nbformat"] == 4
        assert len(reloaded["cells"]) == 2

    def test_kernel_session_persistent_state(self) -> None:
        kernel = KernelSession()

        # Step 1: Assign variables
        res1 = kernel.execute("a = 25\nb = 17")
        assert res1["status"] == "ok"
        assert res1["execution_count"] == 1

        # Step 2: Compute expression using assigned variables
        res2 = kernel.execute("a + b")
        assert res2["status"] == "ok"
        assert res2["execution_count"] == 2
        assert len(res2["outputs"]) == 1
        assert res2["outputs"][0]["output_type"] == "execute_result"
        assert res2["outputs"][0]["data"]["text/plain"] == "42"

        # Step 3: Define function and call
        kernel.execute("def multiply(x, y):\n    return x * y")
        res4 = kernel.execute("multiply(6, 7)")
        assert res4["outputs"][0]["data"]["text/plain"] == "42"

    def test_kernel_session_stdout_stderr(self) -> None:
        kernel = KernelSession()
        code = "import sys\nprint('Hello stdout')\nsys.stderr.write('Warning stderr\\n')"
        res = kernel.execute(code)
        assert res["status"] == "ok"

        stream_names = [o["name"] for o in res["outputs"] if o["output_type"] == "stream"]
        assert "stdout" in stream_names
        assert "stderr" in stream_names

    def test_kernel_session_error_capture(self) -> None:
        kernel = KernelSession()
        res = kernel.execute("10 / 0")
        assert res["status"] == "error"
        assert res["ename"] == "ZeroDivisionError"
        assert "division by zero" in res["evalue"]

        error_out = next(o for o in res["outputs"] if o["output_type"] == "error")
        assert error_out["ename"] == "ZeroDivisionError"
        assert len(error_out["traceback"]) > 0

    def test_kernel_restart(self) -> None:
        kernel = KernelSession()
        kernel.execute("stored_val = 999")
        assert "stored_val" in kernel.globals_dict

        kernel.restart()
        assert "stored_val" not in kernel.globals_dict
        assert kernel.execution_count == 0

        res = kernel.execute("stored_val")
        assert res["status"] == "error"
        assert res["ename"] == "NameError"

    def test_execute_cell_and_run_all_cells(self, mock_api) -> None:
        ext = Jupyter(mock_api)
        nb = ext.create_blank_notebook()
        nb["cells"] = [
            {"cell_type": "code", "source": "val = 100", "outputs": []},
            {"cell_type": "markdown", "source": "## Summary"},
            {"cell_type": "code", "source": "val * 2", "outputs": []},
        ]

        ext.run_all_cells(nb)
        assert nb["cells"][0]["execution_count"] == 1
        assert nb["cells"][2]["execution_count"] == 2
        assert nb["cells"][2]["outputs"][0]["data"]["text/plain"] == "200"

    def test_clear_cell_outputs(self, mock_api) -> None:
        ext = Jupyter(mock_api)
        nb = {
            "cells": [
                {"cell_type": "code", "execution_count": 5, "source": "print(1)", "outputs": [{"output_type": "stream"}]}
            ]
        }
        cleared = ext.clear_cell_outputs(nb)
        assert cleared["cells"][0]["execution_count"] is None
        assert cleared["cells"][0]["outputs"] == []

    def test_export_and_import_python_script(self, mock_api) -> None:
        ext = Jupyter(mock_api)
        nb = {
            "cells": [
                {"cell_type": "markdown", "source": "# Section Title\nDetailed note."},
                {"cell_type": "code", "source": "import math\nmath.sqrt(16)"},
            ]
        }

        script = ext.export_to_python_script(nb)
        assert "# %% [markdown]" in script
        assert "# Section Title" in script
        assert "math.sqrt(16)" in script

        reimported = ext.import_from_python_script(script)
        assert len(reimported["cells"]) == 2
        assert reimported["cells"][0]["cell_type"] == "markdown"
        assert "Section Title" in reimported["cells"][0]["source"]
        assert reimported["cells"][1]["cell_type"] == "code"
        assert "math.sqrt(16)" in reimported["cells"][1]["source"]

    def test_manifest_schema_and_dependencies(self) -> None:
        import tomllib

        manifest_path = Path(__file__).parent.parent / "extension.toml"
        assert manifest_path.exists()
        with open(manifest_path, "rb") as f:
            data = tomllib.load(f)

        assert data["extension"]["id"] == "jupyter"
        assert data["extension"]["author"] == "tomlin7"
        assert data["extension"]["version"] == "0.2.0"
        assert "nbformat>=5.9.0" in data["dependencies"]["python"]
        assert "jupyter_client>=8.6.0" in data["dependencies"]["python"]
        assert "python" in data["dependencies"]["tools"]
        assert "jupyter" in data["dependencies"]["tools"]
        assert len(data["contributes"]["commands"]) >= 6
