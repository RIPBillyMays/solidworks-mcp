"""Offline tests for the sketch-editing field fixes (findings #7 and #11 to #15).

Fakes stand in for SOLIDWORKS: a sketch that holds line/arc segments, a doc
whose SketchFillet2 really trims lines and adds an arc, a relation manager,
and a transform whose ArrayData follows the (row, col) -> 3*col + row layout.
"""

from __future__ import annotations

import math
import sys
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solidworks_mcp import sw_core, sw_select, sw_sketch  # noqa: E402


class Com:
    """Base for fakes: absorbs pywin32's _FlagAsMethod."""

    def _FlagAsMethod(self, *names: str) -> None:
        pass


class Pt:
    def __init__(self, x: float, y: float) -> None:
        self.X, self.Y, self.Z = x, y, 0.0

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Pt) and (self.X, self.Y) == (other.X, other.Y)

    def __hash__(self) -> int:
        return hash((self.X, self.Y))


class Line(Com):
    def __init__(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        self.start, self.end = start, end
        self.ConstructionGeometry = False

    def GetType(self) -> int:
        return 0

    def GetStartPoint2(self) -> Pt:
        return Pt(*self.start)

    def GetEndPoint2(self) -> Pt:
        return Pt(*self.end)

    def GetLength(self) -> float:
        return math.dist(self.start, self.end)

    def GetID(self) -> tuple[int, int]:
        return (id(self) % 1000, 0)


class Arc(Line):
    def __init__(self, center: tuple[float, float], start: tuple[float, float],
                 end: tuple[float, float], radius: float) -> None:
        super().__init__(start, end)
        self.center, self.radius = center, radius

    def GetType(self) -> int:
        return 1

    def GetCenterPoint2(self) -> Pt:
        return Pt(*self.center)

    def GetRadius(self) -> float:
        return self.radius


class Relation(Com):
    def __init__(self, kind: int, entities: list[Any] | None = None) -> None:
        self.kind = kind
        self.entities = entities or []

    def GetRelationType(self) -> int:
        return self.kind

    def GetEntities(self) -> list[Any]:
        return list(self.entities)


class FreshRelation(Relation):
    """A wrapper that never compares equal to another fetch of the same relation."""

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)


class RelationManager(Com):
    def __init__(self, fail_delete: bool = False, add_nothing: bool = False) -> None:
        self.relations: list[Relation] = [Relation(9)]
        self.fail_delete, self.add_nothing = fail_delete, add_nothing
        self.added_entities: list[Any] = []
        self.fresh = False
        self.delete_kinds: list[int] = []

    def GetRelations(self, flt: int) -> list[Relation]:
        if self.fresh:
            # Like 2017: every fetch returns new wrappers, so identity fails.
            return [FreshRelation(r.kind, r.entities) for r in self.relations]
        return list(self.relations)

    def GetRelationsCount(self, flt: int) -> int:
        return len(self.relations)

    def AddRelation(self, entities: Any, kind: int) -> bool:
        self.added_entities = list(entities)
        if not self.add_nothing:
            if kind == 17 and any(r.kind == 17 and r.entities == list(entities) for r in self.relations):
                return True  # 2017 does not duplicate a Fixed relation
            self.relations.append(Relation(kind, list(entities)))
        return True

    def DeleteRelation(self, relation: Relation) -> bool:
        if self.fail_delete:
            raise RuntimeError("cannot delete")
        self.delete_kinds.append(relation.kind)
        for r in self.relations:
            if r.kind == relation.kind and r.entities == relation.entities:
                self.relations.remove(r)
                return True
        raise RuntimeError("no such relation")


class Transform(Com):
    def __init__(self, data: list[float]) -> None:
        self._data = data

    @property
    def Inverse(self) -> "Transform":
        return self

    @property
    def ArrayData(self) -> list[float]:
        return self._data


def axes_transform(x: tuple, y: tuple, n: tuple, origin: tuple = (0, 0, 0)) -> Transform:
    """Sketch-to-model transform whose columns are the sketch axes."""
    return Transform([*x, *y, *n, *origin, 1.0, 0, 0, 0])


class Token(Com):
    """Same COM object, different wrapper: equality by token."""

    def __init__(self, token: int) -> None:
        self.token = token

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Token) and other.token == self.token

    def __hash__(self) -> int:
        return hash(self.token)


class Sketch(Token):
    def __init__(self, token: int, segments: list[Any] | None = None,
                 transform: Transform | None = None) -> None:
        super().__init__(token)
        self.segments = segments if segments is not None else []
        self.points: list[Any] = []
        self.RelationManager = RelationManager()
        self.ModelToSketchTransform = transform or axes_transform((1, 0, 0), (0, 1, 0), (0, 0, 1))

    def GetSketchSegments(self) -> list[Any]:
        return list(self.segments)

    def GetSketchPoints2(self) -> list[Any]:
        return list(self.points)


class Feature(Com):
    def __init__(self, name: str, sketch: Sketch | None) -> None:
        self.Name = name
        self._sketch = sketch
        self._next: Feature | None = None

    def GetTypeName2(self) -> str:
        return "ProfileFeature" if self._sketch is not None else "Extrude"

    def GetSpecificFeature2(self) -> Any:
        # A fresh wrapper each call, like late-bound COM.
        return Sketch(self._sketch.token) if self._sketch is not None else None

    def GetNextFeature(self) -> "Feature | None":
        return self._next


class SketchManager(Com):
    def __init__(self) -> None:
        self.ActiveSketch: Sketch | None = None
        self.inserted = 0

    def InsertSketch(self, flag: bool) -> None:
        self.inserted += 1


class Doc(Com):
    """Part document with a feature list and a fillet-capable sketch."""

    def __init__(self, sketches: list[tuple[str, Sketch]]) -> None:
        self.SketchManager = SketchManager()
        self.selected: list[Any] = []
        self.fillet_calls: list[tuple[float, int]] = []
        self.offset_calls: list[tuple] = []
        self.fillet_noop = False
        self.features = [Feature(n, s) for n, s in sketches]
        for a, b in zip(self.features, self.features[1:]):
            a._next = b
        self.FirstFeature = self.features[0] if self.features else None

    def GetType(self) -> int:
        return 1

    def ClearSelection2(self, flag: bool) -> None:
        self.selected.clear()

    def SketchOffset2(self, distance: float, both: bool, chain: bool) -> bool:
        self.offset_calls.append((distance, both, chain))
        return True

    def SketchFillet2(self, radius: float, keep: int) -> bool:
        self.fillet_calls.append((radius, keep))
        if self.fillet_noop:
            return False
        first, second = self.selected[0], self.selected[1]
        sketch = self.SketchManager.ActiveSketch
        corner = next(p for p in (first.start, first.end) if p in (second.start, second.end))

        def away(line: Line) -> tuple[float, float]:
            far = line.end if line.start == corner else line.start
            length = math.dist(far, corner)
            return ((far[0] - corner[0]) / length, (far[1] - corner[1]) / length)

        u1, u2 = away(first), away(second)
        theta = math.acos(u1[0] * u2[0] + u1[1] * u2[1])
        tangent = radius / math.tan(theta / 2)
        p1 = (corner[0] + u1[0] * tangent, corner[1] + u1[1] * tangent)
        p2 = (corner[0] + u2[0] * tangent, corner[1] + u2[1] * tangent)
        bis = (u1[0] + u2[0], u1[1] + u2[1])
        norm = math.hypot(*bis)
        dist = radius / math.sin(theta / 2)
        centre = (corner[0] + bis[0] / norm * dist, corner[1] + bis[1] / norm * dist)
        for line, new in ((first, p1), (second, p2)):
            if line.start == corner:
                line.start = new
            else:
                line.end = new
        sketch.segments.append(Arc(centre, p1, p2, radius))
        return True


class Harness:
    def __init__(self, doc: Doc) -> None:
        self.doc = doc
        patches = [
            mock.patch.object(sw_sketch, "active_document", lambda: (None, doc)),
            mock.patch.object(sw_sketch, "sketch_manager", lambda d: d.SketchManager),
            mock.patch.object(sw_sketch, "require_part", lambda: (None, doc)),
            mock.patch.object(sw_core, "sketch_manager", lambda d: d.SketchManager),
            mock.patch.object(sw_core, "document_type", lambda d: 1),
            mock.patch.object(sw_sketch, "select_object", self._select),
            mock.patch.object(sw_sketch, "dispatch_array", lambda values: list(values)),
        ]
        self._patches = patches

    def _select(self, doc: Doc, obj: Any, mark: int = 0, append: bool = True) -> bool:
        if not append:
            doc.selected.clear()
        doc.selected.append(obj)
        return True

    def __enter__(self) -> "Harness":
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for patch in self._patches:
            patch.stop()
        sw_core.set_open_sketch_hint("")


def rectangle() -> list[Line]:
    """100 x 50 mm rectangle, metres; corners (0,0) (0.1,0) (0.1,0.05) (0,0.05)."""
    return [
        Line((0, 0), (0.1, 0)), Line((0.1, 0), (0.1, 0.05)),
        Line((0.1, 0.05), (0, 0.05)), Line((0, 0.05), (0, 0)),
    ]


def doc_with_rectangle() -> Doc:
    sketch = Sketch(1, list(rectangle()))
    doc = Doc([("Sketch1", sketch)])
    doc.SketchManager.ActiveSketch = Sketch(1, sketch.segments)
    return doc


# ---------------------------------------------------------------- #7


class OpenSketchLabelTests(unittest.TestCase):
    def make(self, active_token: int) -> Doc:
        sketches = [(f"Sketch{i}", Sketch(i, [Line((0, 0), (i / 1000, 0))])) for i in (1, 2, 3)]
        doc = Doc(sketches)
        doc.SketchManager.ActiveSketch = Sketch(active_token, [Line((0, 0), (active_token / 1000, 0))])
        return doc

    def test_older_sketch_is_named_by_identity_not_recency(self) -> None:
        doc = self.make(1)
        with Harness(doc):
            name, _ = sw_core.open_sketch_name(doc)
        self.assertEqual(name, "Sketch1")

    def test_list_sketch_segments_labels_edited_sketch(self) -> None:
        doc = self.make(2)
        with Harness(doc):
            out = sw_sketch.list_sketch_segments({})
        self.assertEqual(out["data"]["sketch"], "Sketch2")
        self.assertEqual(out["data"]["segments"][0]["length_mm"], 2.0)

    def test_close_sketch_reports_edited_name(self) -> None:
        doc = self.make(1)
        with Harness(doc):
            out = sw_sketch.close_sketch({})
        self.assertEqual(out["data"]["sketch"], "Sketch1")

    def test_edit_sketch_selects_and_reports_requested_name(self) -> None:
        doc = self.make(1)
        with Harness(doc), mock.patch.object(sw_sketch, "select_by_id", return_value=True):
            out = sw_sketch.edit_sketch({"sketch_name": "Sketch1"})
            hint = sw_core.open_sketch_name(doc)[0]
        self.assertEqual(out["data"]["sketch"], "Sketch1")
        self.assertEqual(hint, "Sketch1")

    def test_hint_used_when_identity_unavailable(self) -> None:
        doc = self.make(1)
        doc.SketchManager.ActiveSketch = Sketch(99)  # matches nothing
        with Harness(doc):
            sw_core.set_open_sketch_hint("Sketch2")
            name, _ = sw_core.open_sketch_name(doc)
        self.assertEqual(name, "Sketch2")

    def test_hint_does_not_leak_across_documents(self) -> None:
        doc = self.make(1)
        doc.SketchManager.ActiveSketch = Sketch(99)
        doc.GetTitle = lambda: "PartA"  # type: ignore[attr-defined]
        other = self.make(1)
        other.SketchManager.ActiveSketch = Sketch(99)
        other.GetTitle = lambda: "PartB"  # type: ignore[attr-defined]
        with Harness(doc):
            sw_core.set_open_sketch_hint("Sketch2", doc)
            self.assertEqual(sw_core.open_sketch_name(doc)[0], "Sketch2")
            self.assertEqual(sw_core.open_sketch_name(other)[0], "Sketch3")

    def test_falls_back_to_newest_without_identity_or_hint(self) -> None:
        doc = self.make(1)
        doc.SketchManager.ActiveSketch = Sketch(99)
        with Harness(doc):
            name, _ = sw_core.open_sketch_name(doc)
        self.assertEqual(name, "Sketch3")

    def test_create_sketch_names_new_sketch_and_renames(self) -> None:
        doc = self.make(3)
        doc.SketchManager.ActiveSketch = None

        def open_new(flag: bool) -> None:
            doc.SketchManager.ActiveSketch = Sketch(3)

        doc.SketchManager.InsertSketch = open_new  # type: ignore[method-assign]
        with Harness(doc), \
                mock.patch.object(sw_sketch, "resolve_plane_name", return_value="Front Plane"), \
                mock.patch.object(sw_sketch, "select_by_id", return_value=True):
            out = sw_sketch.create_sketch({"plane": "front", "name": "Base"})
        self.assertEqual(out["data"]["sketch"], "Base")
        self.assertEqual(doc.features[2].Name, "Base")


# ---------------------------------------------------------------- #11


class FilletCornerTests(unittest.TestCase):
    def run_fillet(self, doc: Doc, **args: Any) -> dict[str, Any]:
        with Harness(doc):
            return sw_sketch.sketch_fillet({"radius_mm": 5, **args})

    def test_two_corners_one_at_a_time_with_updated_segments(self) -> None:
        doc = doc_with_rectangle()
        out = self.run_fillet(doc, corners=[{"x": 0, "y": 0}, {"x": 100, "y": 50}])
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(doc.fillet_calls), 2)
        self.assertEqual(out["data"]["filleted_corners_mm"], [[0.0, 0.0], [100.0, 50.0]])
        types = [s["type"] for s in out["data"]["segments"]]
        self.assertEqual(types.count("arc"), 2)
        self.assertEqual(types.count("line"), 4)

    def test_each_fillet_selected_exactly_the_two_corner_segments(self) -> None:
        doc = doc_with_rectangle()
        segs = list(doc.SketchManager.ActiveSketch.segments)
        picks: list[list[Any]] = []
        original = doc.SketchFillet2

        def spy(radius: float, keep: int) -> bool:
            picks.append(list(doc.selected))
            return original(radius, keep)

        doc.SketchFillet2 = spy  # type: ignore[method-assign]
        self.run_fillet(doc, corners=[{"x": 100, "y": 0}])
        self.assertEqual(picks[0], [segs[0], segs[1]])

    def test_later_corner_still_resolves_after_earlier_fillet(self) -> None:
        doc = doc_with_rectangle()
        out = self.run_fillet(doc, corners=[{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 50}, {"x": 0, "y": 50}])
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(doc.SketchManager.ActiveSketch.segments), 8)

    def test_corner_already_filleted_is_rejected(self) -> None:
        doc = doc_with_rectangle()
        first = self.run_fillet(doc, corners=[{"x": 0, "y": 0}])
        self.assertTrue(first["ok"])
        again = self.run_fillet(doc, corners=[{"x": 0, "y": 0}])
        self.assertFalse(again["ok"])
        self.assertIn("already has a fillet", again["message"])
        self.assertEqual(len(doc.fillet_calls), 1)

    def test_partial_progress_reported_when_later_corner_fails(self) -> None:
        doc = doc_with_rectangle()
        out = self.run_fillet(doc, corners=[{"x": 0, "y": 0}, {"x": 55, "y": 55}])
        self.assertFalse(out["ok"])
        self.assertEqual(out["data"]["filleted_corners_mm"], [[0.0, 0.0]])
        self.assertIn("1 earlier corner", out["message"])

    def test_point_with_no_corner_is_rejected_without_filleting(self) -> None:
        doc = doc_with_rectangle()
        out = self.run_fillet(doc, corners=[{"x": 50, "y": 25}])
        self.assertFalse(out["ok"])
        self.assertEqual(doc.fillet_calls, [])

    def test_solidworks_noop_is_reported(self) -> None:
        doc = doc_with_rectangle()
        doc.fillet_noop = True
        out = self.run_fillet(doc, corners=[{"x": 0, "y": 0}])
        self.assertFalse(out["ok"])
        self.assertIn("did not fillet", out["message"])

    def test_tolerance_applies(self) -> None:
        doc = doc_with_rectangle()
        near = self.run_fillet(doc, corners=[{"x": 0.005, "y": 0}])
        self.assertTrue(near["ok"], near)
        doc2 = doc_with_rectangle()
        far = self.run_fillet(doc2, corners=[{"x": 0.5, "y": 0}], tolerance_mm=0.01)
        self.assertFalse(far["ok"])

    def test_corners_and_selection_together_rejected(self) -> None:
        doc = doc_with_rectangle()
        out = self.run_fillet(doc, corners=[{"x": 0, "y": 0}], selection={"sketch_segments": [0, 1]})
        self.assertFalse(out["ok"])

    def test_index_mode_still_works(self) -> None:
        doc = doc_with_rectangle()
        def pick(d: Doc, spec: Any) -> int:
            d.selected[:] = d.SketchManager.ActiveSketch.segments[:2]
            return 2

        with Harness(doc), mock.patch.object(sw_sketch, "require_selection", pick):
            out = sw_sketch.sketch_fillet({"radius_mm": 5, "selection": {"sketch_segments": [0, 1]}})
        self.assertTrue(out["ok"])
        self.assertEqual(doc.fillet_calls, [(0.005, 1)])

    def test_needs_corners_or_selection(self) -> None:
        out = self.run_fillet(doc_with_rectangle())
        self.assertFalse(out["ok"])


# ---------------------------------------------------------------- #12


class OffsetConstructionTests(unittest.TestCase):
    def run_offset(self, doc: Doc, **args: Any) -> dict[str, Any]:
        with Harness(doc), mock.patch.object(sw_sketch, "require_selection", return_value=1):
            return sw_sketch.sketch_offset({"distance_mm": 2, "selection": {"sketch_segments": [0]}, **args})

    def test_chain_sources_become_construction(self) -> None:
        doc = doc_with_rectangle()
        segs = doc.SketchManager.ActiveSketch.segments
        extra = Line((0.5, 0.5), (0.6, 0.5))
        segs.append(extra)
        out = self.run_offset(doc, construct_original=True)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["construction_flagged"], 4)
        self.assertTrue(all(s.ConstructionGeometry for s in segs[:4]))
        self.assertFalse(extra.ConstructionGeometry)

    def test_without_chain_only_selected_segment(self) -> None:
        doc = doc_with_rectangle()
        segs = doc.SketchManager.ActiveSketch.segments
        out = self.run_offset(doc, construct_original=True, chain=False)
        self.assertTrue(out["ok"])
        self.assertEqual([s.ConstructionGeometry for s in segs], [True, False, False, False])

    def test_default_leaves_original_alone(self) -> None:
        doc = doc_with_rectangle()
        out = self.run_offset(doc)
        self.assertTrue(out["ok"])
        self.assertNotIn("construction_flagged", out.get("data", {}))
        self.assertFalse(any(s.ConstructionGeometry for s in doc.SketchManager.ActiveSketch.segments))

    def test_selected_spline_and_ellipse_are_flagged(self) -> None:
        doc = doc_with_rectangle()
        segs = doc.SketchManager.ActiveSketch.segments
        spline, ellipse = Line((0.2, 0), (0.3, 0)), Line((0.4, 0), (0.5, 0))
        spline.GetType = lambda: 3  # type: ignore[method-assign]
        ellipse.GetType = lambda: 2  # type: ignore[method-assign]
        segs += [spline, ellipse]
        out = self.run_offset(doc, construct_original=True, selection={"sketch_segments": [4, 5]})
        self.assertTrue(out["ok"], out)
        self.assertTrue(spline.ConstructionGeometry and ellipse.ConstructionGeometry)
        self.assertFalse(any(s.ConstructionGeometry for s in segs[:4]))

    def test_unselected_curves_are_listed_as_skipped(self) -> None:
        doc = doc_with_rectangle()
        segs = doc.SketchManager.ActiveSketch.segments
        spline = Line((0.2, 0), (0.3, 0))
        spline.GetType = lambda: 3  # type: ignore[method-assign]
        segs.append(spline)
        out = self.run_offset(doc, construct_original=True)
        self.assertEqual(out["data"]["skipped_curve_segments"], [4])
        self.assertFalse(spline.ConstructionGeometry)

    def test_needs_segment_indices(self) -> None:
        doc = doc_with_rectangle()
        with Harness(doc):
            out = sw_sketch.sketch_offset({"distance_mm": 2, "selection": {"edges": [0]}, "construct_original": True})
        self.assertFalse(out["ok"])
        self.assertEqual(doc.offset_calls, [])

    def test_failed_offset_flags_nothing(self) -> None:
        doc = doc_with_rectangle()
        doc.SketchOffset2 = lambda *a: False  # type: ignore[method-assign]
        out = self.run_offset(doc, construct_original=True)
        self.assertFalse(out["ok"])
        self.assertFalse(any(s.ConstructionGeometry for s in doc.SketchManager.ActiveSketch.segments))


# ---------------------------------------------------------------- #13


class DimensionAnchorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = doc_with_rectangle()
        self.manager = self.doc.SketchManager.ActiveSketch.RelationManager
        self.events: list[str] = []
        manager = self.manager
        add, delete = manager.AddRelation, manager.DeleteRelation
        manager.AddRelation = lambda e, k: (self.events.append("fix"), add(e, k))[1]  # type: ignore[method-assign]
        manager.DeleteRelation = lambda r: (self.events.append("unfix"), delete(r))[1]  # type: ignore[method-assign]

    def call(self, **args: Any) -> dict[str, Any]:
        def fake_dimension(app: Any, doc: Any, a: dict[str, Any]) -> dict[str, Any]:
            self.events.append("dimension")
            return sw_core.result(True, "Added a dimension.", sketch_status="under_defined")

        with Harness(self.doc), mock.patch.object(sw_sketch, "_add_dimension", fake_dimension):
            return sw_sketch.add_dimension({"selection": {"sketch_segments": [0]}, "value_mm": 80, **args})

    def test_anchor_start_fixes_start_point_then_removes_relation(self) -> None:
        out = self.call(anchor="start")
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.events, ["fix", "dimension", "unfix"])
        self.assertTrue(out["data"]["anchor_relation_removed"])
        self.assertEqual(len(self.manager.relations), 1)  # only the pre-existing one
        point = self.manager.added_entities[0]
        self.assertEqual((point.X, point.Y), (0.0, 0.0))

    def test_anchor_end_uses_end_point(self) -> None:
        self.call(anchor="end")
        point = self.manager.added_entities[0]
        self.assertEqual((point.X, point.Y), (0.1, 0.0))

    def test_relation_removed_even_if_dimension_raises(self) -> None:
        with Harness(self.doc), mock.patch.object(sw_sketch, "_add_dimension", side_effect=ValueError("boom")):
            with self.assertRaises(ValueError):
                sw_sketch.add_dimension({"selection": {"sketch_segments": [0]}, "anchor": "start"})
        self.assertEqual(len(self.manager.relations), 1)

    def test_failed_removal_is_reported(self) -> None:
        self.manager.fail_delete = True
        out = self.call(anchor="start")
        self.assertFalse(out["data"]["anchor_relation_removed"])
        self.assertIn("could not be removed", out["message"])

    def test_no_relation_added_fails_before_dimension(self) -> None:
        self.manager.add_nothing = True
        out = self.call(anchor="start")
        self.assertFalse(out["ok"])
        self.assertNotIn("dimension", self.events)

    def test_anchor_needs_line_segment_selection(self) -> None:
        self.doc.SketchManager.ActiveSketch.segments[0] = Arc((0, 0), (0.1, 0), (0, 0.1), 0.1)
        out = self.call(anchor="start")
        self.assertFalse(out["ok"])
        self.assertEqual(self.events, [])

    def call_with_dimension_relation(self, **args: Any) -> dict[str, Any]:
        """Like 2017: the dimension adds its own type-1 relation between fix and unfix."""
        def fake_dimension(app: Any, doc: Any, a: dict[str, Any]) -> dict[str, Any]:
            self.manager.relations.append(Relation(1))
            return sw_core.result(True, "Added a dimension.", sketch_status="under_defined")

        with Harness(self.doc), mock.patch.object(sw_sketch, "_add_dimension", fake_dimension):
            return sw_sketch.add_dimension({"selection": {"sketch_segments": [0]}, "value_mm": 80, **args})

    def test_fresh_wrappers_and_dimension_relation_still_remove_temp_fixed(self) -> None:
        self.manager.fresh = True
        out = self.call_with_dimension_relation(anchor="start")
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["data"]["anchor_relation_removed"], out)
        self.assertNotIn("Warning", out["message"])
        self.assertEqual([r.kind for r in self.manager.relations], [9, 1])

    def test_fresh_wrappers_with_user_fixed_elsewhere_match_by_coordinates(self) -> None:
        self.manager.fresh = True
        other = Pt(0.5, 0.5)
        self.manager.relations.append(Relation(17, [other]))
        out = self.call_with_dimension_relation(anchor="start")
        self.assertTrue(out["data"]["anchor_relation_removed"], out)
        fixed = [r for r in self.manager.relations if r.kind == 17]
        self.assertEqual(len(fixed), 1)
        self.assertIs(fixed[0].entities[0], other)

    def test_ambiguous_match_deletes_nothing_and_warns(self) -> None:
        self.manager.fresh = True
        # Two same-coordinate candidates besides ours: cannot tell which is ours.
        self.manager.relations.append(Relation(17, [Pt(0.0, 0.0)]))
        orig = self.manager.AddRelation
        self.manager.AddRelation = lambda e, k: (orig(e, k), self.manager.relations.append(Relation(17, [Pt(0.0, 0.0)])))[0]  # type: ignore[method-assign]
        out = self.call(anchor="start")
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.manager.delete_kinds, [])
        self.assertFalse(out["data"]["anchor_relation_removed"])
        self.assertTrue(out["data"]["anchor_relation_ambiguous"])
        self.assertIn("may remain", out["message"])
        self.assertIn("start point", out["message"])

    def test_already_fixed_anchor_skips_temp_relation(self) -> None:
        self.manager.fresh = True
        pre = Relation(17, [Pt(0.0, 0.0)])
        self.manager.relations.append(pre)
        out = self.call_with_dimension_relation(anchor="start")
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["data"]["anchor_already_fixed"])
        self.assertTrue(out["data"]["anchor_relation_removed"])
        self.assertEqual(self.manager.delete_kinds, [])
        self.assertIn(pre, self.manager.relations)

    def test_preexisting_fixed_relation_survives_normal_cleanup(self) -> None:
        pre = Relation(17)
        self.manager.relations.append(pre)
        out = self.call(anchor="end")
        self.assertTrue(out["data"]["anchor_relation_removed"])
        self.assertIn(pre, self.manager.relations)
        self.assertEqual(len(self.manager.relations), 2)

    def test_no_anchor_does_not_touch_relations(self) -> None:
        out = self.call()
        self.assertTrue(out["ok"])
        self.assertEqual(self.events, ["dimension"])


# ---------------------------------------------------------------- #14


class UndoInSketchTests(unittest.TestCase):
    def make(self, effect: int) -> Doc:
        """effect: segments removed by an EditUndo2 call."""
        doc = doc_with_rectangle()
        sketch = doc.SketchManager.ActiveSketch

        def undo(n: int) -> None:
            for _ in range(effect):
                sketch.segments.pop()

        doc.EditUndo2 = undo  # type: ignore[attr-defined]
        doc.EditRedo2 = lambda n: None  # type: ignore[attr-defined]
        return doc

    def run_step(self, doc: Doc, tool: Any = None, args: dict[str, Any] | None = None) -> dict[str, Any]:
        tool = tool or sw_select.undo
        with mock.patch.object(sw_select, "active_document", lambda: (None, doc)), \
                mock.patch.object(sw_select, "iter_features", side_effect=AssertionError("feature list must not be used")):
            return tool(args or {})

    def test_undo_inside_sketch_judged_by_segment_count(self) -> None:
        out = self.run_step(self.make(1))
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["data"]["segments_before"], out["data"]["segments_after"]), (4, 3))
        self.assertTrue(out["data"]["in_sketch"])

    def test_undo_inside_sketch_with_no_change_is_refused(self) -> None:
        out = self.run_step(self.make(0))
        self.assertFalse(out["ok"])
        self.assertIn("in the sketch", out["message"])

    def test_undo_that_closes_the_sketch_reports_it(self) -> None:
        doc = self.make(0)
        doc.EditUndo2 = lambda n: setattr(doc.SketchManager, "ActiveSketch", None)  # type: ignore[attr-defined]
        out = self.run_step(doc)
        self.assertTrue(out["ok"])
        self.assertFalse(out["data"]["sketch_open"])

    def test_redo_inside_sketch_uses_counts_too(self) -> None:
        out = self.run_step(self.make(0), sw_select.redo)
        self.assertFalse(out["ok"])
        self.assertTrue(out["data"]["in_sketch"])

    def test_no_open_sketch_uses_feature_list_as_before(self) -> None:
        class PlainDoc(Com):
            SketchManager = SketchManager()

            def EditUndo2(self, n: int) -> None:
                return None

            def ClearSelection2(self, flag: bool) -> None:
                pass

        names = [[{"name": "A"}, {"name": "B"}], [{"name": "A"}]]
        with mock.patch.object(sw_select, "active_document", lambda: (None, PlainDoc())), \
                mock.patch.object(sw_select, "iter_features", side_effect=lambda d: names.pop(0)):
            out = sw_select.undo({})
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"]["features_before"], 2)


# ---------------------------------------------------------------- #15


class SketchAxesTests(unittest.TestCase):
    def open_on(self, x: tuple, y: tuple, n: tuple, origin: tuple = (0, 0, 0)) -> dict[str, Any]:
        sketch = Sketch(1, transform=axes_transform(x, y, n, origin))
        doc = Doc([("Sketch1", sketch)])
        doc.SketchManager.ActiveSketch = Sketch(1)
        doc.SketchManager.ActiveSketch.ModelToSketchTransform = sketch.ModelToSketchTransform
        with Harness(doc), mock.patch.object(sw_sketch, "select_by_id", return_value=True):
            return sw_sketch.edit_sketch({"sketch_name": "Sketch1"})["data"]

    def test_front_plane(self) -> None:
        d = self.open_on((1, 0, 0), (0, 1, 0), (0, 0, 1))
        self.assertEqual((d["sketch_x_axis"], d["sketch_y_axis"], d["normal"]),
                         ([1, 0, 0], [0, 1, 0], [0, 0, 1]))

    def test_top_plane_y_is_minus_z(self) -> None:
        d = self.open_on((1, 0, 0), (0, 0, -1), (0, 1, 0))
        self.assertEqual(d["sketch_y_axis"], [0, 0, -1])
        self.assertEqual(d["normal"], [0, 1, 0])

    def test_right_plane_x_is_minus_z(self) -> None:
        d = self.open_on((0, 0, -1), (0, 1, 0), (1, 0, 0))
        self.assertEqual(d["sketch_x_axis"], [0, 0, -1])
        self.assertEqual(d["sketch_y_axis"], [0, 1, 0])

    def test_origin_reported_in_mm_and_no_negative_zero(self) -> None:
        d = self.open_on((1, 0, 0), (0, 1, 0), (0, 0, 1), (0.01, -0.02, 0.0))
        self.assertEqual(d["origin"], [10.0, -20.0, 0.0])
        self.assertNotIn("-0.0", repr(d["sketch_x_axis"] + d["origin"]))

    def test_create_sketch_reports_axes(self) -> None:
        sketch = Sketch(1, transform=axes_transform((0, 0, -1), (0, 1, 0), (1, 0, 0)))
        doc = Doc([("Sketch1", sketch)])

        def open_new(flag: bool) -> None:
            doc.SketchManager.ActiveSketch = Sketch(1, transform=sketch.ModelToSketchTransform)

        doc.SketchManager.InsertSketch = open_new  # type: ignore[method-assign]
        with Harness(doc), \
                mock.patch.object(sw_sketch, "resolve_plane_name", return_value="Right Plane"), \
                mock.patch.object(sw_sketch, "select_by_id", return_value=True):
            out = sw_sketch.create_sketch({"plane": "right"})
        self.assertEqual(out["data"]["sketch_x_axis"], [0, 0, -1])
        self.assertEqual(out["data"]["normal"], [1, 0, 0])

    def test_unreadable_transform_omits_axes_without_failing(self) -> None:
        sketch = Sketch(1)
        sketch.ModelToSketchTransform = None  # type: ignore[assignment]
        self.assertEqual(sw_sketch._sketch_axes(sketch), {})


# ---------------------------------------------------------------- #14 option A


class DeleteSketchSegmentTests(unittest.TestCase):
    def run_delete(self, doc: Doc | None = None, noop: bool = False, **args: Any) -> tuple[dict[str, Any], Doc]:
        doc = doc or doc_with_rectangle()
        segments = doc.SketchManager.ActiveSketch.segments

        class Ext:
            def DeleteSelection2(_self, opt: int) -> bool:
                if not noop:
                    for obj in list(doc.selected):
                        segments.remove(obj)
                return True

        doc.ClearSelection2 = lambda flag: doc.selected.clear()  # type: ignore[attr-defined]
        with Harness(doc), mock.patch.object(sw_sketch, "extension", lambda d: Ext()):
            return sw_sketch.delete_sketch_segment(args), doc

    def test_delete_by_index_reports_deleted_and_updated_list(self) -> None:
        out, doc = self.run_delete(index=1)
        self.assertTrue(out["ok"], out)
        data = out["data"]
        self.assertEqual((data["segments_before"], data["segments_after"]), (4, 3))
        self.assertEqual(data["deleted"]["type"], "line")
        self.assertEqual(data["deleted"]["start_mm"], [100.0, 0.0, 0.0])
        self.assertEqual(data["deleted"]["end_mm"], [100.0, 50.0, 0.0])
        self.assertEqual(len(data["segments"]), 3)

    def test_delete_by_point_picks_nearest_segment(self) -> None:
        out, doc = self.run_delete(point={"x_mm": 50, "y_mm": 0.2})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["deleted"]["index"], 0)
        self.assertEqual(len(doc.SketchManager.ActiveSketch.segments), 3)

    def test_point_at_shared_corner_is_ambiguous(self) -> None:
        out, doc = self.run_delete(point={"x_mm": 100, "y_mm": 0})
        self.assertFalse(out["ok"])
        self.assertIn("Ambiguous", out["message"])
        self.assertEqual(out["data"]["candidates"], [0, 1])
        self.assertEqual(len(doc.SketchManager.ActiveSketch.segments), 4)

    def test_point_too_far_deletes_nothing(self) -> None:
        out, doc = self.run_delete(point={"x_mm": 50, "y_mm": 20})
        self.assertFalse(out["ok"])
        self.assertEqual(len(doc.SketchManager.ActiveSketch.segments), 4)

    def test_arc_selected_by_point_on_ring(self) -> None:
        doc = doc_with_rectangle()
        doc.SketchManager.ActiveSketch.segments.append(Arc((0, 0), (0.02, 0), (0, 0.02), 0.02))
        out, _ = self.run_delete(doc, point={"x_mm": 20 * math.cos(math.pi / 4), "y_mm": 20 * math.sin(math.pi / 4)})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["deleted"]["type"], "arc")

    def _arc_doc(self, rotation: int) -> Doc:
        # Quarter arc, radius 20 mm, between 0 and 90 degrees. Start/end stay in
        # request order for CW; the CW arc sweeps the other way (end -> start).
        doc = doc_with_rectangle()
        arc = Arc((0, 0), (0.02, 0), (0, 0.02), 0.02)
        arc.GetRotationDir = lambda: rotation  # type: ignore[attr-defined]
        doc.SketchManager.ActiveSketch.segments.append(arc)
        return doc

    @staticmethod
    def _on_circle(deg: float) -> dict[str, float]:
        return {"x_mm": 20 * math.cos(math.radians(deg)), "y_mm": 20 * math.sin(math.radians(deg))}

    def test_ccw_arc_midpoint_matches_and_off_arc_refused(self) -> None:
        out, _ = self.run_delete(self._arc_doc(1), point=self._on_circle(45))
        self.assertTrue(out["ok"], out)
        out, doc = self.run_delete(self._arc_doc(1), point=self._on_circle(225))
        self.assertFalse(out["ok"])
        self.assertEqual(len(doc.SketchManager.ActiveSketch.segments), 5)

    def test_cw_arc_midpoint_matches_and_off_arc_refused(self) -> None:
        # CW arc from 0 deg to 90 deg goes the long way: its midpoint is at 225 deg.
        out, _ = self.run_delete(self._arc_doc(-1), point=self._on_circle(225))
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["deleted"]["type"], "arc")
        out, doc = self.run_delete(self._arc_doc(-1), point=self._on_circle(45))
        self.assertFalse(out["ok"])
        self.assertEqual(len(doc.SketchManager.ActiveSketch.segments), 5)

    def test_bad_arguments_and_range(self) -> None:
        self.assertFalse(self.run_delete()[0]["ok"])
        self.assertFalse(self.run_delete(index=1, point={"x_mm": 0, "y_mm": 0})[0]["ok"])
        self.assertFalse(self.run_delete(index=9)[0]["ok"])

    def test_count_not_falling_is_reported_failure(self) -> None:
        out, _ = self.run_delete(noop=True, index=0)
        self.assertFalse(out["ok"])
        self.assertIn("Expected 3", out["message"])

    def test_requires_open_sketch(self) -> None:
        doc = doc_with_rectangle()
        doc.SketchManager.ActiveSketch = None
        with Harness(doc), self.assertRaises(RuntimeError):
            sw_sketch.delete_sketch_segment({"index": 0})

    def test_tool_is_registered(self) -> None:
        self.assertIn("delete_sketch_segment", [t.name for t in sw_core.TOOLS])


class UndoHintTests(unittest.TestCase):
    def test_description_points_to_delete_sketch_segment(self) -> None:
        text = next(t.description for t in sw_core.TOOLS if t.name == "undo")
        self.assertIn("delete_sketch_segment", text)

    def test_unchanged_in_sketch_undo_result_mentions_it(self) -> None:
        doc = doc_with_rectangle()
        doc.EditUndo2 = lambda n: None  # type: ignore[attr-defined]
        doc.ClearSelection2 = lambda flag: None  # type: ignore[attr-defined]
        with mock.patch.object(sw_select, "active_document", lambda: (None, doc)):
            out = sw_select.undo({})
        self.assertFalse(out["ok"])
        self.assertIn("delete_sketch_segment", out["message"])
        self.assertIn("outside the undo stack", out["message"])


if __name__ == "__main__":
    unittest.main()
