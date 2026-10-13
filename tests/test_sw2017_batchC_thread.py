# Fork addition for SOLIDWORKS 2017 support (ADR-0007).
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Offline tests for Batch C2 threads and fillet retry (plan items 2.7-2.9).

swept_thread (sw_thread), hole_wizard(cosmetic_thread=True) and the
fillet_variant full_round route (sw_feature).  COM objects are fakes that
record the exact member and argument count; no SOLIDWORKS is touched.
"""

from __future__ import annotations

import math
import sys
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from solidworks_mcp import sw_core, sw_feature, sw_thread as th
from test_sw2017_batchB_geometry import FakeFM, Harness
from test_sw2017_enums import ev


class ThreadHarness:
    """Patch the live touch points of sw_thread and record the build order."""

    def __init__(self, fm: FakeFM, volumes: tuple[float, float] = (10000.0, 9800.0), bodies: int = 1,
                 helix_ok: bool = True) -> None:
        self.fm = fm
        self.volumes = list(volumes)
        self.bodies = bodies
        self.helix_ok = helix_ok
        self.order: list[str] = []
        self.lines: list[dict[str, Any]] = []
        self.selected: list[tuple[Any, int, bool]] = []
        self.helix_args: dict[str, Any] = {}
        self.sketch_args: dict[str, Any] = {}
        self.patches: list[Any] = []

    def __enter__(self) -> "ThreadHarness":
        def snapshot(doc: Any) -> dict[str, Any]:
            return {"features": 3, "volume_mm3": self.volumes.pop(0) if len(self.volumes) > 1 else self.volumes[0]}

        def create_helix(a: dict[str, Any]) -> dict[str, Any]:
            self.order.append("helix")
            self.helix_args = a
            return sw_core.result(self.helix_ok, "helix", feature="Helix1")

        def create_sketch(a: dict[str, Any]) -> dict[str, Any]:
            self.order.append("sketch")
            self.sketch_args = a
            return sw_core.result(True, "sketch")

        def draw_line(a: dict[str, Any]) -> dict[str, Any]:
            self.lines.append(a)
            return sw_core.result(True, "line")

        def select_object(doc: Any, obj: Any, mark: int = 0, append: bool = True) -> bool:
            self.selected.append((obj, mark, append))
            return True

        common = {
            "require_part": lambda: (None, object()),
            "feature_manager": lambda doc: self.fm,
            "create_helix": create_helix,
            "create_sketch": create_sketch,
            "draw_line": draw_line,
            "close_sketch": lambda a: sw_core.result(True, "closed"),
            "find_feature": lambda doc, name: f"feature:{name}",
            "select_object": select_object,
            "clear_selection": lambda doc: None,
            "exit_active_sketch": lambda doc: None,
            "dialogs_suppressed": lambda: mock.MagicMock(),
            "rename_feature": lambda f, n: None,
            "feature_result": lambda doc, f, action, **d: sw_core.result(f is not None, action, **d),
            "part_snapshot": snapshot,
            "get_bodies": lambda doc: [object()] * self.bodies,
        }
        for name, repl in common.items():
            p = mock.patch.object(th, name, repl)
            p.start()
            self.patches.append(p)
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in self.patches:
            p.stop()


ARGS = {"circle_sketch": "CircleSk", "profile_plane": "front", "start_mm": [0.0, 5.0], "axis": "u",
        "pitch_mm": 1.0, "length_mm": 8.0}


class ThreadMathTests(unittest.TestCase):
    def test_constants(self) -> None:
        self.assertEqual(th.SWEEP_MARK_PROFILE, 1)
        self.assertEqual(th.SWEEP_MARK_PATH, 4)

    def test_profile_is_a_60_degree_triangle_cutting_into_a_bolt(self) -> None:
        # axis along u, radial coordinate is v; start at v=+5 on an external thread: material is below.
        pts = th.thread_profile((0.0, 5.0), "u", 0.6, cut=True, external=True)
        apex, a, b = pts
        self.assertAlmostEqual(apex[1], 5.0 - 0.6)  # apex into the material
        self.assertAlmostEqual(a[1], 5.0)  # LIVE C2: a cut's base sits exactly on the surface (overshoot removed 5 % extra)
        self.assertAlmostEqual(a[0], -b[0])
        half_width = 0.6 * math.tan(math.radians(30))
        self.assertAlmostEqual(abs(a[0]), half_width)
        self.assertAlmostEqual(a[1], b[1])

    def test_internal_cut_goes_outward_and_boss_reverses(self) -> None:
        self.assertGreater(th.thread_profile((4.0, 0.0), "v", 0.5, True, False)[0][0], 4.0)
        self.assertLess(th.thread_profile((4.0, 0.0), "v", 0.5, False, False)[0][0], 4.0)
        self.assertGreater(th.thread_profile((4.0, 0.0), "v", 0.5, False, True)[0][0], 4.0)

    def test_expected_volume_matches_pappus(self) -> None:
        depth = 0.6134
        v = th.expected_thread_volume_mm3(5.0, 1.0, 8.0, depth, True, True)
        area = depth * depth * math.tan(math.radians(30))
        self.assertAlmostEqual(v, area * 2 * math.pi * (5.0 - depth / 3) * 8.0)
        self.assertGreater(th.expected_thread_volume_mm3(5.0, 1.0, 8.0, depth, True, False), v)


class SweptThreadTests(unittest.TestCase):
    def expected(self) -> float:
        return th.expected_thread_volume_mm3(5.0, 1.0, 8.0, 0.6134, True, True)

    def test_cut_build_order_and_exact_call(self) -> None:
        fm = FakeFM()
        with ThreadHarness(fm, volumes=(10000.0, 10000.0 - self.expected())) as h:
            out = th.swept_thread(dict(ARGS))
        self.assertTrue(out["ok"], out)
        self.assertEqual(h.order, ["helix", "sketch"])
        self.assertEqual(h.helix_args["sketch"], "CircleSk")
        self.assertEqual((h.helix_args["height_mm"], h.helix_args["pitch_mm"]), (8.0, 1.0))
        self.assertEqual(h.sketch_args["plane_name"], "front")
        self.assertEqual(len(h.lines), 3)
        a = fm.last("InsertCutSwept5")
        self.assertEqual(len(a), 22)
        self.assertEqual(a[2], th.THREAD_TWIST_CONTROL)
        self.assertEqual([m for _, m, _ in h.selected], [1, 4])
        self.assertEqual(h.selected[0][0], "feature:Thread_Profile")
        self.assertEqual(h.selected[1][0], "feature:Helix1")
        self.assertTrue(out["data"]["within_tolerance"])
        self.assertAlmostEqual(out["data"]["volume_removed_or_added_mm3"], self.expected(), places=2)

    def test_boss_uses_protrusion_swept4_with_20_args(self) -> None:
        fm = FakeFM()
        with ThreadHarness(fm, volumes=(10000.0, 10050.0)):
            out = th.swept_thread(dict(ARGS, mode="boss"))
        self.assertEqual(len(fm.last("InsertProtrusionSwept4")), 20)
        self.assertTrue(out["ok"], out)
        self.assertFalse(out["data"]["within_tolerance"])  # 50 vs ~10: reported, not hidden

    def test_wrong_direction_volume_is_failure(self) -> None:
        with ThreadHarness(FakeFM(), volumes=(10000.0, 10000.0)):
            out = th.swept_thread(dict(ARGS))
        self.assertFalse(out["ok"])
        self.assertIn("silent no-op", out["message"])

    def test_body_count_change_is_failure(self) -> None:
        h = ThreadHarness(FakeFM(), volumes=(10000.0, 9900.0))
        counts = iter([1, 2])
        with h:
            with mock.patch.object(th, "get_bodies", lambda doc: [object()] * next(counts)):
                out = th.swept_thread(dict(ARGS))
        self.assertFalse(out["ok"])
        self.assertIn("body count", out["message"])

    def test_validation_never_reaches_com(self) -> None:
        fm = FakeFM()
        bad_cases = [
            dict(ARGS, pitch_mm=0), dict(ARGS, length_mm=0.5), dict(ARGS, axis="w"), dict(ARGS, mode="melt"),
            dict(ARGS, start_mm=[1.0]), dict(ARGS, axis="v"), dict(ARGS, depth_mm=9),
            {k: v for k, v in ARGS.items() if k != "profile_plane"},
        ]
        with ThreadHarness(fm) as h:
            for bad in bad_cases:
                self.assertFalse(th.swept_thread(bad)["ok"], bad)
        self.assertEqual(h.order, [])
        self.assertEqual(fm.calls, [])

    def test_helix_failure_stops_before_sketch(self) -> None:
        fm = FakeFM()
        with ThreadHarness(fm, helix_ok=False) as h:
            out = th.swept_thread(dict(ARGS))
        self.assertFalse(out["ok"])
        self.assertEqual(h.order, ["helix"])
        self.assertEqual(fm.calls, [])


class HoleCosmeticTests(unittest.TestCase):
    def base(self, **extra: Any) -> dict[str, Any]:
        args = {
            "kind": "tap", "standard": "iso", "size": "M6x1", "diameter_mm": 5.0, "depth_mm": 12,
            "points": [{"x_mm": 1, "y_mm": 2, "z_mm": 3}], "cosmetic_thread": True,
        }
        args.update(extra)
        return args

    def edges(self, radius: float = 2.5, centre: tuple[float, float, float] = (1, 2, 3)) -> list[dict[str, Any]]:
        return [
            {"index": 0, "curve_type": "line"},
            {"index": 1, "curve_type": "circle", "center_mm": [9, 9, 9], "radius_mm": 2.5},
            {"index": 2, "curve_type": "circle", "center_mm": list(centre), "radius_mm": radius},
        ]

    def test_metric_size_parsing(self) -> None:
        self.assertEqual(sw_feature._metric_thread("M6x1"), (6.0, "M6x1.0"))
        self.assertEqual(sw_feature._metric_thread("M8x1.25"), (8.0, "M8x1.25"))
        self.assertEqual(sw_feature._metric_thread("M6x1.0"), (6.0, "M6x1.0"))
        self.assertIsNone(sw_feature._metric_thread("1/4-20"))
        self.assertIsNone(sw_feature._metric_thread("M6"))

    def test_constants(self) -> None:
        self.assertEqual(sw_feature.HOLE_COSMETIC_STANDARD, 2)  # live 2017: 2 = ISO
        self.assertEqual(sw_feature.FM_FILLET, ev("swFeatureNameID_e.swFmFillet"))

    def test_cosmetic_thread_follows_the_hole(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            with mock.patch.object(sw_feature, "enumerate_edges", lambda doc: self.edges()):
                out = sw_feature.hole_wizard(self.base())
        self.assertTrue(out["ok"], out)
        names = [n for n, _ in fm.calls]
        self.assertEqual(names, ["HoleWizard5", "InsertCosmeticThread3"])
        a = fm.last("InsertCosmeticThread3")
        self.assertEqual(len(a), 7)
        self.assertEqual(a[:3], (2, "Machine threads", "M6x1.0"))
        self.assertAlmostEqual(a[3], 0.006)
        self.assertEqual(a[4], sw_feature.COSMETIC_END["blind"])
        self.assertAlmostEqual(a[5], 0.012)
        self.assertEqual(h.selections[-1][0], {"edges": [2]})
        self.assertEqual(len(out["data"]["cosmetic_threads"]), 1)

    def test_value6_flag_still_set_for_tapped_holes(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            with mock.patch.object(sw_feature, "enumerate_edges", lambda doc: self.edges()):
                sw_feature.hole_wizard(self.base())
        self.assertEqual(fm.last("HoleWizard5")[13], 1.0)  # Value6 = args[8 + 5]

    def test_no_cosmetic_by_default(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            sw_feature.hole_wizard(self.base(cosmetic_thread=False))
        self.assertEqual([n for n, _ in fm.calls], ["HoleWizard5"])

    def test_validation_before_com(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            self.assertFalse(sw_feature.hole_wizard(self.base(kind="hole"))["ok"])
            self.assertFalse(sw_feature.hole_wizard(self.base(size="1/4-20", standard="ansi_inch"))["ok"])
        self.assertEqual(fm.calls, [])

    def test_missing_edge_reported_not_silent(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            with mock.patch.object(sw_feature, "enumerate_edges", lambda doc: self.edges(radius=9.0)):
                out = sw_feature.hole_wizard(self.base())
        self.assertFalse(out["ok"])
        self.assertEqual([n for n, _ in fm.calls], ["HoleWizard5"])

    def test_readback_catches_fallback_size(self) -> None:
        class Thread:
            def GetDefinition(self) -> Any:
                return type("D", (), {"Size": "2-4.5", "Diameter": 0.0022})()

        fm = FakeFM({"InsertCosmeticThread3": Thread()})
        with Harness(fm):
            with mock.patch.object(sw_feature, "enumerate_edges", lambda doc: self.edges()):
                out = sw_feature.hole_wizard(self.base())
        self.assertFalse(out["ok"])
        self.assertIn("fell back", str(out["data"]["cosmetic_threads"][0]["reason"]))

    def test_unreadable_definition_is_unverified_not_ok(self) -> None:
        class Thread:
            def GetDefinition(self) -> Any:
                return None

        fm = FakeFM({"InsertCosmeticThread3": Thread()})
        with Harness(fm):
            with mock.patch.object(sw_feature, "enumerate_edges", lambda doc: self.edges()):
                out = sw_feature.hole_wizard(self.base())
        self.assertTrue(out["ok"], out)  # the hole itself succeeded
        self.assertFalse(out["data"]["cosmetic_thread_verified"])
        self.assertFalse(out["data"]["cosmetic_threads"][0]["ok"])
        self.assertIn("warning", out["data"])


class FullRoundFilletTests(unittest.TestCase):
    ARGS = {"type": "full_round", "side_set_1": {"faces": [0]}, "center": {"faces": [1]}, "side_set_2": {"faces": [2]}}

    class Data:
        def __init__(self) -> None:
            self.set_faces: list[tuple[int, Any]] = []

        def SetFaces(self, which: int, faces: Any) -> None:
            self.set_faces.append((which, faces))

    def run_it(self, data: Any, face_counts: tuple[int, int], feature: Any = "feat",
               volumes: tuple[float, float] = (1000.0, 900.0)) -> tuple[dict[str, Any], FakeFM]:
        fm = FakeFM({"CreateDefinition": data, "CreateFeature": feature})
        counts = iter(face_counts)
        vols = iter(volumes)
        faces = lambda doc: [(f"face{i}", None) for i in range(next(counts))]  # noqa: E731
        with Harness(fm):
            with mock.patch.object(sw_feature, "iter_face_objects", faces), \
                    mock.patch.object(sw_feature, "iter_feature_objects", lambda doc: [1, 2]),                     mock.patch.object(sw_feature, "_volume_mm3", lambda doc: next(vols)):
                return sw_feature.fillet_variant(dict(self.ARGS)), fm

    def test_refused_before_com_on_2017(self) -> None:
        # Live C2: CreateDefinition(1) returns Nothing, so full_round is a per-type refusal.
        out, fm = self.run_it(self.Data(), (6, 6))
        self.assertFalse(out["ok"])
        self.assertTrue(out["data"]["fenced"])
        self.assertEqual(fm.calls, [])

    def test_route_failure_is_a_refusal(self) -> None:
        out, fm = self.run_it(object(), (6, 6))  # data object rejects .Type
        self.assertFalse(out["ok"])
        self.assertTrue(out["data"]["fenced"])
        self.assertNotIn("FeatureFillet3", [n for n, _ in fm.calls])

    def test_null_feature_is_failure(self) -> None:
        out, _ = self.run_it(self.Data(), (6, 6), feature=None)
        self.assertFalse(out["ok"])

    def test_bad_index_and_missing_sets_do_not_touch_com(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            with mock.patch.object(sw_feature, "iter_face_objects", lambda doc: [("f", None)] * 2):
                out = sw_feature.fillet_variant(dict(self.ARGS))  # index 2 out of range
                self.assertFalse(out["ok"])
            self.assertFalse(sw_feature.fillet_variant({"type": "full_round", "center": {"faces": [0]}})["ok"])
        self.assertEqual(fm.calls, [])


class RegistrationTests(unittest.TestCase):
    def test_swept_thread_registered(self) -> None:
        self.assertIn("swept_thread", sw_core.HANDLERS)
        self.assertIn("InsertCutSwept5", sw_core._REGISTERED_FLAGS["IFeatureManager"])
        schema = next(t for t in sw_core.TOOLS if t.name == "hole_wizard").inputSchema
        self.assertIn("cosmetic_thread", schema["properties"])


if __name__ == "__main__":
    unittest.main()
