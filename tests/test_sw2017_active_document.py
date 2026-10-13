# Offline tests for finding #3: results name the document they used, and
# activate_document switches and verifies.  COM objects are fakes.

from __future__ import annotations

import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solidworks_mcp import sw_core, sw_file  # noqa: E402


class FakeDoc:
    def __init__(self, title: str) -> None:
        self.GetTitle, self.GetType, self.GetPathName, self.GetSaveFlag = title, 1, "", False


class FakeApp:
    def __init__(self, titles: list[str], switch_works: bool = True) -> None:
        self.docs = [FakeDoc(t) for t in titles]
        self.ActiveDoc: Any = self.docs[0]
        self.switch_works = switch_works
        self.activated: list[str] = []

    @property
    def GetDocuments(self) -> list[FakeDoc]:
        return list(self.docs)

    def ActivateDoc3(self, title: str, *rest: Any) -> Any:
        self.activated.append(title)
        if self.switch_works:
            self.ActiveDoc = next(d for d in self.docs if d.GetTitle == title)


def _patched(app: FakeApp):
    ident = lambda obj, *names: obj  # noqa: E731
    stack = unittest.mock.patch.multiple(sw_core, running_app=lambda: app, flag_methods=ident)
    stack2 = unittest.mock.patch.multiple(sw_file, running_app=lambda: app, flag_methods=ident)
    return _Both(stack, stack2)


class _Both:
    def __init__(self, *managers: Any) -> None:
        self.managers = managers

    def __enter__(self) -> None:
        for m in self.managers:
            m.__enter__()

    def __exit__(self, *exc: Any) -> None:
        for m in reversed(self.managers):
            m.__exit__(*exc)


class ActiveDocumentTitleTests(unittest.TestCase):
    def setUp(self) -> None:
        sw_core.begin_call()

    def test_doc_tool_result_names_document(self) -> None:
        app = FakeApp(["Part1", "Assem1"])
        with _patched(app):
            out = sw_file.get_active_document_info({})
        self.assertTrue(out["ok"])
        self.assertEqual(out["active_document"], "Part1")
        self.assertIn("document", out["data"])  # existing keys intact

    def test_no_document_tool_has_no_field(self) -> None:
        app = FakeApp(["Part1"])
        with _patched(app):
            out = sw_file.list_open_documents({})
        self.assertNotIn("active_document", out)

    def test_no_leak_between_calls(self) -> None:
        app = FakeApp(["Part1"])
        with _patched(app):
            first = sw_file.get_active_document_info({})
            sw_core.begin_call()  # what server.call_tool does per call
            second = sw_file.list_open_documents({})
        self.assertEqual(first["active_document"], "Part1")
        self.assertNotIn("active_document", second)

    def test_follows_document_switch(self) -> None:
        app = FakeApp(["Part1", "Assem1"])
        with _patched(app):
            sw_file.get_active_document_info({})
            app.ActiveDoc = app.docs[1]
            sw_core.begin_call()
            out = sw_file.get_active_document_info({})
        self.assertEqual(out["active_document"], "Assem1")


class ActivateDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        sw_core.begin_call()

    def test_registered(self) -> None:
        self.assertIn("activate_document", {t.name for t in sw_core.TOOLS})

    def test_success_case_insensitive(self) -> None:
        app = FakeApp(["Part1", "Assem1"])
        with _patched(app):
            out = sw_file.activate_document({"title": "assem1"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(app.activated, ["Assem1"])
        self.assertEqual(out["active_document"], "Assem1")
        self.assertEqual(out["data"]["document"]["title"], "Assem1")

    def test_no_match(self) -> None:
        app = FakeApp(["Part1"])
        with _patched(app):
            out = sw_file.activate_document({"title": "Nope"})
        self.assertFalse(out["ok"])
        self.assertEqual(app.activated, [])

    def test_switch_failed(self) -> None:
        app = FakeApp(["Part1", "Assem1"], switch_works=False)
        with _patched(app):
            out = sw_file.activate_document({"title": "Assem1"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["data"]["actual"], "Part1")
        self.assertEqual(out["active_document"], "Part1")  # the doc actually active


class StampingTests(unittest.TestCase):
    def test_new_document_stamps_active(self) -> None:
        app = FakeApp(["Part1"])
        app.GetUserPreferenceStringValue = lambda pref: __file__
        app.NewDocument = lambda *a: app.docs.append(FakeDoc("Part2")) or setattr(app, "ActiveDoc", app.docs[-1]) or app.ActiveDoc
        sw_core.begin_call()
        with _patched(app):
            out = sw_file.new_document("part")
        self.assertEqual(out["active_document"], "Part2")

    def test_open_document_stamps_active(self) -> None:
        app = FakeApp(["Part1"])
        app.OpenDoc6 = lambda *a: app.docs[0]
        app.ActivateDoc3 = lambda *a: True
        sw_core.begin_call()
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.sldprt"
            f.write_bytes(b"")
            with _patched(app):
                out = sw_file.open_document({"path": str(f)})
        self.assertEqual(out["active_document"], "Part1")

    def test_close_document_has_no_active_document(self) -> None:
        app = FakeApp(["Part1"])
        app.CloseDoc = lambda t: None
        sw_core.begin_call()
        with _patched(app):
            out = sw_file.close_document({"title": "Part1", "force": True})
        self.assertNotIn("active_document", out)
        self.assertEqual(out["data"]["closed"], "Part1")


class ServerLeakTests(unittest.TestCase):
    def test_unknown_tool_does_not_leak_title(self) -> None:
        import asyncio
        import json
        from solidworks_mcp import server

        sw_core.note_active_document("Stale")
        out = asyncio.run(server.call_tool("no_such_tool", {}))
        payload = json.loads(out[0].text)
        self.assertFalse(payload["ok"])
        self.assertNotIn("active_document", payload)


if __name__ == "__main__":
    unittest.main()
