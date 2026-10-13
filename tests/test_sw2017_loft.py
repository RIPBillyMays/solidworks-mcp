# Offline tests for the loft start-point fix (finding #16): explicit and auto-aligned pick
# points, the null-result hint and the twist warning.  COM objects are fakes.

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solidworks_mcp import sw_core, sw_feature  # noqa: E402


class Pt:
    def __init__(self, x: float, y: float) -> None:
        self.X, self.Y = x, y


class Seg:
    """A sketch line (type 0) or arc (type 1); coordinates in metres, arcs run counter-clockwise."""

    def __init__(self, kind: int, start, end, center=None, radius=0.0, rotation: int = 1) -> None:
        self.GetType = kind
        self.ConstructionGeometry = False
        self.GetStartPoint2 = Pt(*start)
        self.GetEndPoint2 = Pt(*end)
        if center is not None:
            self.GetCenterPoint2 = Pt(*center)
            self.GetRadius = radius
            self.GetRotationDir = rotation


def rounded_rect(w: float, h: float, r: float, shift: int = 0) -> list[Seg]:
    """Counter-clockwise rounded rectangle centred on the origin (metres); ``shift`` rotates the order."""
    a, b = w / 2, h / 2
    segs = [
        Seg(0, (-a + r, -b), (a - r, -b)),
        Seg(1, (a - r, -b), (a, -b + r), (a - r, -b + r), r),
        Seg(0, (a, -b + r), (a, b - r)),
        Seg(1, (a, b - r), (a - r, b), (a - r, b - r), r),
        Seg(0, (a - r, b), (-a + r, b)),
        Seg(1, (-a + r, b), (-a, b - r), (-a + r, b - r), r),
        Seg(0, (-a, b - r), (-a, -b + r)),
        Seg(1, (-a, -b + r), (-a + r, -b), (-a + r, -b + r), r),
    ]
    return segs[shift:] + segs[:shift]


class FakeTransform:
    def __init__(self, z: float, readable: bool = True) -> None:
        self._z = z
        self._readable = readable

    @property
    def Inverse(self) -> "FakeTransform":
        return self

    @property
    def ArrayData(self) -> list[float]:
        if not self._readable:
            raise RuntimeError("unreadable")
        return [1, 0, 0, 0, 1, 0, 0, 0, 1, 0.0, 0.0, self._z, 1, 0, 0, 0]


class FakeSketch:
    def __init__(self, segs: list[Seg], z: float, readable: bool = True) -> None:
        self.GetSketchSegments = segs
        self.ModelToSketchTransform = FakeTransform(z, readable)


class FakeFeature:
    def __init__(self, sketch: FakeSketch) -> None:
        self.GetSpecificFeature2 = sketch


class FakeExtension:
    def __init__(self, accept: bool = True) -> None:
        self.calls: list[tuple] = []
        self.accept = accept

    def SelectByID2(self, name, kind, x, y, z, append, mark, callout, sel_opt) -> bool:
        self.calls.append((name, x, y, z, append, mark))
        return self.accept


class FakeManager:
    def __init__(self, returns: Any = object()) -> None:
        self.returns = returns
        self.called = 0

    def InsertProtrusionBlend2(self, *args: Any) -> Any:
        self.called += 1
        return self.returns

    InsertCutBlend = InsertProtrusionBlend2


def run_loft(
    args: dict[str, Any],
    sketches: dict[str, FakeSketch],
    *,
    manager: FakeManager | None = None,
    ext: FakeExtension | None = None,
    volumes: tuple[float | None, float | None] = (None, 45875.7),
    clears: list[str] | None = None,
) -> tuple[dict[str, Any], FakeExtension, mock.MagicMock]:
    ext = ext or FakeExtension()
    manager = manager or FakeManager()
    vols = iter(volumes)
    fallback = mock.MagicMock(return_value=1)

    def fake_feature_result(doc, feature, action, **data):
        if feature is None:
            return sw_core.result(False, f"SOLIDWORKS did not create the {action}.", **data)
        return sw_core.result(True, f"Created {action} 'Loft1'.", feature="Loft1", **data)

    with (
        mock.patch.object(sw_feature, "require_part", lambda: (None, object())),
        mock.patch.object(sw_feature, "exit_active_sketch", lambda d: None),
        mock.patch.object(sw_feature, "clear_selection", lambda d: clears.append("clear") if clears is not None else None),
        mock.patch.object(sw_feature, "extension", lambda d: ext),
        mock.patch.object(sw_feature, "feature_manager", lambda d: manager),
        mock.patch.object(sw_feature, "rename_feature", lambda f, n: None),
        mock.patch.object(sw_feature, "feature_result", fake_feature_result),
        mock.patch.object(sw_feature, "require_selection", fallback),
        mock.patch.object(sw_feature, "_volume_mm3", lambda d: next(vols)),
        mock.patch.object(sw_feature, "resolve_sketch", lambda d, n: (n, FakeFeature(sketches[n]))),
    ):
        return sw_feature.loft(args), ext, fallback


def two_profiles(shift_b: int = 0) -> dict[str, FakeSketch]:
    return {
        "SA": FakeSketch(rounded_rect(0.240, 0.070, 0.016), 0.0),
        "SB": FakeSketch(rounded_rect(0.2344, 0.070, 0.016, shift_b), 0.0028),
    }


class LoftTests(unittest.TestCase):
    def test_auto_align_picks_matching_corner_regardless_of_segment_order(self) -> None:
        for shift in (0, 3, 5):
            res, ext, fallback = run_loft({"profile_sketches": ["SA", "SB"]}, two_profiles(shift))
            self.assertTrue(res["ok"], res)
            fallback.assert_not_called()
            (_, ax, ay, az, aa, am), (_, bx, by, bz, ba, bm) = ext.calls
            # +X+Y corner, tie between the two tangent points broken toward larger Y: (w/2 - r, h/2).
            self.assertAlmostEqual(ax, 0.104)
            self.assertAlmostEqual(ay, 0.035)
            self.assertAlmostEqual(bx, 0.2344 / 2 - 0.016)
            self.assertAlmostEqual(by, 0.035)
            self.assertAlmostEqual(bz, 0.0028)
            self.assertEqual((aa, ba, am, bm), (False, True, 1, 1))
            self.assertEqual(res["data"]["start_points_mm"], [[104.0, 35.0, 0.0], [101.2, 35.0, 2.8]])

    def test_explicit_start_points_are_passed_through(self) -> None:
        pts = [[120.0, 19.0, 0.0], [117.2, 19.0, 2.8]]
        res, ext, _ = run_loft({"profile_sketches": ["SA", "SB"], "start_points": pts}, two_profiles())
        self.assertTrue(res["ok"], res)
        self.assertEqual([(c[1], c[2], c[3]) for c in ext.calls], [(0.12, 0.019, 0.0), (0.1172, 0.019, 0.0028)])
        self.assertEqual(res["data"]["start_points_mm"], pts)

    def test_bad_start_points_are_refused(self) -> None:
        res, _, _ = run_loft({"profile_sketches": ["SA", "SB"], "start_points": [[0, 0, 0]]}, two_profiles())
        self.assertFalse(res["ok"])
        res, _, _ = run_loft({"profile_sketches": ["SA", "SB"], "start_points": [[0, 0], [0, 0]]}, two_profiles())
        self.assertFalse(res["ok"])

    def test_explicit_point_that_misses_fails_early(self) -> None:
        manager = FakeManager()
        res, _, _ = run_loft(
            {"profile_sketches": ["SA", "SB"], "start_points": [[0, 0, 0], [0, 0, 0]]},
            two_profiles(), manager=manager, ext=FakeExtension(accept=False),
        )
        self.assertFalse(res["ok"])
        self.assertEqual(manager.called, 0)

    def test_unreadable_vertices_fall_back_with_warning(self) -> None:
        sketches = {
            "SA": FakeSketch(rounded_rect(0.240, 0.070, 0.016), 0.0, readable=False),
            "SB": FakeSketch(rounded_rect(0.2344, 0.070, 0.016), 0.0028, readable=False),
        }
        res, ext, fallback = run_loft({"profile_sketches": ["SA", "SB"]}, sketches)
        self.assertTrue(res["ok"], res)
        self.assertEqual(ext.calls, [])
        self.assertEqual(fallback.call_count, 2)
        self.assertTrue(any("default" in w for w in res["data"]["warnings"]))

    def test_null_result_hint(self) -> None:
        sketches = {
            "SA": FakeSketch(rounded_rect(0.240, 0.070, 0.016), 0.0),
            "SB": FakeSketch(rounded_rect(0.2344, 0.070, 0.016)[:4], 0.0028),
        }
        res, _, _ = run_loft(
            {"profile_sketches": ["SA", "SB"], "closed": True}, sketches, manager=FakeManager(returns=None)
        )
        self.assertFalse(res["ok"])
        hint = res["data"]["hint"]
        self.assertIn("start_points", hint)
        self.assertIn("segment counts", hint)
        self.assertIn("'SA': 8", hint)
        self.assertIn("'SB': 4", hint)
        self.assertIn("closed=true", hint)
        self.assertEqual(res["data"]["profile_segment_counts"], [8, 4])
        self.assertIn(hint, res["message"])

    def test_twist_warning_fires_when_volume_is_low(self) -> None:
        res, _, _ = run_loft(
            {"profile_sketches": ["SA", "SB"]}, two_profiles(), volumes=(None, 42942.1)
        )
        self.assertTrue(res["ok"], res)  # never fails on the warning alone
        warnings = res["data"]["warnings"]
        self.assertTrue(any(w.startswith("warning: possible twist") and "start_points" in w for w in warnings))
        self.assertAlmostEqual(res["data"]["expected_volume_mm3"], 45875.9, delta=1.0)

    def test_no_twist_warning_for_correct_volume(self) -> None:
        res, _, _ = run_loft({"profile_sketches": ["SA", "SB"]}, two_profiles(), volumes=(None, 45875.7))
        self.assertTrue(res["ok"], res)
        self.assertNotIn("warnings", res["data"])

    def test_twist_check_skipped_for_three_profiles(self) -> None:
        sketches = two_profiles()
        sketches["SC"] = FakeSketch(rounded_rect(0.2, 0.070, 0.016), 0.0056)
        res, _, _ = run_loft({"profile_sketches": ["SA", "SB", "SC"]}, sketches)
        self.assertTrue(res["ok"], res)
        self.assertIn("skipped", res["data"]["twist_check"])

    def test_cut_uses_the_same_alignment_and_skips_twist_check(self) -> None:
        res, ext, _ = run_loft({"profile_sketches": ["SA", "SB"], "cut": True}, two_profiles())
        self.assertTrue(res["ok"], res)
        self.assertEqual(len(ext.calls), 2)
        self.assertNotIn("twist_check", res["data"])

    def test_loop_area(self) -> None:
        area = sw_feature._loop_area_m2(
            [{"kind": s.GetType and "arc" or "line", "start": (s.GetStartPoint2.X, s.GetStartPoint2.Y),
              "end": (s.GetEndPoint2.X, s.GetEndPoint2.Y),
              **({"center": (s.GetCenterPoint2.X, s.GetCenterPoint2.Y), "r": s.GetRadius} if s.GetType else {})}
             for s in rounded_rect(0.240, 0.070, 0.016)]
        )
        self.assertAlmostEqual(area * 1e6, 240 * 70 - (4 - math.pi) * 16 * 16, places=3)
        circle = [{"kind": "arc", "start": (0.01, 0.0), "end": (0.01, 0.0), "center": (0.0, 0.0), "r": 0.01}]
        self.assertAlmostEqual(sw_feature._loop_area_m2(circle) * 1e6, math.pi * 100, places=6)

    def test_loop_area_independent_of_arc_direction(self) -> None:
        def area(segs: list[Seg]) -> float:
            return sw_feature._loop_area_m2([
                {"kind": "arc" if s.GetType else "line",
                 "start": (s.GetStartPoint2.X, s.GetStartPoint2.Y), "end": (s.GetEndPoint2.X, s.GetEndPoint2.Y),
                 **({"center": (s.GetCenterPoint2.X, s.GetCenterPoint2.Y), "r": s.GetRadius,
                     "rotation": s.GetRotationDir} if s.GetType else {})}
                for s in segs])

        ccw = rounded_rect(0.240, 0.070, 0.016)
        # The same outline traversed clockwise: segments in reverse order, arcs keep their
        # requested start/end swapped relative to travel and report GetRotationDir = -1.
        cw = []
        for s in reversed(ccw):
            if s.GetType == 1:
                cw.append(Seg(1, (s.GetEndPoint2.X, s.GetEndPoint2.Y), (s.GetStartPoint2.X, s.GetStartPoint2.Y),
                              (s.GetCenterPoint2.X, s.GetCenterPoint2.Y), s.GetRadius, rotation=-1))
            else:
                cw.append(Seg(0, (s.GetEndPoint2.X, s.GetEndPoint2.Y), (s.GetStartPoint2.X, s.GetStartPoint2.Y)))
        expected = 240 * 70 - (4 - math.pi) * 16 * 16
        self.assertAlmostEqual(area(ccw) * 1e6, expected, places=3)
        self.assertAlmostEqual(area(cw) * 1e6, expected, places=3)

    def test_profile_info_reads_clockwise_arcs(self) -> None:
        segs = [Seg(s.GetType, (s.GetEndPoint2.X, s.GetEndPoint2.Y), (s.GetStartPoint2.X, s.GetStartPoint2.Y),
                    (s.GetCenterPoint2.X, s.GetCenterPoint2.Y) if s.GetType else None,
                    getattr(s, "GetRadius", 0.0), rotation=-1) for s in rounded_rect(0.240, 0.070, 0.016)]
        with mock.patch.object(sw_feature, "resolve_sketch", lambda d, n: (n, FakeFeature(FakeSketch(segs, 0.0)))):
            info = sw_feature._profile_info(object(), "S")
        self.assertAlmostEqual(info["area_mm2"], 240 * 70 - (4 - math.pi) * 256, places=3)

    def test_explicit_point_must_be_on_a_vertex(self) -> None:
        manager = FakeManager()
        res, ext, _ = run_loft(
            {"profile_sketches": ["SA", "SB"], "start_points": [[104.0, 35.0, 0.0], [0.0, 0.0, 2.8]]},
            two_profiles(), manager=manager,
        )
        self.assertFalse(res["ok"])
        self.assertEqual(manager.called, 0)
        self.assertEqual(res["data"]["profile"], "SB")
        self.assertIn([101.2, 35.0, 2.8], res["data"]["profile_vertices_mm"])
        # Within 0.01 mm passes.
        res, _, _ = run_loft(
            {"profile_sketches": ["SA", "SB"], "start_points": [[104.005, 35.0, 0.0], [101.2, 35.0, 2.8]]},
            two_profiles(),
        )
        self.assertTrue(res["ok"], res)

    def test_hint_omits_segment_cause_when_counts_match(self) -> None:
        res, _, _ = run_loft(
            {"profile_sketches": ["SA", "SB"]}, two_profiles(), manager=FakeManager(returns=None)
        )
        self.assertNotIn("segment counts", res["data"]["hint"])
        self.assertIn("start_points", res["data"]["hint"])

    def test_selection_cleared_after_null_result(self) -> None:
        doc_calls = []
        res, _, _ = run_loft(
            {"profile_sketches": ["SA", "SB"]}, two_profiles(), manager=FakeManager(returns=None), clears=doc_calls
        )
        self.assertFalse(res["ok"])
        self.assertEqual(doc_calls[-1], "clear")
        self.assertGreaterEqual(len(doc_calls), 2)

    def test_schema_has_start_points(self) -> None:
        tool = next(t for t in sw_core.TOOLS if t.name == "loft")
        self.assertIn("start_points", tool.inputSchema["properties"])


if __name__ == "__main__":
    unittest.main()
