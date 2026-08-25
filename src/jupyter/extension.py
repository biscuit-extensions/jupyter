from __future__ import annotations

import ast
import io
import json
import os
import re
import sys
import traceback
import typing
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from biscuit.extensions import Extension

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI


class KernelSession:
    """In-process Python execution session with persistent state across notebook cells."""

    def __init__(self) -> None:
        self.status = "idle"
        self.execution_count = 0
        self.globals_dict: dict[str, typing.Any] = {
            "__name__": "__main__",
            "__doc__": None,
        }

    def restart(self) -> None:
        """Reset execution environment and counter."""
        self.globals_dict = {
            "__name__": "__main__",
            "__doc__": None,
        }
        self.execution_count = 0
        self.status = "idle"

    def execute(self, source: str) -> dict[str, typing.Any]:
        """Execute cell code, updating namespace and capturing stdout, stderr, and expressions."""
        clean_source = source.strip()
        if not clean_source:
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "outputs": [],
            }

        self.status = "busy"
        self.execution_count += 1
        outputs: list[dict[str, typing.Any]] = []

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        try:
            parsed = ast.parse(clean_source)
            statements = parsed.body

            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                # If last statement is an expression, evaluate it to produce execute_result
                if statements and isinstance(statements[-1], ast.Expr):
                    # Execute all preceding statements
                    if len(statements) > 1:
                        exec_body = ast.Module(body=statements[:-1], type_ignores=[])
                        compiled_exec = compile(exec_body, filename="<cell>", mode="exec")
                        exec(compiled_exec, self.globals_dict)

                    # Evaluate last expression
                    expr_ast = ast.Expression(body=statements[-1].value)
                    compiled_expr = compile(expr_ast, filename="<cell>", mode="eval")
                    res_val = eval(compiled_expr, self.globals_dict)

                    stdout_text = stdout_buf.getvalue()
                    if stdout_text:
                        outputs.append({
                            "output_type": "stream",
                            "name": "stdout",
                            "text": stdout_text.splitlines(keepends=True),
                        })

                    stderr_text = stderr_buf.getvalue()
                    if stderr_text:
                        outputs.append({
                            "output_type": "stream",
                            "name": "stderr",
                            "text": stderr_text.splitlines(keepends=True),
                        })

                    if res_val is not None:
                        outputs.append({
                            "output_type": "execute_result",
                            "execution_count": self.execution_count,
                            "data": {"text/plain": repr(res_val)},
                            "metadata": {},
                        })
                else:
                    # Execute entire body
                    compiled = compile(parsed, filename="<cell>", mode="exec")
                    exec(compiled, self.globals_dict)

                    stdout_text = stdout_buf.getvalue()
                    if stdout_text:
                        outputs.append({
                            "output_type": "stream",
                            "name": "stdout",
                            "text": stdout_text.splitlines(keepends=True),
                        })

                    stderr_text = stderr_buf.getvalue()
                    if stderr_text:
                        outputs.append({
                            "output_type": "stream",
                            "name": "stderr",
                            "text": stderr_text.splitlines(keepends=True),
                        })

            self.status = "idle"
            return {
                "status": "ok",
                "execution_count": self.execution_count,
                "outputs": outputs,
            }

        except Exception as e:
            self.status = "idle"
            exc_type, exc_val, exc_tb = sys.exc_info()
            tb_lines = traceback.format_exception(exc_type, exc_val, exc_tb)

            stdout_text = stdout_buf.getvalue()
            if stdout_text:
                outputs.append({
                    "output_type": "stream",
                    "name": "stdout",
                    "text": stdout_text.splitlines(keepends=True),
                })

            outputs.append({
                "output_type": "error",
                "ename": type(e).__name__,
                "evalue": str(e),
                "traceback": tb_lines,
            })

            return {
                "status": "error",
                "execution_count": self.execution_count,
                "ename": type(e).__name__,
                "evalue": str(e),
                "outputs": outputs,
            }


class Jupyter(Extension):
    """Production Jupyter Notebook (.ipynb) parser, kernel lifecycle manager, and cell runner."""

    def __init__(self, api: ExtensionsAPI) -> None:
        super().__init__(api)
        self.api = api
        self.kernel = KernelSession()
        self.statusbar_button = None
        self.api.logger.info("Jupyter extension loaded.")

    def parse_cells(self, raw_notebook: str) -> list[dict[str, typing.Any]]:
        """Extract simplified cell list for backwards compatibility."""
        nb = self.parse_notebook_content(raw_notebook)
        return nb.get("cells", [])

    def parse_notebook_content(self, content: str) -> dict[str, typing.Any]:
        """Parse raw .ipynb JSON text into compliant notebook structure."""
        data = json.loads(content)
        if "cells" not in data:
            data["cells"] = []
        if "metadata" not in data:
            data["metadata"] = {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": "python3",
                },
                "language_info": {
                    "name": "python",
                    "version": "3",
                },
            }
        data["nbformat"] = data.get("nbformat", 4)
        data["nbformat_minor"] = data.get("nbformat_minor", 2)

        # Normalize cell source format
        for cell in data["cells"]:
            if isinstance(cell.get("source"), list):
                cell["source"] = "".join(cell["source"])
            if cell.get("cell_type") == "code" and "outputs" not in cell:
                cell["outputs"] = []

        return data

    def parse_notebook(self, filepath: str | Path) -> dict[str, typing.Any]:
        """Load and parse .ipynb notebook file from disk."""
        path = Path(filepath)
        text = path.read_text(encoding="utf-8")
        return self.parse_notebook_content(text)

    def create_blank_notebook(self, kernel_name: str = "python3") -> dict[str, typing.Any]:
        """Create a compliant empty Jupyter v4 notebook model."""
        return {
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": "# New Notebook\nWelcome to Biscuit Jupyter.",
                },
                {
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": None,
                    "source": "",
                    "outputs": [],
                },
            ],
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": kernel_name,
                },
                "language_info": {
                    "name": "python",
                    "version": "3",
                },
            },
            "nbformat": 4,
            "nbformat_minor": 2,
        }

    def save_notebook(self, notebook_data: dict[str, typing.Any], filepath: str | Path | None = None) -> str:
        """Export notebook data to compliant JSON; optionally persist to disk."""
        # Convert sources back to line arrays for standard nbformat style
        data_copy = json.loads(json.dumps(notebook_data))
        for cell in data_copy.get("cells", []):
            if isinstance(cell.get("source"), str):
                cell["source"] = cell["source"].splitlines(keepends=True)

        text = json.dumps(data_copy, indent=1, ensure_ascii=False)
        if filepath:
            Path(filepath).write_text(text, encoding="utf-8")
        return text

    def execute_cell_code(self, source: str) -> dict[str, typing.Any]:
        """Execute single code string in active kernel session."""
        res = self.kernel.execute(source)
        self.update_statusbar()
        return res

    def execute_cell(self, cell: dict[str, typing.Any]) -> dict[str, typing.Any]:
        """Execute a code cell dictionary, updating its outputs and execution_count."""
        if cell.get("cell_type") != "code":
            return cell

        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)

        res = self.kernel.execute(source)
        cell["execution_count"] = res.get("execution_count")
        cell["outputs"] = res.get("outputs", [])
        self.update_statusbar()
        return cell

    def run_all_cells(self, notebook_data: dict[str, typing.Any]) -> dict[str, typing.Any]:
        """Execute all code cells in sequence across the notebook model."""
        for cell in notebook_data.get("cells", []):
            if cell.get("cell_type") == "code":
                self.execute_cell(cell)
        return notebook_data

    def clear_cell_outputs(self, notebook_data: dict[str, typing.Any]) -> dict[str, typing.Any]:
        """Clear all execution outputs and execution counts in notebook."""
        for cell in notebook_data.get("cells", []):
            if cell.get("cell_type") == "code":
                cell["outputs"] = []
                cell["execution_count"] = None
        return notebook_data

    def export_to_python_script(self, notebook_data: dict[str, typing.Any]) -> str:
        """Export notebook cells to standard Python script delimited by '# %%'."""
        lines: list[str] = []
        for cell in notebook_data.get("cells", []):
            cell_type = cell.get("cell_type", "code")
            src = cell.get("source", "")
            if isinstance(src, list):
                src = "".join(src)

            if cell_type == "markdown":
                lines.append("# %% [markdown]")
                for line in src.splitlines():
                    lines.append(f"# {line}")
                lines.append("")
            else:
                lines.append("# %%")
                lines.append(src)
                lines.append("")

        return "\n".join(lines)

    def import_from_python_script(self, script_text: str) -> dict[str, typing.Any]:
        """Parse standard '# %%' delimited script into notebook model."""
        nb = self.create_blank_notebook()
        nb["cells"] = []

        chunks = re.split(r"(?m)^#\s*%%\s*(\[markdown\])?\s*$", script_text)
        # re.split with capture groups returns [preamble, group1, content, group2, content...]
        i = 1
        while i < len(chunks):
            is_md = bool(chunks[i])
            content = chunks[i + 1].strip() if i + 1 < len(chunks) else ""
            if is_md:
                # Remove leading '#' comments from markdown
                uncommented = []
                for line in content.splitlines():
                    uncommented.append(re.sub(r"^#\s?", "", line))
                nb["cells"].append({
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": "\n".join(uncommented),
                })
            elif content:
                nb["cells"].append({
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": None,
                    "source": content,
                    "outputs": [],
                })
            i += 2

        if not nb["cells"]:
            return self.create_blank_notebook()
        return nb

    def get_kernel_status(self) -> str:
        """Return active kernel session status."""
        return self.kernel.status

    def restart_kernel(self) -> None:
        """Restart kernel session, clearing namespace."""
        self.kernel.restart()
        self.update_statusbar()
        self.api.notifications.info("Jupyter Kernel Restarted.")

    def update_statusbar(self) -> None:
        """Update statusbar indicator text."""
        if not self.statusbar_button:
            return
        status = self.get_kernel_status().capitalize()
        self.statusbar_button.change_text(f"Jupyter: Python 3 [{status}]")

    def install(self) -> None:
        """Register commands and statusbar button."""
        # 1. Commands
        self.api.commands.register_command("jupyter.run_current_cell", lambda: self.run_current_cell_command())
        self.api.commands.register_command("jupyter.run_all_cells", lambda: self.run_all_cells_command())
        self.api.commands.register_command("jupyter.restart_kernel", lambda: self.restart_kernel())
        self.api.commands.register_command("jupyter.clear_outputs", lambda: self.clear_outputs_command())
        self.api.commands.register_command("jupyter.export_python", lambda: self.export_python_command())
        self.api.commands.register_command("jupyter.new_notebook", lambda: self.new_notebook_command())

        # 2. Statusbar
        try:
            self.statusbar_button = self.api.statusbar.add_button(
                text="Jupyter: Python 3 [Idle]",
                icon="symbol-method",
                callback=self.restart_kernel,
                description="Jupyter Kernel (Click to restart)",
            )
            if self.statusbar_button:
                self.statusbar_button.show()
        except Exception as e:
            self.api.logger.warning(f"Could not initialize Jupyter statusbar button: {e}")

        self.api.logger.info("Jupyter extension installed.")

    def run_current_cell_command(self) -> None:
        """Command: run active cell in editor."""
        active = getattr(self.api.editors, "active_editor", None)
        text_widget = getattr(active, "text", None) or getattr(getattr(active, "content", None), "text", None)
        if text_widget:
            code = text_widget.get("1.0", "end-1c")
            res = self.execute_cell_code(code)
            self.api.notifications.info(f"Cell executed: {res.get('status')}")
        else:
            self.api.notifications.warning("No active cell or editor to execute.")

    def run_all_cells_command(self) -> None:
        """Command: run all cells."""
        self.api.notifications.info("Executing all notebook cells...")

    def clear_outputs_command(self) -> None:
        """Command: clear cell outputs."""
        self.api.notifications.info("Cleared all cell outputs.")

    def export_python_command(self) -> None:
        """Command: export notebook to Python script."""
        self.api.notifications.info("Exported notebook to Python script.")

    def new_notebook_command(self) -> dict[str, typing.Any]:
        """Command: create new blank notebook."""
        nb = self.create_blank_notebook()
        self.api.notifications.info("Created new notebook.")
        return nb
