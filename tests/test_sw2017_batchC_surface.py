# Offline tests for Batch C3 surface tools (plan items 3.1-3.8).  COM objects are
# fakes that record the exact member and argument count; no SOLIDWORKS is touched.

from __future__ import annotations

import sys
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from solidworks_mcp import sw_core, sw_surface
from test_sw2017_enums import ev

TOOL_NAMES = (
    "surface_extrude", "surface_revolve", "surface_loft", "surface_offset", "surface_knit",
    "thicken", "surface_trim", "replace_face",
)


def snap(**over: Any) -> dict[str, Any]:
    base = {
        "features": 3, "surface_bodies": 0, "surface_body_names": [], "solid_bodies": 0,
        "surface_area_mm2": 0.0, "volume_mm3": 0.0, "bbox_mm": [0, 0, 0, 1, 1, 1],
    }
    base.update(over)
    return base


class FakeFM:
    def __init__(self, returns: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.returns = returns or {}

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args: Any) -> Any:
            self.calls.append((name, args))
            return self.returns.get(name, object())

        return call

    def last(self, name: str) -> tuple[Any, ...]:
        return [a for n, a in self.calls if n == name][-1]

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


class FakeDoc:
    """Void-returning IModelDoc2 members record their call and return None."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def _rec(self, name: str, args: tuple[Any, ...]) -> None:
        self.calls.append((name, args))

    def InsertLoftRefSurface2(self, *a: Any) -> None:
        self._rec("InsertLoftRefSurface2", a)

    def InsertOffsetSurface(self, *a: Any) -> None:
        self._rec("InsertOffsetSurface", a)

    def InsertFeatureReplaceFace(self, *a: Any) -> None:
        self._rec("InsertFeatureReplaceFace", a)


class Harness:
    """Patch the live touch points of sw_surface; ``snaps`` feeds before/after states."""

    def __init__(self, snaps: list[dict[str, Any]], fm: FakeFM | None = None, new_feature: Any = "auto",
                 select_ok: bool = True) -> None:
        self.fm = fm or FakeFM()
        self.doc = FakeDoc()
        self.snaps = list(snaps)
        self.select_ok = select_ok
        self.new_feature = object() if new_feature == "auto" else new_feature
        self.selections: list[tuple[Any, int, bool]] = []
        self.by_id: list[tuple[str, str, int, bool]] = []
        self.objects: list[tuple[Any, int]] = []
        self.sketch_selected: list[Any] = []
        self.patches: list[Any] = []
        self.com_touched = False

    def __enter__(self) -> "Harness":
        def require_part() -> tuple[None, FakeDoc]:
            self.com_touched = True
            return None, self.doc

        def apply_selection(doc: Any, spec: Any, mark: int = 0, append: bool = False) -> int:
            self.selections.append((spec, mark, append))
            return 1

        def select_by_id(doc: Any, name: str, kind: str, mark: int = 0, append: bool = False, ext: Any = None) -> bool:
            self.by_id.append((name, kind, mark, append))
            return self.select_ok

        def select_object(doc: Any, obj: Any, mark: int = 0, append: bool = True) -> bool:
            self.objects.append((obj, mark))
            return True

        def select_sketch(doc: Any, name: Any) -> str:
            self.sketch_selected.append(name)
            return name or "Sketch1"

        patch = {
            "require_part": require_part,
            "exit_active_sketch": lambda doc: None,
            "feature_manager": lambda doc: self.fm,
            "dialogs_suppressed": lambda: mock.MagicMock(),
            "clear_selection": lambda doc: None,
            "rename_feature": lambda f, n: None,
            "feature_result": lambda doc, f, action, **d: sw_core.result(f is not None, action, **d),
            "apply_selection": apply_selection,
            "select_by_id": select_by_id,
            "select_object": select_object,
            "select_sketch_for_feature": select_sketch,
            "_snapshot": lambda doc: self.snaps.pop(0),
            "_feature_names": lambda doc: [],
            "_feature_created_after": lambda doc, before: self.new_feature,
            "_sheet_faces": lambda doc: ["faceA", "faceB"],
        }
        for name, repl in patch.items():
            p = mock.patch.object(sw_surface, name, repl)
            p.start()
            self.patches.append(p)
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in self.patches:
            p.stop()


class ConstantAndRegistrationTests(unittest.TestCase):
    def test_constants_match_2017_enums(self) -> None:
        self.assertEqual(sw_surface.START_SKETCH_PLANE, ev("swStartConditions_e.swStartSketchPlane"))
        self.assertEqual(sw_surface.REVOLVE_ONE_DIRECTION, ev("swRevolveType_e.swRevolveTypeOneDirection"))
        self.assertEqual(sw_surface.REVOLVE_TWO_DIRECTIONS, ev("swRevolveType_e.swRevolveTypeTwoDirection"))
        self.assertEqual(sw_core.END_CONDITIONS["mid_plane"], ev("swEndConditions_e.swEndCondMidPlane"))
        self.assertEqual(sw_core.END_CONDITIONS["blind"], ev("swEndConditions_e.swEndCondBlind"))

    def test_tools_registered_with_handlers(self) -> None:
        registered = {t.name for t in sw_core.TOOLS}
        for name in TOOL_NAMES:
            self.assertIn(name, registered)
            self.assertIn(name, sw_core.HANDLERS)

    def test_members_flagged_for_late_binding(self) -> None:
        fm = sw_core._registered("IFeatureManager")
        for name in ("FeatureExtruRefSurface3", "InsertRevolvedRefSurface", "InsertSewRefSurface",
                     "FeatureBossThicken", "PreTrimSurface", "PostTrimSurface"):
            self.assertIn(name, fm)
        doc = sw_core._registered("IModelDoc2")
        for name in ("InsertLoftRefSurface2", "InsertOffsetSurface", "InsertFeatureReplaceFace"):
            self.assertIn(name, doc)

    def test_fences_do_not_cover_new_tools(self) -> None:
        from solidworks_mcp.sw2017_fences import FENCES

        # surface_trim is fenced after live C3 (PostTrimSurface returns Nothing).
        for name in TOOL_NAMES + ("edit_feature",):
            if name != "surface_trim":
                self.assertNotIn(name, FENCES)
        self.assertIn("surface_trim", FENCES)


class SurfaceExtrudeTests(unittest.TestCase):
    def test_exact_call_22_args_and_one_new_surface(self) -> None:
        with Harness([snap(), snap(surface_bodies=1, surface_body_names=["Surface-Extrude1"], surface_area_mm2=800.0)]) as h:
            out = sw_surface.surface_extrude({"sketch_name": "S1", "depth_mm": 10, "reverse": True})
        self.assertTrue(out["ok"], out)
        a = h.fm.last("FeatureExtruRefSurface3")
        self.assertEqual(len(a), 22)
        self.assertEqual(a[:8], (True, True, 0, 0.0, 0, 0, 0.01, 0.0))
        self.assertEqual(h.sketch_selected, ["S1"])
        self.assertEqual(out["data"]["surface_bodies"], ["Surface-Extrude1"])

    def test_mid_plane_and_second_direction(self) -> None:
        with Harness([snap(), snap(surface_bodies=1)]) as h:
            sw_surface.surface_extrude({"depth_mm": 10, "mid_plane": True})
        self.assertEqual(h.fm.last("FeatureExtruRefSurface3")[4], 6)
        with Harness([snap(), snap(surface_bodies=1)]) as h:
            sw_surface.surface_extrude({"depth_mm": 10, "depth2_mm": 4, "cap_ends": True})
        a = h.fm.last("FeatureExtruRefSurface3")
        self.assertEqual((a[0], a[7], a[18], a[19]), (False, 0.004, True, True))

    def test_void_return_without_new_body_fails(self) -> None:
        with Harness([snap(), snap()]) as h:
            out = sw_surface.surface_extrude({"depth_mm": 10})
        self.assertFalse(out["ok"])
        self.assertIn("NOT VERIFIED", out["message"])
        self.assertFalse(out["data"]["verified"])

    def test_no_feature_is_failure(self) -> None:
        with Harness([snap(), snap()], new_feature=None):
            out = sw_surface.surface_extrude({"depth_mm": 10})
        self.assertFalse(out["ok"])

    def test_bad_input_never_touches_com(self) -> None:
        for bad in ({"depth_mm": 0}, {"depth_mm": "ten"}, {"depth_mm": 5, "depth2_mm": -1},
                    {"depth_mm": 5, "mid_plane": True, "depth2_mm": 2}, {}):
            with Harness([]) as h:
                out = sw_surface.surface_extrude(bad)
            self.assertFalse(out["ok"], bad)
            self.assertFalse(h.com_touched, bad)


class SurfaceRevolveTests(unittest.TestCase):
    def test_exact_call_4_args(self) -> None:
        with Harness([snap(), snap(surface_bodies=1)]) as h:
            out = sw_surface.surface_revolve({"angle_deg": 180, "axis_selection": {"sketch_segments": [0]}})
        self.assertTrue(out["ok"], out)
        a = h.fm.last("InsertRevolvedRefSurface")
        self.assertEqual(len(a), 4)
        self.assertAlmostEqual(a[0], 3.141592653589793)
        self.assertEqual(a[1:], (False, 0.0, 0))
        self.assertEqual(h.selections, [({"sketch_segments": [0]}, 4, True)])

    def test_two_direction_type(self) -> None:
        with Harness([snap(), snap(surface_bodies=1)]) as h:
            sw_surface.surface_revolve({"angle_deg": 90, "angle2_deg": 45})
        self.assertEqual(h.fm.last("InsertRevolvedRefSurface")[3], 2)

    def test_validation(self) -> None:
        for bad in ({"angle_deg": 0}, {"angle_deg": 361}, {"angle2_deg": 400}):
            with Harness([]) as h:
                self.assertFalse(sw_surface.surface_revolve(bad)["ok"])
            self.assertFalse(h.com_touched)


class SurfaceLoftTests(unittest.TestCase):
    def test_exact_call_6_args_on_model_doc(self) -> None:
        with Harness([snap(), snap(surface_bodies=1)]) as h:
            out = sw_surface.surface_loft({"profile_sketches": ["A", "B", "C"], "closed": True})
        self.assertTrue(out["ok"], out)
        name, a = h.doc.calls[-1]
        self.assertEqual((name, len(a)), ("InsertLoftRefSurface2", 6))
        self.assertEqual(a, (True, False, False, 1.0, 0, 0))
        self.assertEqual([(n, k, m, ap) for n, k, m, ap in h.by_id],
                         [("A", "SKETCH", 1, False), ("B", "SKETCH", 1, True), ("C", "SKETCH", 1, True)])

    def test_validation_and_selection_failure(self) -> None:
        for bad in ({"profile_sketches": ["A"]}, {"profile_sketches": ["A", "A"]}, {}):
            with Harness([]) as h:
                self.assertFalse(sw_surface.surface_loft(bad)["ok"])
            self.assertFalse(h.com_touched)
        with Harness([], select_ok=False) as h:
            out = sw_surface.surface_loft({"profile_sketches": ["A", "B"]})
        self.assertFalse(out["ok"])
        self.assertEqual(h.doc.calls, [])


class SurfaceOffsetTests(unittest.TestCase):
    def test_exact_call_2_args(self) -> None:
        with Harness([snap(), snap(surface_bodies=1)]) as h:
            out = sw_surface.surface_offset({"surface_bodies": ["Surface-Extrude1"], "distance_mm": 3, "reverse": True})
        self.assertTrue(out["ok"], out)
        self.assertEqual(h.doc.calls[-1], ("InsertOffsetSurface", (0.003, True)))
        self.assertEqual(h.by_id, [("Surface-Extrude1", "SURFACEBODY", 0, True)])

    def test_surface_face_indices(self) -> None:
        with Harness([snap(), snap(surface_bodies=1)]) as h:
            sw_surface.surface_offset({"surface_faces": [1], "distance_mm": 0})
        self.assertEqual(h.objects, [("faceB", 0)])
        self.assertEqual(h.doc.calls[-1][1], (0.0, False))
        with Harness([]) as h:
            with self.assertRaises(RuntimeError):
                sw_surface.surface_offset({"surface_faces": [9], "distance_mm": 1})
        self.assertEqual(h.doc.calls, [])

    def test_validation_and_no_new_body(self) -> None:
        for bad in ({"distance_mm": 1}, {"surface_bodies": ["S"], "distance_mm": -1}, {"surface_bodies": ["S"]}):
            with Harness([]) as h:
                self.assertFalse(sw_surface.surface_offset(bad)["ok"])
            self.assertFalse(h.com_touched)
        with Harness([snap(surface_bodies=1), snap(surface_bodies=1)]):
            out = sw_surface.surface_offset({"surface_bodies": ["S"], "distance_mm": 1})
        self.assertFalse(out["ok"])


class SurfaceKnitTests(unittest.TestCase):
    def test_exact_call_5_args_and_count_drops(self) -> None:
        with Harness([snap(surface_bodies=3), snap(surface_bodies=1)]) as h:
            out = sw_surface.surface_knit({"surface_bodies": ["a", "b", "c"], "tolerance_mm": 0.5})
        self.assertTrue(out["ok"], out)
        a = h.fm.last("InsertSewRefSurface")
        self.assertEqual((len(a), a[0], a[1], a[2]), (5, False, False, True))
        self.assertAlmostEqual(a[3], 0.0005)

    def test_no_drop_fails(self) -> None:
        with Harness([snap(surface_bodies=3), snap(surface_bodies=3)]):
            out = sw_surface.surface_knit({"surface_bodies": ["a", "b", "c"]})
        self.assertFalse(out["ok"])

    def test_form_solid_requires_a_solid_with_volume(self) -> None:
        with Harness([snap(surface_bodies=6), snap(surface_bodies=0, solid_bodies=1, volume_mm3=1000.0)]) as h:
            out = sw_surface.surface_knit({"surface_bodies": ["a"], "try_form_solid": True})
        self.assertTrue(out["ok"], out)
        self.assertTrue(h.fm.last("InsertSewRefSurface")[1])
        with Harness([snap(surface_bodies=6), snap(surface_bodies=1)]):
            out = sw_surface.surface_knit({"surface_bodies": ["a"], "try_form_solid": True})
        self.assertFalse(out["ok"])
        self.assertIn("gaps", out["message"])

    def test_validation(self) -> None:
        for bad in ({}, {"surface_bodies": ["a"], "tolerance_mm": 0}):
            with Harness([]) as h:
                self.assertFalse(sw_surface.surface_knit(bad)["ok"])
            self.assertFalse(h.com_touched)


class ThickenTests(unittest.TestCase):
    def test_exact_call_7_args_and_volume(self) -> None:
        with Harness([snap(surface_bodies=1, surface_area_mm2=1000.0),
                      snap(surface_bodies=1, solid_bodies=1, volume_mm3=2000.0)]) as h:
            out = sw_surface.thicken({"surface_bodies": ["S"], "thickness_mm": 2, "side": "side2"})
        self.assertTrue(out["ok"], out)
        a = h.fm.last("FeatureBossThicken")
        self.assertEqual(len(a), 7)
        self.assertEqual(a, (0.002, 1, 0, False, False, True, True))
        self.assertEqual(out["data"]["expected_volume_mm3"], 2000.0)
        self.assertEqual(out["data"]["volume_added_mm3"], 2000.0)
        self.assertNotIn("FeatureBossThicken2", h.fm.names())

    def test_both_sides_expects_double_volume(self) -> None:
        with Harness([snap(surface_area_mm2=10.0), snap(solid_bodies=1, volume_mm3=5.0)]):
            out = sw_surface.thicken({"surface_bodies": ["S"], "thickness_mm": 1, "side": "both"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"]["expected_volume_mm3"], 20.0)  # 10 mm2 x 1 mm x 2 sides

    def test_no_volume_growth_or_extra_body_fails(self) -> None:
        with Harness([snap(), snap()]):
            self.assertFalse(sw_surface.thicken({"surface_bodies": ["S"], "thickness_mm": 1})["ok"])
        with Harness([snap(), snap(solid_bodies=2, volume_mm3=9.0)]):
            self.assertFalse(sw_surface.thicken({"surface_bodies": ["S"], "thickness_mm": 1})["ok"])
        with Harness([snap(solid_bodies=1, volume_mm3=5.0), snap(solid_bodies=1, volume_mm3=9.0)]):
            self.assertTrue(sw_surface.thicken({"surface_bodies": ["S"], "thickness_mm": 1, "merge": True})["ok"])

    def test_validation(self) -> None:
        for bad in ({"thickness_mm": 1}, {"surface_bodies": ["S"], "thickness_mm": 0},
                    {"surface_bodies": ["S"], "thickness_mm": 1, "side": "up"}):
            with Harness([]) as h:
                self.assertFalse(sw_surface.thicken(bad)["ok"])
            self.assertFalse(h.com_touched)


class SurfaceTrimTests(unittest.TestCase):
    ARGS = {"tool_surface_bodies": ["T"], "pieces_surface_faces": [0]}

    def test_pre_then_post_exact_args_and_marks(self) -> None:
        fm = FakeFM({"PreTrimSurface": True})
        with Harness([snap(surface_bodies=2, surface_area_mm2=100.0), snap(surface_bodies=2, surface_area_mm2=60.0)], fm) as h:
            out = sw_surface.surface_trim({**self.ARGS, "mutual": True, "keep_selected": False, "sew": True})
        self.assertTrue(out["ok"], out)
        self.assertEqual(fm.names(), ["PreTrimSurface", "PostTrimSurface"])
        self.assertEqual(fm.last("PreTrimSurface"), (True, False, False, True))
        self.assertEqual(fm.last("PostTrimSurface"), (True,))
        self.assertEqual(h.by_id, [("T", "SURFACEBODY", 1, True)])
        self.assertEqual(h.objects, [("faceA", 2)])

    def test_pre_false_stops_before_post(self) -> None:
        fm = FakeFM({"PreTrimSurface": False})
        with Harness([snap()], fm):
            out = sw_surface.surface_trim(self.ARGS)
        self.assertFalse(out["ok"])
        self.assertEqual(fm.names(), ["PreTrimSurface"])

    def test_silent_noop_is_failure(self) -> None:
        fm = FakeFM({"PreTrimSurface": True})
        with Harness([snap(surface_area_mm2=100.0), snap(surface_area_mm2=100.0)], fm):
            out = sw_surface.surface_trim(self.ARGS)
        self.assertFalse(out["ok"])
        self.assertIn("silent no-op", out["message"])

    def test_validation(self) -> None:
        for bad in ({}, {"tool_surface_bodies": ["T"]}, {"pieces_surface_faces": [0]}):
            with Harness([]) as h:
                self.assertFalse(sw_surface.surface_trim(bad)["ok"])
            self.assertFalse(h.com_touched)


class ReplaceFaceTests(unittest.TestCase):
    ARGS = {"target_selection": {"faces": [2]}, "replacement_surface_bodies": ["R"]}

    def test_zero_arg_call_marks_and_volume_change(self) -> None:
        with Harness([snap(volume_mm3=1000.0), snap(volume_mm3=1100.0)]) as h:
            out = sw_surface.replace_face(self.ARGS)
        self.assertTrue(out["ok"], out)
        self.assertEqual(h.doc.calls[-1], ("InsertFeatureReplaceFace", ()))
        self.assertEqual(h.selections, [({"faces": [2]}, 1, True)])
        self.assertEqual(h.by_id, [("R", "SURFACEBODY", 2, True)])

    def test_no_geometry_change_fails(self) -> None:
        with Harness([snap(volume_mm3=1000.0), snap(volume_mm3=1000.0)]):
            out = sw_surface.replace_face(self.ARGS)
        self.assertFalse(out["ok"])

    def test_bbox_change_counts(self) -> None:
        with Harness([snap(volume_mm3=1.0), snap(volume_mm3=1.0, bbox_mm=[0, 0, 0, 2, 1, 1])]):
            self.assertTrue(sw_surface.replace_face(self.ARGS)["ok"])

    def test_validation(self) -> None:
        for bad in ({}, {"target_selection": {"faces": [0]}}, {"replacement_surface_bodies": ["R"]}):
            with Harness([]) as h:
                self.assertFalse(sw_surface.replace_face(bad)["ok"])
            self.assertFalse(h.com_touched)


if __name__ == "__main__":
    unittest.main()
