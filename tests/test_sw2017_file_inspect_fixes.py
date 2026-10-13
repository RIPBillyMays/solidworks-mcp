# Offline tests for field findings #10 (rebuild_document), #18 (list_faces/list_edges
# paging and filters) and #19 (capture_screenshot save_as).  COM objects are fakes.

from __future__ import annotations

import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solidworks_mcp import sw_core, sw_file, sw_inspect  # noqa: E402


def payload(res: dict[str, Any]) -> dict[str, Any]:
    return res.get("data", res)


class FakeDoc:
    def __init__(self) -> None:
        self.calls: list[str] = []


class RebuildTests(unittest.TestCase):
    def run_rebuild(
        self,
        detail: dict[str, Any],
        wrong: list[list[dict[str, Any]]],
        force_raises: bool = False,
        force_returns: Any = True,
        args: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[int]]:
        forced: list[int] = []

        class FM:
            def ForceRebuild3(self, top_only: Any) -> bool:
                forced.append(1)
                if force_raises:
                    raise RuntimeError("force failed")
                return force_returns

        feed = iter(wrong)
        last = [wrong[-1]]

        def fake_wrong(doc: Any) -> list[dict[str, Any]]:
            try:
                last[0] = next(feed)
            except StopIteration:
                pass
            return last[0]

        with mock.patch.object(sw_file, "active_document", return_value=(None, FakeDoc())), \
             mock.patch.object(sw_file, "rebuild_detail", return_value=detail), \
             mock.patch.object(sw_core, "whats_wrong", side_effect=fake_wrong), \
             mock.patch.object(sw_file, "flag_methods", return_value=FM()), \
             mock.patch.object(sw_file, "dialogs_suppressed", mock.MagicMock()):
            return payload(sw_file.rebuild_document(args or {})), forced

    def run_force_all(self, ext: Any, wrong: list[Any] | None = None) -> tuple[dict[str, Any], list[int]]:
        forced: list[int] = []

        class FM:
            def ForceRebuild3(self, top_only: Any) -> bool:
                forced.append(1)
                return True

        with mock.patch.object(sw_file, "active_document", return_value=(None, FakeDoc())),              mock.patch.object(sw_file, "extension", return_value=ext),              mock.patch.object(sw_core, "whats_wrong", return_value=wrong or []),              mock.patch.object(sw_file, "flag_methods", return_value=FM()),              mock.patch.object(sw_file, "dialogs_suppressed", mock.MagicMock()):
            return payload(sw_file.rebuild_document({"force_all": True})), forced

    def test_force_all_with_2017_property_style_member(self) -> None:
        class Ext:
            ForceRebuildAll = True  # late binding surfaces it as a bool property, not callable

        res, forced = self.run_force_all(Ext())
        self.assertEqual(res["rebuild_returned"], True)
        self.assertIsNone(res["rebuild_error"])
        self.assertEqual(forced, [])

    def test_force_all_with_method_style_member(self) -> None:
        class Ext:
            def ForceRebuildAll(self) -> bool:
                return True

        res, _ = self.run_force_all(Ext())
        self.assertEqual(res["rebuild_returned"], True)
        self.assertIsNone(res["rebuild_error"])

    def test_force_all_exception_reports_error_text(self) -> None:
        class Ext:
            @property
            def ForceRebuildAll(self) -> bool:
                raise RuntimeError("kaput")

        res, _ = self.run_force_all(Ext())
        self.assertIn("kaput", res["rebuild_error"])
        self.assertIn("ForceRebuildAll failed", res["rebuild_error"])

    def test_clean_rebuild_reports_raw_value(self) -> None:
        res, forced = self.run_rebuild({"ok": True, "raw": True, "error": None}, [[]])
        self.assertEqual(res["rebuild_returned"], True)
        self.assertEqual(res["warnings"], [])
        self.assertEqual(forced, [])

    def test_warnings_do_not_fail(self) -> None:
        warn = {"feature": "Fillet1", "code": 5, "is_warning": True}
        res, _ = self.run_rebuild({"ok": True, "raw": True, "error": None}, [[warn]])
        self.assertEqual(res["warnings"], [warn])
        self.assertEqual(res["problems"], [])

    def test_errors_still_fail(self) -> None:
        err = {"feature": "Boss1", "code": 3, "is_warning": False}
        res, forced = self.run_rebuild({"ok": True, "raw": True, "error": None}, [[err]])
        self.assertEqual(res["problems"], [err])
        self.assertEqual(forced, [])

    def test_exception_text_and_force_fallback(self) -> None:
        res, forced = self.run_rebuild({"ok": False, "raw": None, "error": "com_error: boom"}, [[], []])
        self.assertEqual(res["rebuild_error"], "com_error: boom")
        self.assertTrue(res["force_rebuild_used"])
        self.assertEqual(forced, [1])

    def test_force_failure_stays_not_ok(self) -> None:
        res, _ = self.run_rebuild({"ok": False, "raw": False, "error": None}, [[]], force_raises=True)
        self.assertIn("force_rebuild_error", res)
        self.assertNotIn("force_rebuild_used", res)

    def test_force_rebuild_false_is_not_ok(self) -> None:
        res, forced = self.run_rebuild({"ok": False, "raw": False, "error": None}, [[]], force_returns=False)
        self.assertEqual(forced, [1])
        self.assertNotIn("force_rebuild_used", res)
        self.assertEqual(res["force_rebuild_returned"], False)
        self.assertIn("force_rebuild_error", res)

    def test_force_rebuild_true_reports_raw(self) -> None:
        res, _ = self.run_rebuild({"ok": False, "raw": False, "error": None}, [[], []])
        self.assertTrue(res["force_rebuild_used"])
        self.assertEqual(res["force_rebuild_returned"], True)

    def test_rebuild_detail_captures_exception(self) -> None:
        with mock.patch.object(sw_core, "invoke_no_arg", side_effect=RuntimeError("nope")):
            out = sw_core.rebuild_detail(object())
        self.assertFalse(out["ok"])
        self.assertIn("nope", out["error"])
        with mock.patch.object(sw_core, "invoke_no_arg", return_value=False):
            out = sw_core.rebuild_detail(object())
        self.assertEqual((out["ok"], out["raw"]), (False, False))

    def test_whats_wrong_split(self) -> None:
        entries = [{"feature": "a", "is_warning": True}, {"feature": "b", "is_warning": False}]
        with mock.patch.object(sw_core, "whats_wrong", return_value=entries):
            errors, warnings = sw_core.whats_wrong_split(object())
        self.assertEqual([e["feature"] for e in errors], ["b"])
        self.assertEqual([w["feature"] for w in warnings], ["a"])


class Sentinel:
    """Compares by identity, like a COM identity check."""


def make_faces(n: int) -> list[dict[str, Any]]:
    return [
        {"index": i, "_obj": Sentinel(), "point_mm": [float(i), 0.0, 0.0], "_point_m": [i / 1000, 0, 0]}
        for i in range(n)
    ]


def make_edges(n: int) -> list[dict[str, Any]]:
    return [
        {
            "index": i, "_obj": Sentinel(), "point_mm": [float(i), 0.0, 0.0],
            "start_mm": [float(i), 0.0, 0.0], "end_mm": [float(i) + 1, 0.0, 0.0],
        }
        for i in range(n)
    ]


class ListingTests(unittest.TestCase):
    def faces(self, faces: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
        with mock.patch.object(sw_inspect, "active_document", return_value=(None, object())), \
             mock.patch.object(sw_inspect, "enumerate_faces", return_value=faces):
            return payload(sw_inspect.list_faces(args))

    def edges(self, edges: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any]:
        with mock.patch.object(sw_inspect, "active_document", return_value=(None, object())), \
             mock.patch.object(sw_inspect, "enumerate_edges", return_value=edges):
            return payload(sw_inspect.list_edges(args))

    def test_bad_limit_rejected(self) -> None:
        for bad in (0, -5):
            with self.assertRaises(ValueError):
                self.faces(make_faces(3), {"limit": bad})
        self.assertEqual(len(self.faces(make_faces(3), {"limit": None})["faces"]), 3)

    def test_default_limit_truncates(self) -> None:
        res = self.faces(make_faces(250), {})
        self.assertEqual(len(res["faces"]), 200)
        self.assertTrue(res["truncated"])
        self.assertEqual(res["total"], 250)
        self.assertEqual(res["total_faces"], 250)

    def test_small_listing_not_truncated(self) -> None:
        res = self.edges(make_edges(5), {})
        self.assertEqual(len(res["edges"]), 5)
        self.assertFalse(res["truncated"])

    def test_limit_and_offset(self) -> None:
        res = self.faces(make_faces(10), {"limit": 3, "offset": 8})
        self.assertEqual([f["index"] for f in res["faces"]], [8, 9])
        self.assertFalse(res["truncated"])
        res = self.faces(make_faces(10), {"limit": 3, "offset": 2})
        self.assertEqual([f["index"] for f in res["faces"]], [2, 3, 4])
        self.assertTrue(res["truncated"])

    def test_within_box(self) -> None:
        box = {"min": [2, -1, -1], "max": [5, 1, 1]}
        res = self.faces(make_faces(10), {"within_box": box})
        self.assertEqual([f["index"] for f in res["faces"]], [2, 3, 4, 5])
        # edges need both endpoints inside: edge 5 ends at x=6
        res = self.edges(make_edges(10), {"within_box": box})
        self.assertEqual([e["index"] for e in res["edges"]], [2, 3, 4])

    def test_within_box_swapped_corners_and_bad_input(self) -> None:
        res = self.faces(make_faces(10), {"within_box": {"min": [5, 1, 1], "max": [2, -1, -1]}})
        self.assertEqual(len(res["faces"]), 4)
        with self.assertRaises(ValueError):
            self.faces(make_faces(3), {"within_box": {"min": [0, 0]}})

    def test_feature_filter_faces_and_edges(self) -> None:
        faces = make_faces(6)
        edges = make_edges(6)
        feat_faces = [faces[1]["_obj"], faces[4]["_obj"]]

        class FakeFace:
            def __init__(self, own: list[Any]) -> None:
                self.own = own

            def GetEdges(self) -> list[Any]:
                return self.own

        class FakeFeature:
            def GetFaces(self) -> list[Any]:
                return [FakeFace([edges[0]["_obj"], edges[2]["_obj"]])]

        class FaceFeature:
            def GetFaces(self) -> list[Any]:
                return feat_faces

        with mock.patch.object(sw_inspect, "find_feature", return_value=FaceFeature()):
            res = self.faces(faces, {"feature": "Boss1"})
        self.assertEqual([f["index"] for f in res["faces"]], [1, 4])
        with mock.patch.object(sw_inspect, "find_feature", return_value=FakeFeature()):
            res = self.edges(edges, {"feature": "Boss1"})
        self.assertEqual([e["index"] for e in res["edges"]], [0, 2])

    def test_unknown_feature_raises(self) -> None:
        with mock.patch.object(sw_inspect, "find_feature", return_value=None):
            with self.assertRaises(ValueError):
                self.faces(make_faces(2), {"feature": "Nope"})

    def test_internal_keys_stripped(self) -> None:
        res = self.faces(make_faces(2), {})
        self.assertTrue(all("_obj" not in f for f in res["faces"]))


class ScreenshotTests(unittest.TestCase):
    def test_rejects_paths(self) -> None:
        for bad in ("a/b.png", "a\\b.png", "..", "../x.png", "x..png", "C:x.png", "", "  "):
            with self.assertRaises(ValueError, msg=bad):
                sw_inspect.screenshot_save_path(bad)

    def test_rejects_reserved_names(self) -> None:
        for bad in ("CON", "con.png", "NUL.txt", "Com1", "LPT9.png", "aux.tar.png"):
            with self.assertRaises(ValueError, msg=bad):
                sw_inspect.screenshot_save_path(bad)
        sw_inspect.screenshot_save_path("console.png")
        sw_inspect.screenshot_save_path("COM10.png")

    def test_accepts_plain_name_and_adds_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sw_inspect, "OUTPUT_ROOT", Path(tmp)):
                self.assertEqual(sw_inspect.screenshot_save_path("iso"), Path(tmp) / "screenshots" / "iso.png")
                self.assertEqual(sw_inspect.screenshot_save_path("a.PNG").name, "a.PNG")

    def _capture(self, tmp: str, save_as: str | None) -> tuple[Path | None, list[Path]]:
        class Ext:
            def SaveAs(self, path: str, *a: Any) -> bool:
                Path(path).write_bytes(b"\x89PNG fake")
                return True

        with mock.patch.object(sw_inspect, "OUTPUT_ROOT", Path(tmp)), \
             mock.patch.object(sw_inspect, "extension", return_value=Ext()), \
             mock.patch.object(sw_inspect, "byref_long", return_value=0), \
             mock.patch.object(sw_inspect, "nothing", return_value=None):
            data, kept = sw_inspect._capture_png(object(), 800, save_as)
        self.assertTrue(data)
        return kept, list((Path(tmp) / "screenshots").glob("*.png"))

    def test_file_kept_with_save_as(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kept, files = self._capture(tmp, "keep.png")
            self.assertEqual(kept, Path(tmp) / "screenshots" / "keep.png")
            self.assertEqual(files, [kept])

    def test_file_deleted_without_save_as(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kept, files = self._capture(tmp, None)
            self.assertIsNone(kept)
            self.assertEqual(files, [])

    def test_tool_rejects_bad_name_before_touching_sw(self) -> None:
        with mock.patch.object(sw_inspect, "active_document", side_effect=AssertionError("touched SW")):
            with self.assertRaises(ValueError):
                sw_inspect.capture_screenshot({"save_as": "../evil.png"})


if __name__ == "__main__":
    unittest.main()
