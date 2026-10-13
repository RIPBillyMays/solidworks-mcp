# Offline tests for batch B geometry: reference geometry, Hole Wizard, fillet
# variants, vertex chamfer, multi-body operations, dome/helix/wrap.  COM objects
# are fakes; no SOLIDWORKS is touched.

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

from solidworks_mcp import sw_body, sw_core, sw_feature
from test_sw2017_enums import ev


class FakeFM:
    """Records every call; unknown members are recorded and return a feature."""

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


class FakeDoc:
    def __init__(self, fm: FakeFM) -> None:
        self.fm = fm
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.dome_return: Any = None

    def InsertDome(self, *a: Any) -> Any:
        self.calls.append(("InsertDome", a))
        return self.dome_return

    def InsertHelix(self, *a: Any) -> Any:
        self.calls.append(("InsertHelix", a))
        return None


class Harness:
    """Patch the live touch points of both modules and record selections."""

    def __init__(self, fm: FakeFM, bodies: int = 3, new_feature: Any = "auto", face_hit: bool = True) -> None:
        self.fm = fm
        self.doc = FakeDoc(fm)
        self.bodies = [object() for _ in range(bodies)]
        self.selections: list[tuple[Any, int, bool]] = []
        self.by_id: list[tuple[str, str, int, bool]] = []
        self.points: list[tuple[str, list[float]]] = []
        self.face_hit = face_hit
        self.new_feature = new_feature
        self.patches: list[Any] = []

    def __enter__(self) -> "Harness":
        def require_selection(doc: Any, spec: Any, mark: int = 0, append: bool = False) -> int:
            self.selections.append((spec, mark, append))
            return 1

        def apply_selection(doc: Any, spec: Any, mark: int = 0, append: bool = False) -> int:
            self.selections.append((spec, mark, append))
            return 1

        def feature_result(doc: Any, feature: Any, action: str, **data: Any) -> dict[str, Any]:
            return sw_core.result(feature is not None, action, **data)

        def select_by_id(doc: Any, name: str, kind: str, mark: int = 0, append: bool = False, ext: Any = None) -> bool:
            self.by_id.append((name, kind, mark, append))
            return True

        def select_at_point(doc: Any, kind: str, point: Any, mark: int = 0, append: bool = True) -> bool:
            self.points.append((kind, list(point)))
            return self.face_hit

        created = object() if self.new_feature == "auto" else self.new_feature
        common = {
            "require_part": lambda: (None, self.doc),
            "feature_manager": lambda doc: self.fm,
            "require_selection": require_selection,
            "feature_result": feature_result,
            "rename_feature": lambda f, n: None,
            "dialogs_suppressed": lambda: mock.MagicMock(),
            "exit_active_sketch": lambda doc: None,
            "clear_selection": lambda doc: None,
        }
        for name, repl in common.items():
            for module in (sw_feature, sw_body):
                p = mock.patch.object(module, name, repl)
                p.start()
                self.patches.append(p)
        extra = {
            sw_body: {
                "apply_selection": apply_selection,
                "get_bodies": lambda doc: self.bodies,
                "_feature_names": lambda doc: [],
                "_feature_created_after": lambda doc, before: created,
                "select_by_id": select_by_id,
                "resolve_sketch": lambda doc, name: (name or "Sketch1", object()),
                "select_sketch_for_feature": lambda doc, name: name or "Sketch1",
            },
            sw_feature: {"select_at_point": select_at_point, "feature_property": lambda f, m, d="": "Hole1"},
        }
        for module, table in extra.items():
            for name, repl in table.items():
                p = mock.patch.object(module, name, repl)
                p.start()
                self.patches.append(p)
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in self.patches:
            p.stop()


SEL = {"faces": [0]}


class ConstantTests(unittest.TestCase):
    def test_constants_match_2017_enums(self) -> None:
        f, b = sw_feature, sw_body
        self.assertEqual(f.HOLE_KINDS["counterbore"], ev("swWzdGeneralHoleTypes_e.swWzdCounterBore"))
        self.assertEqual(f.HOLE_KINDS["countersink"], ev("swWzdGeneralHoleTypes_e.swWzdCounterSink"))
        self.assertEqual(f.HOLE_KINDS["hole"], ev("swWzdGeneralHoleTypes_e.swWzdHole"))
        self.assertEqual(f.HOLE_KINDS["pipe_tap"], ev("swWzdGeneralHoleTypes_e.swWzdPipeTap"))
        self.assertEqual(f.HOLE_KINDS["tap"], ev("swWzdGeneralHoleTypes_e.swWzdTap"))
        for key, name in (("ansi_inch", "AnsiInch"), ("ansi_metric", "AnsiMetric"), ("iso", "ISO"),
                          ("din", "DIN"), ("jis", "JIS"), ("bsi", "BSI"), ("gb", "GB")):
            self.assertEqual(f.HOLE_STANDARDS[key], ev(f"swWzdHoleStandards_e.swStandard{name}"), key)
        fast = "swWzdHoleStandardFastenerTypes_e.swStandard"
        expect = {
            "ansi_inch": {"tapped": "AnsiInchTappedHole", "drill": "AnsiInchFractionalDrillSizes",
                          "clearance": "AnsiInchScrewClearances", "tap_drill": "AnsiInchTapDrills",
                          "socket_head": "AnsiInchSocketCapScrew", "flat_head": "AnsiInchFlatHead82"},
            "ansi_metric": {"tapped": "AnsiMetricTappedHole", "drill": "AnsiMetricDrillSizes",
                            "clearance": "AnsiMetricScrewClearances", "tap_drill": "AnsiMetricTapDrills",
                            "socket_head": "AnsiMetricSocketHeadCapScrew", "flat_head": "AnsiMetricFlatHead82"},
            "iso": {"tapped": "ISOTappedHole", "drill": "ISODrillSizes", "clearance": "ISOScrewClearances",
                    "tap_drill": "ISOTapDrills", "socket_head": "ISOSocketHeadCap", "flat_head": "ISOSocketCTSKFlatHead"},
        }
        for std, table in expect.items():
            self.assertEqual(set(f.HOLE_FASTENERS[std]), set(table))
            for key, member in table.items():
                self.assertEqual(f.HOLE_FASTENERS[std][key], ev(fast + member), (std, key))
        for end, name in (("blind", "Blind"), ("through_all", "ThroughAll"), ("through_next", "ThroughNext")):
            self.assertEqual(f.HOLE_END[end], ev(f"swEndConditions_e.swEndCond{name}"))
        self.assertEqual(f.FILLET_TYPE_VARIABLE, ev("swFeatureFilletType_e.swFeatureFilletType_VariableRadius"))
        self.assertEqual(f.FILLET_TYPE_FACE, ev("swFeatureFilletType_e.swFeatureFilletType_Face"))
        self.assertEqual(f.FILLET_TYPE_FULL_ROUND, ev("swFeatureFilletType_e.swFeatureFilletType_FullRound"))
        self.assertEqual(f.FILLET_OPT_VARIABLE_RADIUS, ev("swFeatureFilletOptions_e.swFeatureFilletVarRadiusType"))
        self.assertEqual(f.FILLET_MARK_FACE_SET1, ev("swSimpleFilletWhichFaces_e.swFaceFilletSet1"))
        # live 2017: set 2 needs mark 4 (the enum says 2, which builds nothing)
        self.assertEqual(f.FILLET_MARK_FACE_SET2, 4)
        self.assertEqual(f.FILLET_MARK_ROUND_SET1, ev("swSimpleFilletWhichFaces_e.swFullRoundFilletSet1"))
        self.assertEqual(f.FILLET_MARK_ROUND_CENTER, ev("swSimpleFilletWhichFaces_e.swFullRoundFilletCenterSet"))
        self.assertEqual(f.FILLET_MARK_ROUND_SET2, ev("swSimpleFilletWhichFaces_e.swFullRoundFilletSet2"))
        self.assertEqual(f.CHAMFER_VERTEX, ev("swChamferType_e.swChamferVertex"))
        self.assertEqual(f.COSMETIC_END["blind"], ev("swCosmeticThreadType_e.swApplyCosmeticThread_Blind"))
        self.assertEqual(f.COSMETIC_END["up_to_next"], ev("swCosmeticThreadType_e.swApplyCosmeticThread_UpToNext"))
        self.assertEqual(f.COSMETIC_END["through"], ev("swCosmeticThreadType_e.swApplyCosmeticThread_ThroughFeature"))

        along = {"along_curve": "AlongCurve", "arc_center": "CenterEdge", "face_center": "FaceCenter",
                 "vertex_projection": "FaceVertexProjection", "intersection": "Intersection", "sketch_point": "SketchPoint"}
        for key, name in along.items():
            self.assertEqual(b.REF_POINT_TYPES[key], ev(f"swRefPointType_e.swRefPoint{name}"), key)
        self.assertEqual(b.REF_POINT_ALONG["distance"], ev("swRefPointAlongCurveType_e.swRefPointAlongCurveDistance"))
        self.assertEqual(b.REF_POINT_ALONG["percentage"], ev("swRefPointAlongCurveType_e.swRefPointAlongCurvePercentage"))
        self.assertEqual(b.REF_POINT_ALONG["evenly"], ev("swRefPointAlongCurveType_e.swRefPointAlongCurveEvenlyDistributed"))
        for key, name in (("add", "Add"), ("subtract", "Subtract"), ("common", "Common")):
            self.assertEqual(b.COMBINE_OPS[key], ev(f"swCombineBodiesOperationType_e.swCombineBodiesOperation{name}"))
        for key, name in (("centroid", "Centroid"), ("origin", "Origin"), ("coordinate_system", "CoordinateSystem")):
            self.assertEqual(b.SCALE_ABOUT[key], ev(f"swScaleType_e.swScaleAbout{name}"))
        helix = {"pitch_revolutions": "PitchAndRevolution", "height_revolutions": "HeightAndRevolution",
                 "height_pitch": "HeightAndPitch", "spiral": "Spiral"}
        for key, name in helix.items():
            self.assertEqual(b.HELIX_DEFINED_BY[key], ev(f"swHelixDefinedBy_e.swHelixDefinedBy{name}"))
        self.assertEqual(b.WRAP_TYPES["emboss"], ev("swWrapSketchType_e.swWrapSketchType_Emboss"))
        self.assertEqual(b.WRAP_TYPES["deboss"], ev("swWrapSketchType_e.swWrapSketchType_Engrave"))
        self.assertEqual(b.WRAP_TYPES["scribe"], ev("swWrapSketchType_e.swWrapSketchType_Scribe"))
        self.assertEqual(b.WRAP_METHODS["analytical"], ev("swWrapMethods_e.swWrapMethods_Analytical"))
        self.assertEqual(b.WRAP_METHODS["spline_surface"], ev("swWrapMethods_e.swWrapMethods_SplineSurface"))


class RegistrationTests(unittest.TestCase):
    def test_tools_registered_once(self) -> None:
        names = [t.name for t in sw_core.TOOLS]
        for name in (
            "hole_wizard", "cosmetic_thread", "fillet_variant", "chamfer_vertex",
            "create_reference_point", "create_coordinate_system", "combine_bodies", "split_body",
            "move_copy_body", "scale_part", "mirror_body", "delete_body", "intersect_bodies",
            "create_dome", "create_helix", "wrap_sketch",
        ):
            self.assertEqual(names.count(name), 1, name)
            self.assertIn(name, sw_core.HANDLERS)

    def test_server_imports_sw_body(self) -> None:
        self.assertIn("sw_body", (ROOT / "solidworks_mcp" / "server.py").read_text(encoding="utf-8"))


class HoleWizardTests(unittest.TestCase):
    def base(self, **extra: Any) -> dict[str, Any]:
        args: dict[str, Any] = {
            "kind": "counterbore", "standard": "ansi_metric", "size": "M6", "diameter_mm": 6.6,
            "depth_mm": 12, "cbore_diameter_mm": 11, "cbore_depth_mm": 6.5,
            "points": [{"x_mm": 1, "y_mm": 2, "z_mm": 3}],
        }
        args.update(extra)
        return args

    def test_counterbore_arguments(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            out = sw_feature.hole_wizard(self.base())
        self.assertTrue(out["ok"], out)
        a = fm.last("HoleWizard5")
        self.assertEqual(len(a), 27)
        self.assertEqual(a[:5], (0, 1, ev("swWzdHoleStandardFastenerTypes_e.swStandardAnsiMetricSocketHeadCapScrew"), "M6", 0))
        self.assertAlmostEqual(a[5], 0.0066)
        self.assertAlmostEqual(a[6], 0.012)
        self.assertAlmostEqual(a[8], 0.011)
        self.assertAlmostEqual(a[9], 0.0065)
        self.assertEqual(a[20:], ("", False, True, True, True, True, False))

    def test_countersink_and_tap(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            sw_feature.hole_wizard(self.base(kind="countersink", csink_diameter_mm=13, csink_angle_deg=90))
        a = fm.last("HoleWizard5")
        self.assertEqual(a[0], 1)
        self.assertAlmostEqual(a[8], 0.013)
        self.assertAlmostEqual(a[9], math.pi / 2)
        fm = FakeFM()
        with Harness(fm):
            sw_feature.hole_wizard(self.base(kind="tap", standard="iso", thread_depth_mm=8, end_condition="through_all", depth_mm=None))
        a = fm.last("HoleWizard5")
        self.assertEqual((a[0], a[1], a[2], a[4]), (4, 8, 147, 1))
        self.assertAlmostEqual(a[8], 0.008)

    def test_one_feature_per_point_and_face_selected_at_point(self) -> None:
        fm = FakeFM()
        points = [{"x_mm": 1, "y_mm": 2, "z_mm": 3}, {"x_mm": 10, "y_mm": 2, "z_mm": 3}]
        with Harness(fm) as h:
            out = sw_feature.hole_wizard(self.base(points=points))
        self.assertEqual(len(fm.calls), 2)
        self.assertEqual(len(out["data"]["created"]), 2)
        self.assertEqual(h.points[0], ("FACE", [0.001, 0.002, 0.003]))

    def test_raw_values_override(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            sw_feature.hole_wizard(self.base(raw_values_mm=[1, 2, 3]))
        a = fm.last("HoleWizard5")
        self.assertEqual([round(v, 6) for v in a[8:20]], [0.001, 0.002, 0.003] + [0.0] * 9)

    def test_validation(self) -> None:
        with Harness(FakeFM()):
            self.assertFalse(sw_feature.hole_wizard(self.base(kind="nope"))["ok"])
            self.assertFalse(sw_feature.hole_wizard(self.base(depth_mm=None))["ok"])
            self.assertFalse(sw_feature.hole_wizard(self.base(standard="jis"))["ok"])
            self.assertFalse(sw_feature.hole_wizard(self.base(fastener="bogus"))["ok"])
        fm = FakeFM()
        with Harness(fm):
            self.assertTrue(sw_feature.hole_wizard(self.base(standard="jis", fastener_type_index=7))["ok"])
        self.assertEqual(fm.last("HoleWizard5")[2], 7)

    def test_no_face_at_point(self) -> None:
        fm = FakeFM()
        with Harness(fm, face_hit=False):
            out = sw_feature.hole_wizard(self.base())
        self.assertFalse(out["ok"])
        self.assertEqual(fm.calls, [])

    def test_cosmetic_thread(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            out = sw_feature.cosmetic_thread(
                {"selection": {"edges": [0]}, "standard_type": "Machine threads", "size": "M6x1",
                 "diameter_mm": 6, "end_condition": "through"}
            )
        self.assertTrue(out["ok"])
        self.assertEqual(fm.last("InsertCosmeticThread3"), (0, "Machine threads", "M6x1", 0.006, 2, 0.0, ""))


class FilletTests(unittest.TestCase):
    def test_variable(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            out = sw_feature.fillet_variant({"type": "variable", "selection": {"edges": [0]}, "radius_mm": 2, "end_radius_mm": 5})
        self.assertTrue(out["ok"])
        a = fm.last("FeatureFillet3")
        self.assertEqual(a[0], 1 | 4)
        self.assertEqual(a[4], 1)
        self.assertEqual(list(a[7].value), [0.002, 0.005])
        self.assertEqual(h.selections[0][1], 0)

    def test_face_marks(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            sw_feature.fillet_variant({"type": "face", "radius_mm": 3, "face_set_1": {"faces": [0]}, "face_set_2": {"faces": [1]}})
        a = fm.last("FeatureFillet3")
        self.assertEqual((a[0], a[1], a[4]), (1, 0.003, 2))
        self.assertEqual([(s[1], s[2]) for s in h.selections], [(1, False), (4, True)])

    def test_full_round_refused_on_2017(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            out = sw_feature.fillet_variant({"type": "full_round", "side_set_1": {"faces": [0]},
                                             "center": {"faces": [1]}, "side_set_2": {"faces": [2]}})
        self.assertFalse(out["ok"])
        self.assertTrue(out["data"]["fenced"])
        self.assertFalse([n for n, _ in fm.calls if n == "FeatureFillet3"])

    def test_missing_inputs_do_not_touch_com(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            for args in (
                {"type": "variable", "selection": SEL, "radius_mm": 1},
                {"type": "face", "radius_mm": 1, "face_set_1": SEL},
                {"type": "full_round", "center": SEL},
                {"type": "bogus"},
            ):
                self.assertFalse(sw_feature.fillet_variant(args)["ok"], args)
        self.assertEqual(fm.calls, [])

    def test_chamfer_vertex(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            sw_feature.chamfer_vertex({"selection": {"vertices": [0]}, "distance_mm": 2, "distance3_mm": 4})
        self.assertEqual(fm.last("InsertFeatureChamfer"), (0, 3, 0.002, 0.0, 0.0, 0.002, 0.002, 0.004))


class ReferenceGeometryTests(unittest.TestCase):
    def test_reference_point_percentage(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            out = sw_body.create_reference_point(
                {"method": "along_curve", "selection": {"edges": [0]}, "along": "percentage", "percent": 25}
            )
        self.assertTrue(out["ok"])
        self.assertEqual(fm.last("InsertReferencePoint"), (2, 1, 25.0, 1))

    def test_reference_point_distance_evenly_and_face(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            sw_body.create_reference_point({"method": "along_curve", "selection": SEL, "distance_mm": 10})
            self.assertEqual(fm.last("InsertReferencePoint"), (2, 0, 0.01, 1))
            sw_body.create_reference_point({"method": "along_curve", "selection": SEL, "along": "evenly", "count": 4})
            self.assertEqual(fm.last("InsertReferencePoint"), (2, 2, 0.0, 4))
            sw_body.create_reference_point({"method": "face_center", "selection": SEL})
            self.assertEqual(fm.last("InsertReferencePoint"), (4, 0, 0.0, 1))

    def test_reference_point_validation(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            self.assertFalse(sw_body.create_reference_point({"method": "along_curve", "selection": SEL})["ok"])
            self.assertFalse(sw_body.create_reference_point({"method": "nope", "selection": SEL})["ok"])
        self.assertEqual(fm.calls, [])

    def test_coordinate_system_marks(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            out = sw_body.create_coordinate_system(
                {"origin": {"vertices": [0]}, "x_axis": {"edges": [1]}, "y_axis": {"edges": [2]}, "flip_y": True}
            )
        self.assertTrue(out["ok"])
        self.assertEqual([s[1] for s in h.selections], [1, 2, 4])
        self.assertEqual(fm.last("InsertCoordinateSystem"), (False, True, False))


class MultiBodyTests(unittest.TestCase):
    def test_combine(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            out = sw_body.combine_bodies({"operation": "subtract", "main_body": 0, "tool_bodies": [1, 2]})
        self.assertTrue(out["ok"])
        a = fm.last("InsertCombineFeature")
        self.assertEqual(a[0], 1)
        self.assertIs(a[1], h.bodies[0])
        self.assertEqual(list(a[2].value), [h.bodies[1], h.bodies[2]])

    def test_combine_rejections(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            self.assertFalse(sw_body.combine_bodies({"operation": "add", "main_body": 0, "tool_bodies": [0]})["ok"])
            self.assertFalse(sw_body.combine_bodies({"operation": "weld", "main_body": 0, "tool_bodies": [1]})["ok"])
            with self.assertRaises(RuntimeError):
                sw_body.combine_bodies({"operation": "add", "main_body": 0, "tool_bodies": [9]})
        self.assertEqual(fm.calls, [])

    def test_delete_body_keep(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            sw_body.delete_body({"bodies": [1], "keep": True})
        self.assertEqual(fm.last("InsertDeleteBody2"), (True,))
        self.assertEqual(h.selections[0][0], {"bodies": [1]})

    def test_move_copy_converts_units(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            sw_body.move_copy_body({"bodies": [0], "dx_mm": 10, "rz_deg": 90, "pivot_x_mm": 5, "copy": True, "count": 3})
        a = fm.last("InsertMoveCopyBody2")
        self.assertEqual(len(a), 12)
        self.assertEqual(a[:4], (0.01, 0.0, 0.0, 0.0))
        self.assertEqual(a[4], 0.005)
        self.assertAlmostEqual(a[7], math.pi / 2)
        self.assertEqual(a[10:], (True, 3))

    def test_move_without_copy_zeroes_count(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            sw_body.move_copy_body({"bodies": [0], "dz_mm": 1, "count": 5})
        self.assertEqual(fm.last("InsertMoveCopyBody2")[10:], (False, 0))

    def test_scale(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            sw_body.scale_part({"factor": 2})
            self.assertEqual(fm.last("InsertScale"), (0, True, 2.0, 2.0, 2.0))
            sw_body.scale_part({"x_factor": 1, "y_factor": 2, "z_factor": 3, "about": "origin"})
            self.assertEqual(fm.last("InsertScale"), (1, False, 1.0, 2.0, 3.0))
            self.assertFalse(sw_body.scale_part({"x_factor": 1})["ok"])
            self.assertFalse(sw_body.scale_part({"factor": 2, "about": "moon"})["ok"])
        self.assertEqual(len(fm.calls), 2)

    def test_mirror_body(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            sw_body.mirror_body({"bodies": [0], "plane_selection": {"planes": ["front"]}, "merge": True})
        self.assertEqual(fm.last("InsertMirrorFeature2"), (True, False, True, False, 0))
        self.assertEqual([s[1] for s in h.selections], [2, 256])

    def test_split_two_phase(self) -> None:
        pieces = (object(), object())
        fm = FakeFM({"PreSplitBody2": pieces})
        with Harness(fm):
            out = sw_body.split_body({"tool_selection": {"planes": ["front"]}, "consume_cut": True})
        self.assertTrue(out["ok"])
        a = fm.last("PostSplitBody")
        self.assertEqual(list(a[0].value), list(pieces))
        self.assertEqual(a[1], True)

    def test_split_failures_stop_before_post(self) -> None:
        for pre in (None, False, True):
            fm = FakeFM({"PreSplitBody2": pre})
            with Harness(fm):
                out = sw_body.split_body({"tool_selection": {"planes": ["front"]}})
            self.assertFalse(out["ok"])
            self.assertNotIn("PostSplitBody", [n for n, _ in fm.calls])

    def test_intersect(self) -> None:
        fm = FakeFM({"PreIntersect2": True})
        with Harness(fm):
            out = sw_body.intersect_bodies({"selection": {"bodies": [0, 1]}, "merge": True})
        self.assertTrue(out["ok"])
        self.assertEqual(fm.last("PreIntersect2"), (True, 0))
        self.assertEqual(fm.last("PostIntersect")[1:], (True, True))
        fm = FakeFM({"PreIntersect2": False})
        with Harness(fm):
            self.assertFalse(sw_body.intersect_bodies({"selection": {"bodies": [0, 1]}})["ok"])
        self.assertNotIn("PostIntersect", [n for n, _ in fm.calls])

    def test_void_call_with_no_new_feature_is_failure(self) -> None:
        fm = FakeFM({"InsertDeleteBody2": True})
        with Harness(fm, new_feature=None):
            out = sw_body.delete_body({"bodies": [0]})
        self.assertFalse(out["ok"])


class ShapingTests(unittest.TestCase):
    def test_dome_void_return_resolved_from_tree(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            out = sw_body.create_dome({"selection": SEL, "height_mm": 5, "elliptical": True})
        self.assertTrue(out["ok"])
        self.assertEqual(h.doc.calls[-1], ("InsertDome", (0.005, False, True)))

    def test_helix_arguments(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            out = sw_body.create_helix({"defined_by": "height_pitch", "height_mm": 50, "pitch_mm": 5, "taper_deg": 10})
        self.assertTrue(out["ok"])
        name, a = h.doc.calls[-1]
        self.assertEqual(name, "InsertHelix")
        self.assertEqual(a[:5], (False, True, True, False, 2))
        self.assertEqual(a[5:7], (0.05, 0.005))
        self.assertAlmostEqual(a[8], math.radians(10))

    def test_spiral_and_missing_values(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            sw_body.create_helix({"defined_by": "spiral", "pitch_mm": 3, "revolutions": 5})
            self.assertEqual(h.doc.calls[-1][1][4], 3)
            self.assertFalse(sw_body.create_helix({"defined_by": "height_pitch", "height_mm": 5})["ok"])
            self.assertFalse(sw_body.create_helix({"defined_by": "x"})["ok"])

    def test_wrap_marks_and_args(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            out = sw_body.wrap_sketch(
                {"sketch": "Sketch2", "face_selection": SEL, "wrap_type": "deboss", "thickness_mm": 0.5}
            )
        self.assertTrue(out["ok"])
        self.assertEqual(h.by_id, [("Sketch2", "SKETCH", 4, False)])
        self.assertEqual(h.selections[-1][1:], (1, True))
        self.assertEqual(fm.last("InsertWrapFeature2"), (1, 0.0005, False, 1, 4))
        with Harness(FakeFM()):
            self.assertFalse(sw_body.wrap_sketch({"sketch": "S", "face_selection": SEL, "wrap_type": "x"})["ok"])


if __name__ == "__main__":
    unittest.main()
