"""Offline tests for exact sketch placement and read-back verification (field finding #1).

A small fake SketchManager stands in for SOLIDWORKS: it records the AddToDB /
DisplayWhenAdded state seen at each Create* call and can shift what it creates,
the way sketch inference does in a crowded sketch.
"""

from __future__ import annotations

import math
import sys
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidworks_mcp import sw_sketch  # noqa: E402


class Pt:
    def __init__(self, x: float, y: float) -> None:
        self.X, self.Y, self.Z = x, y, 0.0


class FakeLine:
    def GetType(self) -> int:
        return 0

    def __init__(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        self._start, self._end = start, end
        self.ConstructionGeometry = False

    def GetStartPoint2(self) -> Pt:
        return Pt(*self._start)

    def GetEndPoint2(self) -> Pt:
        return Pt(*self._end)


class FakeArc(FakeLine):
    def __init__(self, center: tuple[float, float], start: tuple[float, float],
                 end: tuple[float, float], radius: float, rotation: int = 1) -> None:
        super().__init__(start, end)
        self._center, self._radius, self._rotation = center, radius, rotation

    def GetRotationDir(self) -> int:
        return self._rotation

    def GetCenterPoint2(self) -> Pt:
        return Pt(*self._center)

    def GetRadius(self) -> float:
        return self._radius


class FakeCircle(FakeArc):
    def GetType(self) -> int:
        return 1


class FakeSketch:
    def __init__(self) -> None:
        self.segments: list[Any] = []

    def GetSketchSegments(self) -> list[Any]:
        return list(self.segments)


class FakeSketchManager:
    def __init__(self, shift: tuple[float, float] = (0.0, 0.0), shift_index: int | None = None,
                 raise_on_line: bool = False, swap_arc_ends: bool = False,
                 wrong_sweep: bool = False) -> None:
        self.swap_arc_ends, self.wrong_sweep = swap_arc_ends, wrong_sweep
        self.ActiveSketch = FakeSketch()
        self.AddToDB = False
        self.DisplayWhenAdded = True
        self.shift, self.shift_index = shift, shift_index
        self.raise_on_line = raise_on_line
        self.seen: list[tuple[bool, bool]] = []
        self.lines_made = 0

    def _snapshot(self) -> None:
        self.seen.append((self.AddToDB, self.DisplayWhenAdded))

    def CreateLine(self, x1: float, y1: float, z1: float, x2: float, y2: float, z2: float) -> FakeLine:
        self._snapshot()
        if self.raise_on_line:
            raise RuntimeError("boom")
        index = self.lines_made
        self.lines_made += 1
        dx, dy = self.shift if self.shift_index in (None, index) else (0.0, 0.0)
        line = FakeLine((x1 + dx, y1 + dy), (x2, y2))
        self.ActiveSketch.segments.append(line)
        return line

    def CreateArc(self, xc: float, yc: float, zc: float, x1: float, y1: float, z1: float,
                  x2: float, y2: float, z2: float, direction: int) -> FakeArc:
        self._snapshot()
        dx, dy = self.shift
        radius = math.hypot(x1 - xc, y1 - yc)
        end_scale = radius / math.hypot(x2 - xc, y2 - yc)
        end = (xc + (x2 - xc) * end_scale, yc + (y2 - yc) * end_scale)
        start = (x1, y1)
        rotation = direction
        if self.swap_arc_ends:  # SOLIDWORKS stores the same arc travelled the other way
            start, end, rotation = end, start, -direction
        if self.wrong_sweep:
            rotation = -rotation
        arc = FakeArc((xc + dx, yc + dy), start, end, radius, rotation)
        self.ActiveSketch.segments.append(arc)
        return arc


    def CreatePolygon(self, xc: float, yc: float, zc: float, x1: float, y1: float, z1: float,
                      sides: int, inscribed: bool) -> list[Any]:
        """6 edges plus the construction circle, as 2017 returns them."""
        self._snapshot()
        radius = math.hypot(x1 - xc, y1 - yc)
        base = math.atan2(y1 - yc, x1 - xc)
        corners = [(xc + radius * math.cos(base + 2 * math.pi * i / sides),
                    yc + radius * math.sin(base + 2 * math.pi * i / sides)) for i in range(sides)]
        made: list[Any] = [FakeLine(corners[i], corners[(i + 1) % sides]) for i in range(sides)]
        made.append(FakeCircle((xc, yc), (x1, y1), (x1, y1), radius))
        self.ActiveSketch.segments.extend(made)
        return made


class FakeDoc:
    def __init__(self, manager: FakeSketchManager) -> None:
        self.SketchManager = manager
        self.redraws = 0

    def GraphicsRedraw2(self) -> None:
        self.redraws += 1


class Harness:
    def __init__(self, **kwargs: Any) -> None:
        self.manager = FakeSketchManager(**kwargs)
        self.doc = FakeDoc(self.manager)
        self._patches = [
            mock.patch.object(sw_sketch, "active_document", lambda: (None, self.doc)),
            mock.patch.object(sw_sketch, "sketch_manager", lambda doc: doc.SketchManager),
        ]

    def __enter__(self) -> "Harness":
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for patch in self._patches:
            patch.stop()


LINE = {"x1_mm": 0, "y1_mm": 0, "x2_mm": 10, "y2_mm": 0}


class DbModeTests(unittest.TestCase):
    def test_flags_set_during_creation_and_restored(self) -> None:
        with Harness() as h:
            out = sw_sketch.draw_line(dict(LINE))
        self.assertTrue(out["ok"], out)
        self.assertEqual(h.manager.seen, [(True, False)])
        self.assertIs(h.manager.AddToDB, False)
        self.assertIs(h.manager.DisplayWhenAdded, True)
        self.assertEqual(h.doc.redraws, 1)

    def test_previous_non_default_values_are_restored(self) -> None:
        with Harness() as h:
            h.manager.AddToDB, h.manager.DisplayWhenAdded = True, False
            sw_sketch.draw_line(dict(LINE))
        self.assertIs(h.manager.AddToDB, True)
        self.assertIs(h.manager.DisplayWhenAdded, False)

    def test_restored_when_create_raises(self) -> None:
        with Harness(raise_on_line=True) as h:
            with self.assertRaises(RuntimeError):
                sw_sketch.draw_line(dict(LINE))
        self.assertEqual(h.manager.seen, [(True, False)])
        self.assertIs(h.manager.AddToDB, False)
        self.assertIs(h.manager.DisplayWhenAdded, True)

    def test_ok_result_reports_actual_coordinates(self) -> None:
        with Harness():
            out = sw_sketch.draw_line({"x1_mm": 1.5, "y1_mm": 2, "x2_mm": 10, "y2_mm": 3})
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"]["actual"], {"start_mm": [1.5, 2.0], "end_mm": [10.0, 3.0]})
        self.assertEqual(out["data"]["segments_added"], 1)
        self.assertTrue(out["data"]["verified"])


class LineMismatchTests(unittest.TestCase):
    def test_shifted_endpoint_is_reported(self) -> None:
        with Harness(shift=(0.0012, 0.0)) as h:
            out = sw_sketch.draw_line(dict(LINE))
        self.assertFalse(out["ok"])
        self.assertEqual(out["data"]["requested"]["start_mm"], [0.0, 0.0])
        self.assertEqual(out["data"]["actual"]["start_mm"], [1.2, 0.0])
        self.assertIn("requested", out["message"])
        self.assertIs(h.manager.AddToDB, False)

    def test_sub_tolerance_difference_passes(self) -> None:
        with Harness(shift=(5e-7, 0.0)):
            self.assertTrue(sw_sketch.draw_line(dict(LINE))["ok"])


class ArcTests(unittest.TestCase):
    ARC = {
        "center_x_mm": 0.5, "center_y_mm": 0, "start_x_mm": 5.5, "start_y_mm": 0,
        "end_x_mm": 0.5, "end_y_mm": 5,
    }

    def test_exact_arc_passes_with_actual(self) -> None:
        with Harness():
            out = sw_sketch.draw_arc(dict(self.ARC))
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["actual"]["center_mm"], [0.5, 0.0])
        self.assertEqual(out["data"]["actual"]["radius_mm"], 5.0)

    def test_centre_shift_fails(self) -> None:
        with Harness(shift=(-0.0005, 0.0)):
            out = sw_sketch.draw_arc(dict(self.ARC))
        self.assertFalse(out["ok"])
        self.assertEqual(out["data"]["requested"]["center_mm"], [0.5, 0.0])
        self.assertEqual(out["data"]["actual"]["center_mm"], [0.0, 0.0])
        self.assertIn("centre", out["message"])


class ArcDirectionTests(unittest.TestCase):
    BASE = {
        "center_x_mm": 0, "center_y_mm": 0, "start_x_mm": 5, "start_y_mm": 0,
        "end_x_mm": 0, "end_y_mm": 5,
    }

    def test_both_directions_with_swapped_readback_pass(self) -> None:
        for direction in (1, -1):
            for swap in (False, True):
                with self.subTest(direction=direction, swap=swap), Harness(swap_arc_ends=swap):
                    out = sw_sketch.draw_arc({**self.BASE, "direction": direction})
                    self.assertTrue(out["ok"], out)
                    self.assertTrue(out["data"]["verified"])

    def test_wrong_sweep_side_fails(self) -> None:
        for direction in (1, -1):
            with self.subTest(direction=direction), Harness(swap_arc_ends=True, wrong_sweep=True):
                out = sw_sketch.draw_arc({**self.BASE, "direction": direction})
                self.assertFalse(out["ok"])
                self.assertIn("sweep", out["message"])

    def test_unrelated_endpoints_still_fail(self) -> None:
        with Harness(swap_arc_ends=True) as h:
            h.manager.shift = (0.0, 0.0)
            out = sw_sketch.draw_arc({**self.BASE, "direction": -1, "end_y_mm": 5})
            self.assertTrue(out["ok"])
        with Harness(swap_arc_ends=True):
            with mock.patch.object(FakeArc, "GetEndPoint2", lambda self: Pt(0.0001, 0.005)):
                out = sw_sketch.draw_arc({**self.BASE, "direction": -1})
            self.assertFalse(out["ok"])
            self.assertIn("end points", out["message"])


class PolygonTests(unittest.TestCase):
    ARGS = {"center_x_mm": 3, "center_y_mm": 2, "point_x_mm": 8, "point_y_mm": 2, "sides": 6}

    def test_construction_circle_is_not_counted(self) -> None:
        with Harness():
            out = sw_sketch.draw_polygon(dict(self.ARGS))
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["actual"]["sides"], 6)
        self.assertEqual(out["data"]["actual"]["center_mm"], [3.0, 2.0])
        self.assertEqual(out["data"]["actual"]["circumradius_mm"], 5.0)

    def test_circumscribed_passes_a_computed_corner(self) -> None:
        with Harness() as h:
            calls: list[tuple[Any, ...]] = []
            original = h.manager.CreatePolygon

            def spy(*a: Any) -> Any:
                calls.append(a)
                return original(*a)

            h.manager.CreatePolygon = spy  # type: ignore[method-assign]
            out = sw_sketch.draw_polygon({**self.ARGS, "inscribed": False})
        self.assertTrue(out["ok"], out)
        corner_radius = 5 / math.cos(math.pi / 6)
        self.assertAlmostEqual(out["data"]["actual"]["circumradius_mm"], corner_radius, places=5)
        self.assertAlmostEqual(math.hypot(calls[0][3] - 0.003, calls[0][4] - 0.002) * 1000, corner_radius, places=6)
        self.assertIs(calls[0][7], True)

    def test_radius_mismatch_still_fails(self) -> None:
        with Harness() as h:
            original = h.manager.CreatePolygon
            h.manager.CreatePolygon = lambda xc, yc, zc, x, y, z, n, i: original(  # type: ignore[method-assign]
                xc, yc, zc, x + 0.001, y, z, n, i)
            out = sw_sketch.draw_polygon(dict(self.ARGS))
        self.assertFalse(out["ok"])


class RectangleExtraTests(unittest.TestCase):
    def _rect(self, extra: Any) -> dict[str, Any]:
        with Harness() as h:
            def create(x1: float, y1: float, z1: float, x2: float, y2: float, z2: float) -> list[Any]:
                corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
                made: list[Any] = [FakeLine(corners[i], corners[(i + 1) % 4]) for i in range(4)]
                made.append(extra)
                h.manager.ActiveSketch.segments.extend(made)
                return made

            h.manager.CreateCornerRectangle = create  # type: ignore[attr-defined]
            return sw_sketch.draw_rectangle({"x1_mm": 0, "y1_mm": 0, "x2_mm": 10, "y2_mm": 5})

    def test_extra_circle_is_ignored(self) -> None:
        out = self._rect(FakeCircle((50.0, 50.0), (51.0, 50.0), (51.0, 50.0), 1.0))
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["data"]["verified"])
        self.assertEqual(out["data"]["actual"]["max_corner_mm"], [10.0, 5.0])

    def test_unreadable_type_segment_gives_verified_false(self) -> None:
        class Opaque:
            def GetType(self) -> int:
                raise RuntimeError("no type")

        out = self._rect(Opaque())
        self.assertTrue(out["ok"], out)
        self.assertIs(out["data"]["verified"], False)
        self.assertNotIn("actual", out["data"])


class PolylineTests(unittest.TestCase):
    @staticmethod
    def star(points: int = 10) -> list[dict[str, float]]:
        return [
            {"x_mm": (10 if i % 2 == 0 else 4) * math.cos(2 * math.pi * i / points),
             "y_mm": (10 if i % 2 == 0 else 4) * math.sin(2 * math.pi * i / points)}
            for i in range(points)
        ]

    def test_closed_star_creates_ten_verified_segments(self) -> None:
        pts = self.star()
        with Harness() as h:
            out = sw_sketch.draw_polyline({"points": pts, "closed": True})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["segments_added"], 10)
        self.assertEqual(len(out["data"]["segments"]), 10)
        self.assertTrue(out["data"]["verified"])
        self.assertEqual(h.manager.seen, [(True, False)] * 10)
        # last segment closes back to vertex 0 exactly
        self.assertEqual(out["data"]["segments"][9]["end_mm"], sw_sketch.mm_point(
            (pts[0]["x_mm"] / 1000, pts[0]["y_mm"] / 1000)))

    def test_open_polyline_segment_count(self) -> None:
        with Harness():
            out = sw_sketch.draw_polyline({"points": self.star(5)})
        self.assertEqual(out["data"]["segments_added"], 4)

    def test_bad_vertices_listed(self) -> None:
        with Harness(shift=(0.001, 0.0), shift_index=2):
            out = sw_sketch.draw_polyline({"points": self.star(), "closed": True})
        self.assertFalse(out["ok"])
        self.assertEqual([v["vertex"] for v in out["data"]["bad_vertices"]], [2])
        self.assertIn("vertex 2", out["message"])

    def test_rejections_touch_nothing(self) -> None:
        with Harness() as h:
            for args in (
                {"points": [{"x_mm": 0, "y_mm": 0}]},
                {"points": [{"x_mm": 0, "y_mm": 0}, {"x_mm": 1, "y_mm": 0}], "closed": True},
                {"points": [{"x_mm": 0, "y_mm": 0}, {"x_mm": 0, "y_mm": 0}, {"x_mm": 1, "y_mm": 1}]},
                {"points": [{"x_mm": 0, "y_mm": 0}, {"x_mm": 1}]},
            ):
                self.assertFalse(sw_sketch.draw_polyline(args)["ok"], args)
        self.assertEqual(h.manager.seen, [])

    def test_registered_with_schema(self) -> None:
        from solidworks_mcp.sw_core import TOOLS

        entry = next(t for t in TOOLS if t.name == "draw_polyline")
        self.assertEqual(entry.inputSchema["required"], ["points"])
        self.assertIn("exact", entry.description)


if __name__ == "__main__":
    unittest.main()
