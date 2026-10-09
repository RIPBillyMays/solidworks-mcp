# Offline regression tests for the SOLIDWORKS 2017 compatibility fixes (fork).
#
# No SOLIDWORKS is needed or touched: COM objects are replaced with fakes, in the
# style of tests/test_sw_core.py.
#
#     .venv\Scripts\python.exe -m unittest discover -s tests -v

from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

import pythoncom
import win32com.client

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PACKAGE = "solidworks_mcp"
PACKAGE_DIR = ROOT / PACKAGE

from solidworks_mcp import sw_core, sw_file, sw_inspect

# Third-party modules the package imports lazily because they are optional
# (sw_inspect.capture_screenshot wraps Pillow in try/except), so an
# unresolvable one is not a packaging bug.
OPTIONAL_THIRD_PARTY = {"PIL"}


def _function_level_imports(path: Path) -> list[tuple[int, int, str | None, list[str]]]:
    """Return (lineno, level, module, imported names) for imports inside functions."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, int, str | None, list[str]]] = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.append((node.lineno, 0, alias.name, []))
            elif isinstance(node, ast.ImportFrom):
                found.append((node.lineno, node.level, node.module, [a.name for a in node.names]))
    return found


class FunctionLevelImportTests(unittest.TestCase):
    """Function-level imports only fail at call time, so the test suite never saw them.

    Upstream had nine ``from sw_core import ...`` lines inside tool functions.
    ``sw_core`` is not a top-level module when the server runs as a package, so
    each one raised ModuleNotFoundError the first time its tool was called.
    """

    def test_package_modules_are_found(self) -> None:
        # Guards the guard: an empty walk would make the real test vacuous.
        self.assertGreater(len(list(PACKAGE_DIR.glob("sw_*.py"))), 5)

    def test_every_function_level_import_resolves_as_a_package_import(self) -> None:
        siblings = {p.stem for p in PACKAGE_DIR.glob("*.py")}
        checked = 0
        problems: list[str] = []
        for path in sorted(PACKAGE_DIR.glob("*.py")):
            for lineno, level, module, names in _function_level_imports(path):
                where = f"{path.name}:{lineno}"
                checked += 1
                try:
                    if level == 0:
                        top = (module or "").split(".")[0]
                        if top in siblings:
                            problems.append(f"{where}: bare import of package module '{module}' (use a relative import)")
                            continue
                        if top in OPTIONAL_THIRD_PARTY:
                            continue
                        if importlib.util.find_spec(top) is None:
                            problems.append(f"{where}: cannot resolve '{module}'")
                        continue
                    target = importlib.import_module("." * level + (module or ""), PACKAGE)
                    for name in names:
                        if name != "*" and not hasattr(target, name):
                            try:
                                importlib.import_module(f"{target.__name__}.{name}")
                            except ImportError:
                                problems.append(f"{where}: '{target.__name__}' has no '{name}'")
                except ImportError as exc:
                    problems.append(f"{where}: {exc}")
        self.assertGreater(checked, 0, "no function-level imports were found; the walker is broken")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_a_bare_sibling_import_is_detected(self) -> None:
        """The walker must report ``from sw_core import x`` inside a function."""
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.py"
            bad.write_text("def f():\n    from sw_core import nothing\n    return nothing\n", encoding="utf-8")
            found = _function_level_imports(bad)
        self.assertEqual(found, [(2, 0, "sw_core", ["nothing"])])
        self.assertIn("sw_core", {p.stem for p in PACKAGE_DIR.glob("*.py")})


class FakeApp:
    """Records the preference ids asked of GetUserPreferenceStringValue."""

    def __init__(self, template: str) -> None:
        self.template = template
        self.asked: list[int] = []
        self.created_with: list[str] = []

    def GetUserPreferenceStringValue(self, preference: int) -> str:
        self.asked.append(preference)
        return self.template

    def NewDocument(self, template: str, paper: int, width: float, height: float) -> object:
        self.created_with.append(template)
        return object()


class NewDocumentTemplateTests(unittest.TestCase):
    def _ask(self, kind: str, template: str) -> FakeApp:
        app = FakeApp(template)
        with unittest.mock.patch.object(sw_file, "running_app", return_value=app), \
                unittest.mock.patch.object(sw_file, "document_info", return_value={}):
            reply = sw_file.new_document(kind)
        self.assertFalse(reply.get("isError", False), reply)
        return app

    def test_default_template_preference_ids_are_8_9_10(self) -> None:
        # swUserPreferenceStringValue_e: DefaultTemplatePart/Assembly/Drawing.
        with tempfile.NamedTemporaryFile(suffix=".prtdot") as tpl:
            for kind, expected in (("part", 8), ("assembly", 9), ("drawing", 10)):
                with self.subTest(kind=kind):
                    app = self._ask(kind, tpl.name)
                    self.assertEqual(app.asked, [expected])
                    self.assertEqual(app.created_with, [tpl.name])

    def test_missing_preference_falls_back_to_discovery(self) -> None:
        app = FakeApp("")
        with tempfile.NamedTemporaryFile(suffix=".prtdot") as tpl, \
                unittest.mock.patch.object(sw_file, "running_app", return_value=app), \
                unittest.mock.patch.object(sw_file, "document_info", return_value={}), \
                unittest.mock.patch.object(sw_file, "discover_template", return_value=Path(tpl.name)):
            sw_file.new_document("part")
        self.assertEqual(app.created_with, [tpl.name])


class FakeMeasure:
    """An IMeasure whose Calculate records its arguments like a flagged method."""

    def __init__(self) -> None:
        self.flagged: list[str] = []
        self.calls: list[tuple[Any, ...]] = []

    def _FlagAsMethod(self, *names: str) -> None:
        self.flagged.extend(names)

    def Calculate(self, *args: Any) -> bool:
        self.calls.append(args)
        return True


class FakeExtension:
    def __init__(self, measure: FakeMeasure) -> None:
        self.CreateMeasure = measure


class MeasureTests(unittest.TestCase):
    def test_calculate_gets_one_null_dispatch_argument(self) -> None:
        # 2017's IMeasure.Calculate(Entities) is not optional; null = use the selection.
        measure = FakeMeasure()
        with unittest.mock.patch.object(sw_inspect, "active_document", return_value=(object(), object())), \
                unittest.mock.patch.object(sw_inspect, "apply_selection", return_value=2), \
                unittest.mock.patch.object(sw_inspect, "clear_selection"), \
                unittest.mock.patch.object(sw_inspect, "extension", return_value=FakeExtension(measure)):
            reply = sw_inspect.measure({"selection": {"faces": []}})
        self.assertFalse(reply.get("isError", False), reply)
        self.assertEqual(len(measure.calls), 1)
        self.assertEqual(len(measure.calls[0]), 1)
        arg = measure.calls[0][0]
        self.assertIsInstance(arg, win32com.client.VARIANT)
        self.assertEqual(arg.varianttype, pythoncom.VT_DISPATCH)
        self.assertIsNone(arg.value)
        self.assertIn("Calculate", measure.flagged)


class ExtensionMethodListTests(unittest.TestCase):
    def test_saveas3_is_not_flagged_on_the_extension(self) -> None:
        # IModelDocExtension.SaveAs3 is absent from the 2017 type library.
        self.assertNotIn("SaveAs3", sw_core._EXTENSION_METHODS)


if __name__ == "__main__":
    unittest.main()
