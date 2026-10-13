# Offline tests for batch A: extrude/cut/revolve end conditions, undo, selection,
# dialog suppression.  COM objects are fakes; no SOLIDWORKS is touched.

from __future__ import annotations

import inspect
import math
import sys
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solidworks_mcp import sw_core, sw_feature, sw_select


class FakeFM:
    """Records the positional arguments of every feature call."""

    def __init__(self, none_first: int = 0) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.none_first = none_first

    def _rec(self, name: str, args: tuple[Any, ...]) -> Any:
        self.calls.append((name, args))
        if self.none_first > 0:
            self.none_first -= 1
            return None
        return object()

    def FeatureExtrusion3(self, *a: Any) -> Any:
        return self._rec("FeatureExtrusion3", a)

    def FeatureExtrusionThin2(self, *a: Any) -> Any:
        return self._rec("FeatureExtrusionThin2", a)

    def FeatureCut4(self, *a: Any) -> Any:
        return self._rec("FeatureCut4", a)

    def FeatureCutThin2(self, *a: Any) -> Any:
        return self._rec("FeatureCutThin2", a)

    def FeatureRevolve2(self, *a: Any) -> Any:
        return self._rec("FeatureRevolve2", a)


class OldFM(FakeFM):
    """A SOLIDWORKS 2016-style manager: FeatureCut3 only."""

    def __getattribute__(self, name: str) -> Any:
        if name == "FeatureCut4":
            raise AttributeError(name)
        return super().__getattribute__(name)

    def FeatureCut3(self, *a: Any) -> Any:
        return self._rec("FeatureCut3", a)


class FakeDoc:
    def __init__(self) -> None:
        self.undo_steps: list[int] = []
        self.redo_steps: list[int] = []
        self.cleared = 0

    def _FlagAsMethod(self, *names: str) -> None:
        pass

    def EditUndo2(self, n: int) -> bool:
        self.undo_steps.append(n)
        return True

    def EditRedo2(self, n: int) -> bool:
        self.redo_steps.append(n)
        return True

    def ClearSelection2(self, flag: bool) -> None:
        self.cleared += 1


class FakeApp:
    def __init__(self, fail_toggle: int | None = None) -> None:
        self.toggles = {10: True, 77: True}
        self.fail_toggle = fail_toggle

    def GetUserPreferenceToggle(self, t: int) -> bool:
        return self.toggles[t]

    def SetUserPreferenceToggle(self, t: int, v: bool) -> None:
        if t == self.fail_toggle:
            raise RuntimeError("rejected")
        self.toggles[t] = v


class Harness:
    """Patch the feature module's live touch points and capture what is selected."""

    def __init__(self, fm: FakeFM) -> None:
        self.fm, self.doc = fm, FakeDoc()
        self.selected: list[tuple[dict[str, Any], int, bool]] = []
        self.objects: list[tuple[Any, int]] = []
        self.patches: list[Any] = []

    def __enter__(self) -> "Harness":
        def require_selection(doc: Any, spec: Any, mark: int = 0, append: bool = False) -> int:
            self.selected.append((spec, mark, append))
            return 1

        def select_object(doc: Any, obj: Any, mark: int = 0, append: bool = True) -> bool:
            self.objects.append((obj, mark))
            return True

        def feature_result(doc: Any, feature: Any, action: str, **data: Any) -> dict[str, Any]:
            return sw_core.result(feature is not None, action, **data)

        targets = {
            "require_part": lambda: (None, self.doc),
            "select_sketch_for_feature": lambda doc, name: name or "Sketch1",
            "feature_manager": lambda doc: self.fm,
            "require_selection": require_selection,
            "select_object": select_object,
            "feature_result": feature_result,
            "rename_feature": lambda f, n: None,
            "dialogs_suppressed": lambda: mock.MagicMock(),
        }
        for name, repl in targets.items():
            p = mock.patch.object(sw_feature, name, repl)
            p.start()
            self.patches.append(p)
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in self.patches:
            p.stop()


class ExtrudeTests(unittest.TestCase):
    def boss(self, args: dict[str, Any]) -> tuple[dict[str, Any], Harness]:
        with Harness(FakeFM()) as h:
            return sw_feature.boss_extrude(args), h

    def test_default_call_matches_legacy_arguments(self) -> None:
        out, h = self.boss({"depth_mm": 10})
        self.assertTrue(out["ok"])
        name, a = h.fm.calls[0]
        self.assertEqual(name, "FeatureExtrusion3")
        self.assertEqual(len(a), 23)
        self.assertEqual(a[:7], (True, False, False, 0, 0, 0.01, 0.01))
        self.assertEqual(a[17:], (True, True, True, 0, 0.0, False))

    def test_through_all_both_still_becomes_two_through_all(self) -> None:
        _, h = self.boss({"end_condition": "through_all_both"})
        a = h.fm.calls[0][1]
        self.assertEqual((a[0], a[3], a[4]), (False, 1, 1))

    def test_mid_plane_is_single_direction_type_6(self) -> None:
        _, h = self.boss({"end_condition": "mid_plane", "depth_mm": 20})
        a = h.fm.calls[0][1]
        self.assertEqual((a[0], a[3]), (True, 6))

    def test_second_direction_and_drafts(self) -> None:
        _, h = self.boss({
            "depth_mm": 10, "end_condition2": "blind", "depth2_mm": 5,
            "draft_deg": 3, "draft_outward": True, "draft2_deg": 2, "draft2_outward": False,
        })
        a = h.fm.calls[0][1]
        self.assertFalse(a[0])
        self.assertEqual((a[3], a[4]), (0, 0))
        self.assertAlmostEqual(a[5], 0.01)
        self.assertAlmostEqual(a[6], 0.005)
        self.assertEqual((a[7], a[8], a[9], a[10]), (True, True, True, False))
        self.assertAlmostEqual(a[11], math.radians(3))
        self.assertAlmostEqual(a[12], math.radians(2))

    def test_merge_false_is_passed(self) -> None:
        _, h = self.boss({"merge": False})
        self.assertFalse(h.fm.calls[0][1][17])

    def test_up_to_surface_selects_face_with_mark_1(self) -> None:
        out, h = self.boss({"end_condition": "up_to_surface", "target": {"face": 4}})
        self.assertTrue(out["ok"])
        self.assertEqual(h.selected, [({"faces": [4]}, 1, True)])
        self.assertEqual(h.fm.calls[0][1][3], 4)

    def test_offset_from_surface_uses_depth_as_offset_and_flip(self) -> None:
        _, h = self.boss({"end_condition": "offset_from_surface", "depth_mm": 2,
                          "target": {"face": 1}, "offset_reverse": True})
        a = h.fm.calls[0][1]
        self.assertEqual(a[3], 5)
        self.assertAlmostEqual(a[5], 0.002)
        self.assertTrue(a[13])

    def test_up_to_vertex_and_body(self) -> None:
        _, h = self.boss({"end_condition": "up_to_vertex", "target": {"vertex": 2}})
        self.assertEqual(h.selected[0][0], {"vertices": [2]})
        _, h = self.boss({"end_condition": "up_to_body", "target": {"body": 1}})
        self.assertEqual((h.selected[0][0], h.fm.calls[0][1][3]), ({"bodies": [1]}, 7))

    def test_through_next_needs_no_target(self) -> None:
        _, h = self.boss({"end_condition": "through_next"})
        self.assertEqual((h.selected, h.fm.calls[0][1][3]), ([], 2))

    def test_target_by_coordinates(self) -> None:
        _, h = self.boss({"end_condition": "up_to_surface",
                          "target": {"point": {"x_mm": 1, "y_mm": 2, "z_mm": 3}}})
        pts = h.selected[0][0]["points"]
        self.assertEqual(pts, [{"x_mm": 1, "y_mm": 2, "z_mm": 3, "type": "FACE"}])

    def test_target_by_body_name(self) -> None:
        bodies = [mock.MagicMock(Name="A"), mock.MagicMock(Name="B")]
        with mock.patch.object(sw_feature, "get_bodies", return_value=bodies), \
                mock.patch.object(sw_feature, "safe", side_effect=lambda o, m, d=None: o.Name):
            spec = sw_feature._target_to_selection(object(), {"body_name": "b"})
        self.assertEqual(spec, {"bodies": [1]})
        with mock.patch.object(sw_feature, "get_bodies", return_value=bodies), \
                mock.patch.object(sw_feature, "safe", side_effect=lambda o, m, d=None: o.Name):
            with self.assertRaises(RuntimeError):
                sw_feature._target_to_selection(object(), {"body_name": "zzz"})

    def test_target_by_feature_face(self) -> None:
        with mock.patch.object(sw_feature, "find_feature", return_value=mock.MagicMock()), \
                mock.patch.object(sw_feature, "safe", return_value=["f0", "f1"]), \
                mock.patch.object(sw_feature, "as_list", side_effect=lambda x: x):
            spec = sw_feature._target_to_selection(object(), {"feature": "Boss", "face_index": 1})
            self.assertEqual(spec, {"_objects": ["f1"]})
            with self.assertRaises(RuntimeError):
                sw_feature._target_to_selection(object(), {"feature": "Boss", "face_index": 5})

    def test_feature_face_target_selects_object_with_mark(self) -> None:
        with Harness(FakeFM()) as h, \
                mock.patch.object(sw_feature, "_target_to_selection", return_value={"_objects": ["F"]}):
            sw_feature.boss_extrude({"end_condition": "up_to_surface", "target": {"feature": "x"}})
        self.assertEqual(h.objects, [("F", 1)])

    def test_missing_target_is_rejected(self) -> None:
        with Harness(FakeFM()):
            with self.assertRaises(RuntimeError):
                sw_feature.boss_extrude({"end_condition": "up_to_surface"})

    def test_second_direction_target_uses_mark_2(self) -> None:
        _, h = self.boss({"end_condition2": "up_to_surface", "target2": {"face": 3}})
        self.assertEqual(h.selected, [({"faces": [3]}, 2, True)])
        self.assertEqual(h.fm.calls[0][1][4], 4)

    def test_invalid_combinations(self) -> None:
        with Harness(FakeFM()):
            for bad in (
                {"end_condition": "mid_plane", "end_condition2": "blind"},
                {"end_condition2": "mid_plane"},
                {"end_condition": "through_all_both", "thin": {"thickness_mm": 1}},
                {"end_condition": "bogus"},
            ):
                with self.assertRaises(RuntimeError, msg=str(bad)):
                    sw_feature.boss_extrude(bad)

    def test_thin_one_direction_and_cap(self) -> None:
        _, h = self.boss({"thin": {"thickness_mm": 2, "cap_ends": True, "reverse": True}})
        name, a = h.fm.calls[0]
        self.assertEqual(name, "FeatureExtrusionThin2")
        self.assertEqual(len(a), 30)
        self.assertAlmostEqual(a[18], 0.002)
        self.assertEqual(a[19], 0.0)
        self.assertAlmostEqual(a[20], 0.002)
        # RevThinDir is a swThinWallType_e: 1 = opposite direction.
        self.assertEqual((a[21], a[22]), (1, True))

    def test_thin_mid_plane_splits_and_two_directions(self) -> None:
        _, h = self.boss({"thin": {"thickness_mm": 4, "type": "mid_plane"}})
        a = h.fm.calls[0][1]
        # mid-plane: Thk1 is the total wall, thin type 2 in RevThinDir.
        self.assertEqual((a[18], a[19], a[21]), (0.004, 0.0, 2))
        _, h = self.boss({"thin": {"thickness_mm": 4, "type": "two_directions", "thickness2_mm": 1}})
        a = h.fm.calls[0][1]
        self.assertEqual((a[18], a[19], a[21]), (0.004, 0.001, 3))
        with Harness(FakeFM()):
            with self.assertRaises(RuntimeError):
                sw_feature.boss_extrude({"thin": {"thickness_mm": 4, "type": "two_directions"}})

    def test_schema_exposes_new_options(self) -> None:
        props = {t.name: t.inputSchema["properties"] for t in sw_core.TOOLS}
        for key in ("target", "end_condition2", "depth2_mm", "draft2_deg", "thin", "merge"):
            self.assertIn(key, props["boss_extrude"])
        for key in ("target", "flip_side", "thin", "draft_outward"):
            self.assertIn(key, props["cut_extrude"])
        for key in ("angle2_deg", "thin", "mid_plane"):
            self.assertIn(key, props["revolve"])
        self.assertNotIn("default", props["boss_extrude"]["end_condition2"])


class CutTests(unittest.TestCase):
    def cut(self, args: dict[str, Any], fm: FakeFM | None = None) -> tuple[dict[str, Any], Harness]:
        with Harness(fm or FakeFM()) as h:
            return sw_feature.cut_extrude(args), h

    def test_default_cut_args_length_and_values(self) -> None:
        _, h = self.cut({"depth_mm": 10})
        name, a = h.fm.calls[0]
        self.assertEqual((name, len(a)), ("FeatureCut4", 27))
        self.assertEqual(a[17:], (False, True, True, False, False, False, 0, 0.0, False, False))

    def test_flip_side_and_draft_outward(self) -> None:
        _, h = self.cut({"flip_side": True, "draft_deg": 5, "draft_outward": True})
        a = h.fm.calls[0][1]
        self.assertTrue(a[1])
        self.assertEqual((a[7], a[9]), (True, True))

    def test_through_all_both(self) -> None:
        _, h = self.cut({"end_condition": "through_all_both"})
        a = h.fm.calls[0][1]
        self.assertEqual((a[0], a[3], a[4]), (False, 1, 1))

    def test_target_reselected_on_retry(self) -> None:
        fm = FakeFM(none_first=1)
        out, h = self.cut({"end_condition": "up_to_surface", "target": {"face": 2}}, fm)
        self.assertEqual(len(fm.calls), 2)
        self.assertEqual(len(h.selected), 2)
        self.assertTrue(fm.calls[1][1][2])
        self.assertTrue(out["data"]["reversed_automatically"])

    def test_thin_cut(self) -> None:
        _, h = self.cut({"thin": {"thickness_mm": 1.5}})
        name, a = h.fm.calls[0]
        self.assertEqual((name, len(a)), ("FeatureCutThin2", 29))
        self.assertAlmostEqual(a[17], 0.0015)

    def test_cut3_fallback_drops_trailing_flag(self) -> None:
        fm = OldFM()
        with mock.patch.object(sw_core, "_UNFLAGGABLE_NAMES", set()):
            self.cut({}, fm)
        self.assertEqual((fm.calls[0][0], len(fm.calls[0][1])), ("FeatureCut3", 26))


class RevolveTests(unittest.TestCase):
    def rev(self, args: dict[str, Any]) -> FakeFM:
        fm = FakeFM()
        with Harness(fm):
            sw_feature.revolve(args)
        return fm

    def test_default_matches_legacy(self) -> None:
        a = self.rev({}).calls[0][1]
        self.assertEqual(len(a), 20)
        self.assertEqual((a[0], a[1], a[2], a[3], a[6], a[14]), (True, True, False, False, 0, 0))
        self.assertAlmostEqual(a[8], 2 * math.pi)

    def test_two_direction(self) -> None:
        a = self.rev({"angle_deg": 90, "angle2_deg": 45}).calls[0][1]
        self.assertFalse(a[0])
        self.assertAlmostEqual(a[8], math.radians(90))
        self.assertAlmostEqual(a[9], math.radians(45))

    def test_mid_plane(self) -> None:
        a = self.rev({"angle_deg": 120, "mid_plane": True}).calls[0][1]
        self.assertEqual((a[0], a[6]), (False, 6))

    def test_mid_plane_with_angle2_rejected(self) -> None:
        with Harness(FakeFM()):
            with self.assertRaises(RuntimeError):
                sw_feature.revolve({"mid_plane": True, "angle2_deg": 10})

    def test_thin(self) -> None:
        a = self.rev({"thin": {"thickness_mm": 2, "type": "two_directions", "thickness2_mm": 1},
                      "cut": True}).calls[0][1]
        # IsSolid stays True for thin revolves: False builds a surface body on 2017.
        self.assertEqual((a[1], a[2], a[3]), (True, True, True))
        self.assertEqual(a[14], 3)
        self.assertEqual((a[15], a[16]), (0.002, 0.001))


class DialogGuardTests(unittest.TestCase):
    def test_toggles_off_inside_and_restored(self) -> None:
        app = FakeApp()
        with sw_core.dialogs_suppressed(app):
            self.assertEqual(app.toggles, {10: False, 77: False})
        self.assertEqual(app.toggles, {10: True, 77: True})

    def test_restored_after_exception(self) -> None:
        app = FakeApp()
        with self.assertRaises(ValueError):
            with sw_core.dialogs_suppressed(app):
                raise ValueError("boom")
        self.assertEqual(app.toggles, {10: True, 77: True})

    def test_rejected_toggle_does_not_block_others(self) -> None:
        app = FakeApp(fail_toggle=10)
        with sw_core.dialogs_suppressed(app):
            self.assertFalse(app.toggles[77])
        self.assertTrue(app.toggles[77])

    def test_no_app_is_tolerated(self) -> None:
        with mock.patch.object(sw_core, "running_app", side_effect=RuntimeError("none")):
            with sw_core.dialogs_suppressed():
                pass

    def test_feature_tools_use_the_guard(self) -> None:
        for fn in (sw_feature.boss_extrude, sw_feature.cut_extrude, sw_feature.revolve):
            self.assertIn("dialogs_suppressed()", inspect.getsource(fn))

    def test_legacy_helper_untouched(self) -> None:
        self.assertTrue(callable(sw_core.dimension_dialog_suppressed))


class SelectToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = FakeDoc()
        self.names = [[{"name": "A"}, {"name": "B"}], [{"name": "A"}]]
        for p in (
            mock.patch.object(sw_select, "active_document", lambda: (None, self.doc)),
            mock.patch.object(sw_select, "selection_count", return_value=1),
            mock.patch.object(sw_select, "iter_features", side_effect=lambda d: self.names.pop(0)),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_tools_registered(self) -> None:
        names = {t.name for t in sw_core.TOOLS}
        self.assertTrue({"undo", "redo", "select_entity", "clear_selection", "boss_extrude"} <= names)

    def test_undo_reports_counts(self) -> None:
        out = sw_select.undo({"count": 2})
        self.assertTrue(out["ok"])
        self.assertEqual(self.doc.undo_steps, [2])
        self.assertEqual((out["data"]["features_before"], out["data"]["features_after"]), (2, 1))
        self.assertTrue(out["data"]["feature_tree_changed"])

    def test_redo(self) -> None:
        sw_select.redo({})
        self.assertEqual(self.doc.redo_steps, [1])

    def test_select_by_name(self) -> None:
        with mock.patch.object(sw_select, "select_by_id", return_value=True) as sel:
            out = sw_select.select_entity({"type": "face", "name": "Face<1>"})
        self.assertTrue(out["ok"])
        self.assertEqual(sel.call_args[0][1:3], ("Face<1>", "FACE"))

    def test_select_by_point_converts_to_metres(self) -> None:
        ext = mock.MagicMock()
        ext.SelectByID2.return_value = True
        with mock.patch.object(sw_select, "extension", return_value=ext):
            out = sw_select.select_entity({"type": "FACE", "x_mm": 10, "y_mm": 0, "z_mm": 5})
        self.assertTrue(out["ok"])
        args = ext.SelectByID2.call_args[0]
        self.assertEqual((args[1], args[2], args[4]), ("FACE", 0.01, 0.005))

    def test_select_by_ray(self) -> None:
        ext = mock.MagicMock()
        ext.SelectByRay.return_value = True
        with mock.patch.object(sw_select, "extension", return_value=ext):
            out = sw_select.select_entity({"type": "FACE", "ray": True, "x_mm": 0, "y_mm": 0, "z_mm": 100,
                                           "dir_x": 0, "dir_y": 0, "dir_z": -1})
        self.assertTrue(out["ok"])
        self.assertEqual(ext.SelectByRay.call_args[0][7], 2)

    def test_select_needs_something(self) -> None:
        self.assertFalse(sw_select.select_entity({"type": "FACE"})["ok"])
        self.assertFalse(sw_select.select_entity(
            {"type": "FACE", "ray": True, "x_mm": 0, "y_mm": 0, "z_mm": 0})["ok"])

    def test_clear_selection_tool(self) -> None:
        out = sw_select.clear_selection_tool({})
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(self.doc.cleared, 1)


if __name__ == "__main__":
    unittest.main()
