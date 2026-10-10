# Offline tests for the Phase 5 tools: list_open_documents, close_document, delete_mate.
# COM objects are replaced with fakes; no SOLIDWORKS is touched.

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

from solidworks_mcp import sw_assembly, sw_core, sw_file


class FakeDoc:
    def __init__(self, title: str, path: str = "", dirty: bool = False, save_ok: bool = True) -> None:
        self.GetTitle, self.GetPathName, self.GetSaveFlag, self.GetType = title, path, dirty, 1
        self.save_ok, self.saved = save_ok, False

    def Save3(self, options: int, errors: Any, warnings: Any) -> bool:
        self.saved = self.save_ok
        return self.save_ok


class FakeApp:
    def __init__(self, docs: list[FakeDoc], active: FakeDoc | None = None) -> None:
        self.docs, self.ActiveDoc, self.closed = docs, active, []

    @property
    def GetDocuments(self) -> list[FakeDoc]:
        return list(self.docs)

    def CloseDoc(self, name: str) -> None:
        self.closed.append(name)
        self.docs = [d for d in self.docs if d.GetTitle != name]


def _run(app: FakeApp, handler: Any, args: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    with unittest.mock.patch.object(sw_file, "running_app", return_value=app):
        if root is None:
            return handler(args)
        with unittest.mock.patch.object(sw_file, "OUTPUT_ROOT", root):
            return handler(args)


class DocumentToolTests(unittest.TestCase):
    def test_tools_registered(self) -> None:
        names = {t.name for t in sw_core.TOOLS}
        self.assertTrue({"list_open_documents", "close_document", "delete_mate"} <= names)

    def test_list_open_documents(self) -> None:
        app = FakeApp([FakeDoc("a.SLDPRT", "C:/x/a.sldprt", True), FakeDoc("Part2")])
        out = _run(app, sw_file.list_open_documents, {})
        self.assertTrue(out["ok"])
        docs = out["data"]["documents"]
        self.assertEqual([d["title"] for d in docs], ["a.SLDPRT", "Part2"])
        self.assertTrue(docs[0]["dirty"])
        self.assertEqual(docs[0]["document_type"], "part")

    def test_close_clean_active(self) -> None:
        doc = FakeDoc("Part1")
        app = FakeApp([doc, FakeDoc("Part2")], active=doc)
        out = _run(app, sw_file.close_document, {})
        self.assertTrue(out["ok"])
        self.assertEqual(app.closed, ["Part1"])
        self.assertEqual(out["data"]["remaining_documents"], 1)

    def test_dirty_refused_without_save_or_force(self) -> None:
        doc = FakeDoc("Part1", dirty=True)
        app = FakeApp([doc], active=doc)
        out = _run(app, sw_file.close_document, {"title": "part1"})
        self.assertFalse(out["ok"])
        self.assertEqual(app.closed, [])

    def test_force_discards(self) -> None:
        doc = FakeDoc("Part1", dirty=True)
        app = FakeApp([doc], active=doc)
        self.assertTrue(_run(app, sw_file.close_document, {"title": "Part1", "force": True})["ok"])
        self.assertEqual(app.closed, ["Part1"])

    def test_unknown_title(self) -> None:
        app = FakeApp([FakeDoc("Part1")])
        self.assertFalse(_run(app, sw_file.close_document, {"title": "nope"})["ok"])

    def test_save_unsaved_new_doc_refused(self) -> None:
        doc = FakeDoc("Part1", dirty=True)
        app = FakeApp([doc], active=doc)
        out = _run(app, sw_file.close_document, {"save": True}, Path(tempfile.gettempdir()).resolve())
        self.assertFalse(out["ok"])
        self.assertIn("save_document", out["message"])
        self.assertFalse(doc.saved)

    def test_save_outside_output_root_refused(self) -> None:
        root = Path(tempfile.mkdtemp()).resolve()
        doc = FakeDoc("a", str(Path(tempfile.gettempdir()).resolve() / "other" / "a.sldprt"), True)
        app = FakeApp([doc], active=doc)
        out = _run(app, sw_file.close_document, {"save": True}, root)
        self.assertFalse(out["ok"])
        self.assertFalse(doc.saved)
        self.assertEqual(app.closed, [])

    def test_save_inside_output_root_saves_then_closes(self) -> None:
        root = Path(tempfile.mkdtemp()).resolve()
        doc = FakeDoc("a", str(root / "a.sldprt"), True)
        app = FakeApp([doc], active=doc)
        out = _run(app, sw_file.close_document, {"save": True}, root)
        self.assertTrue(out["ok"])
        self.assertTrue(doc.saved)
        self.assertEqual(app.closed, ["a"])

    def test_save_failure_does_not_close(self) -> None:
        root = Path(tempfile.mkdtemp()).resolve()
        doc = FakeDoc("a", str(root / "a.sldprt"), True, save_ok=False)
        app = FakeApp([doc], active=doc)
        self.assertFalse(_run(app, sw_file.close_document, {"save": True}, root)["ok"])
        self.assertEqual(app.closed, [])


class FakeFeature:
    def __init__(self, name: str, type_name: str, sub: "FakeFeature | None" = None, nxt: "FakeFeature | None" = None) -> None:
        self.Name, self.GetTypeName2 = name, type_name
        self.GetFirstSubFeature, self.GetNextSubFeature, self.GetNextFeature = sub, nxt, nxt
        self.selected = False

    def Select2(self, append: bool, mark: int) -> bool:
        self.selected = True
        return True


class FakeExt:
    def __init__(self) -> None:
        self.deleted = False

    def DeleteSelection2(self, options: int) -> bool:
        self.deleted = True
        return True


class DeleteMateTests(unittest.TestCase):
    def _run(self, name: str) -> tuple[dict[str, Any], FakeFeature, FakeExt]:
        m2 = FakeFeature("Distance1", "MateDistanceDim")
        m1 = FakeFeature("Coincident1", "MateCoincident", nxt=m2)
        group = FakeFeature("Mates", "MateGroup", sub=m1)
        # The group is the only top-level feature the walker sees.
        group.GetNextFeature = None
        doc = unittest.mock.MagicMock()
        doc.FirstFeature = group
        ext = FakeExt()
        with unittest.mock.patch.object(sw_assembly, "require_assembly", return_value=(None, doc)), \
             unittest.mock.patch.object(sw_assembly, "clear_selection"), \
             unittest.mock.patch.object(sw_assembly, "rebuild"), \
             unittest.mock.patch.object(sw_core, "extension", return_value=ext), \
             unittest.mock.patch.object(sw_core, "selectable", side_effect=lambda f: f):
            out = sw_assembly.delete_mate({"mate_name": name})
        return out, m2, ext

    def test_deletes_named_mate(self) -> None:
        out, mate, ext = self._run("Distance1")
        self.assertTrue(out["ok"], out)
        self.assertTrue(mate.selected and ext.deleted)

    def test_unknown_mate(self) -> None:
        out, _, ext = self._run("Nope")
        self.assertFalse(out["ok"])
        self.assertFalse(ext.deleted)


if __name__ == "__main__":
    unittest.main()
