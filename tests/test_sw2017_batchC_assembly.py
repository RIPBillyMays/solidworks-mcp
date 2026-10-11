# Offline tests for Batch C1: advanced mates (sw_mates_adv + add_mate), add_mate_reference and the
# assembly pattern / mirror / sub-assembly tools (sw_asm_pattern).  COM objects are fakes that
# record the exact member and argument count; no SOLIDWORKS is touched.

from __future__ import annotations

import math
import sys
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from solidworks_mcp import sw_asm_pattern, sw_assembly, sw_core, sw_mates_adv  # noqa: E402
from test_sw2017_batchA_assembly import (  # noqa: E402
    FakeAssembly, FakeComponent, FakeFeature, FakeMate, _mate_tree, _patched,
)
from test_sw2017_enums import ev  # noqa: E402


# --------------------------------------------------------------------------
# Constants pinned to the 2017 typelib (the enum coverage scan skips dict(...) tables)
# --------------------------------------------------------------------------


class ConstantTests(unittest.TestCase):
    def test_mate_types(self) -> None:
        t = sw_mates_adv.ADV_MATE_TYPES
        self.assertEqual(t["gear"], ev("swMateType_e.swMateGEAR"))
        self.assertEqual(t["rack_pinion"], ev("swMateType_e.swMateRACKPINION"))
        self.assertEqual(t["screw"], ev("swMateType_e.swMateSCREW"))
        self.assertEqual(t["cam"], ev("swMateType_e.swMateCAMFOLLOWER"))
        self.assertEqual(t["hinge"], ev("swMateType_e.swMateHINGE"))
        self.assertEqual(t["path"], ev("swMateType_e.swMatePATH"))
        self.assertEqual(t["limit_distance"], ev("swMateType_e.swMateDISTANCE"))
        self.assertEqual(t["limit_angle"], ev("swMateType_e.swMateANGLE"))
        self.assertEqual(sw_core.MATE_TYPES["slot"], ev("swMateType_e.swMateSLOT"))

    def test_slot_constraint_uses_width_options(self) -> None:
        c = sw_mates_adv.LIVE_PROBE_SLOT_CONSTRAINT
        self.assertEqual(c["center"], ev("swMateWidthOptions_e.swMateWidth_Centered"))
        self.assertEqual(c["free"], ev("swMateWidthOptions_e.swMateWidth_Free"))
        self.assertEqual(c["distance"], ev("swMateWidthOptions_e.swMateWidth_Dimension"))
        self.assertEqual(c["percent"], ev("swMateWidthOptions_e.swMateWidth_Percent"))

    def test_mate_reference_enums(self) -> None:
        t, a = sw_mates_adv.MATE_REFERENCE_TYPES, sw_mates_adv.MATE_REFERENCE_ALIGNMENTS
        self.assertEqual(t["default"], ev("swMateReferenceType_e.swMateReferenceType_default"))
        self.assertEqual(t["tangent"], ev("swMateReferenceType_e.swMateReferenceType_Tangent"))
        self.assertEqual(t["coincident"], ev("swMateReferenceType_e.swMateReferenceType_Coincident"))
        self.assertEqual(t["concentric"], ev("swMateReferenceType_e.swMateReferenceType_Concentric"))
        self.assertEqual(t["parallel"], ev("swMateReferenceType_e.swMateReferenceType_Parallel"))
        self.assertEqual(a["any"], ev("swMateReferenceAlignment_e.swMateReferenceAlignment_Any"))
        self.assertEqual(a["aligned"], ev("swMateReferenceAlignment_e.swMateReferenceAlignment_Aligned"))
        self.assertEqual(a["anti_aligned"], ev("swMateReferenceAlignment_e.swMateReferenceAlignment_AntiAligned"))
        self.assertEqual(a["closest"], ev("swMateReferenceAlignment_e.swMateReferenceAlignment_Closest"))

    def test_mirror_enums(self) -> None:
        o, n = sw_asm_pattern.MIRROR_ORIENTATIONS, sw_asm_pattern.MIRROR_NAME_MODIFIERS
        self.assertEqual(o["rotate_y"], ev("swMirrorComponentOrientation_e.swMirrorComponentOrientation_RotatePlaneY"))
        self.assertEqual(o["none"], ev("swMirrorComponentOrientation_e.swMirrorComponentOrientation_None"))
        self.assertEqual(o["rotate_xy"], ev("swMirrorComponentOrientation_e.swMirrorComponentOrientation_RotatePlaneXY"))
        self.assertEqual(o["rotate_x"], ev("swMirrorComponentOrientation_e.swMirrorComponentOrientation_RotatePlaneX"))
        self.assertEqual(n["prefix"], ev("swMirrorComponentNameModifier_e.swMirrorComponentName_Prefix"))
        self.assertEqual(n["suffix"], ev("swMirrorComponentNameModifier_e.swMirrorComponentName_Suffix"))
        self.assertEqual(n["custom"], ev("swMirrorComponentNameModifier_e.swMirrorComponentName_Custom"))


class ListMatesNamesTests(unittest.TestCase):
    def test_advanced_types_named_and_limits_not_aliased(self) -> None:
        feats = [FakeFeature("Gear1", "MateGear", FakeMate(10)), FakeFeature("Dist1", "MateDistanceDim", FakeMate(5)),
                 FakeFeature("Hinge1", "MateHinge", FakeMate(22))]
        doc = FakeAssembly(first_feature=_mate_tree(*feats))
        with _patched(doc):
            out = sw_assembly.list_mates({})
        by = {m["name"]: m["mate_type"] for m in out["data"]["mates"]}
        self.assertEqual(by, {"Gear1": "gear", "Dist1": "distance", "Hinge1": "hinge"})


class RegistrationTests(unittest.TestCase):
    def test_tools_registered(self) -> None:
        names = {t.name for t in sw_core.TOOLS}
        self.assertTrue({
            "add_mate_reference", "linear_component_pattern", "circular_component_pattern",
            "pattern_driven_component_pattern", "mirror_components", "create_subassembly",
        } <= names)

    def test_add_mate_enum_includes_advanced_types(self) -> None:
        schema = next(t for t in sw_core.TOOLS if t.name == "add_mate").inputSchema
        enum = set(schema["properties"]["mate_type"]["enum"])
        self.assertTrue({"gear", "rack_pinion", "screw", "cam", "hinge", "path", "limit_distance", "limit_angle",
                         "slot", "symmetric", "width", "distance", "angle"} <= enum)
        self.assertEqual(schema["required"], ["mate_type"])

    def test_late_bound_members_flagged(self) -> None:
        flags = sw_core._REGISTERED_FLAGS
        self.assertIn("AddMate5", flags["IAssemblyDoc"])
        self.assertTrue({"MirrorComponents3", "MakeAssemblyFromSelectedComponents", "InsertNewVirtualAssembly"}
                        <= set(flags["IAssemblyDoc"]))
        self.assertTrue({"InsertMateReference2", "FeatureLinearPattern5", "FeatureCircularPattern5",
                         "InsertDerivedPattern2"} <= set(flags["IFeatureManager"]))


# --------------------------------------------------------------------------
# add_mate (items 1.1-1.9)
# --------------------------------------------------------------------------


class AddMateAdvancedTests(unittest.TestCase):
    def _run(self, args: dict[str, Any], built_type: int | None = None, selected: int = 2, grow: bool = True):
        mate = FakeMate(built_type if built_type is not None else -1)
        if built_type is None:
            del mate.Type  # no Type readable: nothing to compare
        doc = FakeAssembly(first_feature=_mate_tree(FakeFeature("Old1", "MateCoincident", FakeMate(0))))
        doc.mate_result = mate
        if grow:
            doc.on_add = lambda: setattr(doc.FirstFeature.GetFirstSubFeature, "GetNextSubFeature",
                                         FakeFeature("New1", "MateGear", mate))
        marks: list[tuple[int, bool]] = []

        def pick(d: Any, spec: dict[str, Any], append: bool) -> str:
            marks.append((int(spec.get("mark", 0)), append))
            return "picked"

        with _patched(doc), mock.patch.dict(sw_mates_adv.UNSUPPORTED_MATE_TYPES, clear=True), \
             mock.patch.object(sw_assembly, "require_selection", return_value=selected), \
             mock.patch.object(sw_assembly, "_select_mate_entity", side_effect=pick):
            out = sw_assembly.add_mate(args)
        return out, doc, marks

    @staticmethod
    def _ents(n: int, **first: Any) -> list[dict[str, Any]]:
        return [{"component": "A-1", "face": i, **(first if i == 0 else {})} for i in range(n)]

    # -- 1.1 limit distance / angle (already present from Batch A; verified here) --
    def test_limit_distance_positions_and_alias(self) -> None:
        out, doc, _ = self._run({"mate_type": "limit_distance", "selection": {"faces": [0, 1]},
                                 "distance_mm": 10, "min_distance_mm": 5, "max_distance_mm": 20}, built_type=5)
        self.assertTrue(out["ok"], out)
        a = doc.add_args
        self.assertEqual(len(a), 15)
        self.assertEqual(a[0], 5)
        self.assertEqual((a[3], a[4], a[5]), (0.010, 0.020, 0.005))  # value, upper, lower
        self.assertEqual(out["data"]["requested_type"], 5)
        self.assertEqual(out["data"]["built_type"], 5)

    def test_limit_distance_needs_both_limits_before_com(self) -> None:
        out, doc, _ = self._run({"mate_type": "limit_distance", "selection": {"faces": [0, 1]}, "min_distance_mm": 5})
        self.assertFalse(out["ok"])
        self.assertIsNone(doc.add_args)

    def test_limit_value_outside_range_rejected(self) -> None:
        out, doc, _ = self._run({"mate_type": "limit_distance", "selection": {"faces": [0, 1]},
                                 "distance_mm": 30, "min_distance_mm": 5, "max_distance_mm": 20})
        self.assertFalse(out["ok"])
        self.assertIsNone(doc.add_args)

    def test_limit_angle_values(self) -> None:
        out, doc, _ = self._run({"mate_type": "limit_angle", "selection": {"faces": [0, 1]},
                                 "angle_deg": 45, "min_angle_deg": 10, "max_angle_deg": 90}, built_type=6)
        self.assertTrue(out["ok"], out)
        a = doc.add_args
        self.assertEqual(a[0], 6)
        self.assertAlmostEqual(a[8], math.radians(45))
        self.assertAlmostEqual(a[9], math.radians(90))   # AngleAbsUpperLimit
        self.assertAlmostEqual(a[10], math.radians(10))  # AngleAbsLowerLimit

    def test_plain_mate_has_no_plan(self) -> None:
        out, doc, _ = self._run({"mate_type": "coincident", "selection": {"faces": [0, 1]}})
        self.assertTrue(out["ok"])
        self.assertNotIn("requested_type", out["data"])
        self.assertEqual(doc.add_args[:3], (0, 2, False))

    # -- 1.2 gear --
    def test_gear_ratio_and_reverse(self) -> None:
        out, doc, _ = self._run({"mate_type": "gear", "selection": {"faces": [0, 1]},
                                 "ratio_num": 3, "ratio_den": 2, "reverse": True}, built_type=10)
        self.assertTrue(out["ok"], out)
        a = doc.add_args
        self.assertEqual(len(a), 15)
        self.assertEqual((a[0], a[2]), (10, True))
        self.assertEqual((a[6], a[7]), (3.0, 2.0))

    def test_gear_bad_ratio_rejected_before_com(self) -> None:
        for bad in ({"ratio_num": 0}, {"ratio_den": -1}, {"ratio_num": "x"}):
            out, doc, _ = self._run({"mate_type": "gear", "selection": {"faces": [0, 1]}, **bad})
            self.assertFalse(out["ok"], bad)
            self.assertIsNone(doc.add_args, bad)

    def test_wrong_built_type_is_a_failure(self) -> None:
        out, _, _ = self._run({"mate_type": "gear", "selection": {"faces": [0, 1]}}, built_type=0)
        self.assertFalse(out["ok"])
        self.assertEqual(out["data"]["built_type"], 0)
        self.assertEqual(out["data"]["requested_type"], 10)

    def test_no_mate_count_growth_is_a_failure(self) -> None:
        out, _, _ = self._run({"mate_type": "gear", "selection": {"faces": [0, 1]}}, built_type=10, grow=False)
        self.assertFalse(out["ok"])
        self.assertIn("did not grow", out["message"])

    def test_unreadable_type_with_growth_is_ok_but_unverified(self) -> None:
        out, _, _ = self._run({"mate_type": "gear", "selection": {"faces": [0, 1]}}, built_type=None)
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["data"]["type_unverified"])

    def test_addmate5_runs_inside_dialogs_suppressed(self) -> None:
        events: list[str] = []

        class Guard:
            def __enter__(self) -> None:
                events.append("enter")

            def __exit__(self, *exc: Any) -> None:
                events.append("exit")

        with mock.patch.object(sw_assembly, "dialogs_suppressed", lambda: Guard()):
            out, doc, _ = self._run({"mate_type": "gear", "selection": {"faces": [0, 1]}}, built_type=10)
        self.assertEqual(events, ["enter", "exit"])

    # -- 1.3 / 1.4 rack-pinion and screw --
    def test_rack_pinion_distance_slot(self) -> None:
        out, doc, _ = self._run({"mate_type": "rack_pinion", "selection": {"faces": [0, 1]},
                                 "distance_per_rev_mm": 62.8}, built_type=13)
        self.assertTrue(out["ok"], out)
        a = doc.add_args
        self.assertEqual(a[0], 13)
        self.assertAlmostEqual(a[3], 0.0628)
        self.assertEqual((a[4], a[5]), (a[3], a[3]))
        self.assertEqual((a[6], a[7]), (1.0, 1.0))
        self.assertTrue(out["data"]["live_probe"])

    def test_rack_pinion_ratio_slot_override(self) -> None:
        out, doc, _ = self._run({"mate_type": "rack_pinion", "selection": {"faces": [0, 1]},
                                 "distance_per_rev_mm": 10, "value_slot": "ratio"}, built_type=13)
        self.assertTrue(out["ok"], out)
        self.assertEqual(doc.add_args[3], 0.0)
        self.assertAlmostEqual(doc.add_args[6], 0.01)

    def test_screw_pitch_and_validation(self) -> None:
        out, doc, _ = self._run({"mate_type": "screw", "selection": {"faces": [0, 1]}, "pitch_mm": 1.5}, built_type=17)
        self.assertTrue(out["ok"], out)
        self.assertEqual(doc.add_args[0], 17)
        self.assertAlmostEqual(doc.add_args[3], 0.0015)
        for bad in ({}, {"pitch_mm": 0}, {"pitch_mm": -2}):
            o, d, _ = self._run({"mate_type": "screw", "selection": {"faces": [0, 1]}, **bad})
            self.assertFalse(o["ok"])
            self.assertIsNone(d.add_args)
        o, d, _ = self._run({"mate_type": "screw", "selection": {"faces": [0, 1]}, "pitch_mm": 1, "value_slot": "angle"})
        self.assertFalse(o["ok"])

    # -- 1.5 cam, 1.6 hinge, 1.8 path: marks --
    def test_rack_pinion_mate_refused_before_any_com_call(self) -> None:
        doc = FakeAssembly(first_feature=_mate_tree(FakeFeature("Old1", "MateCoincident", FakeMate(0))))
        with _patched(doc), mock.patch.object(sw_assembly, "require_selection") as sel:
            out = sw_assembly.add_mate({"mate_type": "rack_pinion", "distance_per_rev_mm": 94.2, "entities": self._ents(2)})
        self.assertFalse(out["ok"])
        self.assertTrue(out["data"]["fenced"])
        self.assertTrue(out["message"].startswith("Not supported on SOLIDWORKS 2017:"))
        sel.assert_not_called()
        self.assertFalse(doc.add_args)

    def test_hinge_mate_refused_before_any_com_call(self) -> None:
        doc = FakeAssembly(first_feature=_mate_tree(FakeFeature("Old1", "MateCoincident", FakeMate(0))))
        with _patched(doc), mock.patch.object(sw_assembly, "require_selection") as sel:
            out = sw_assembly.add_mate({"mate_type": "hinge", "entities": self._ents(4)})
        self.assertFalse(out["ok"])
        self.assertTrue(out["data"]["fenced"])
        self.assertTrue(out["message"].startswith("Not supported on SOLIDWORKS 2017:"))
        sel.assert_not_called()
        self.assertFalse(doc.add_args)

    def test_path_mate_refused_before_any_com_call(self) -> None:
        doc = FakeAssembly(first_feature=_mate_tree(FakeFeature("Old1", "MateCoincident", FakeMate(0))))
        with _patched(doc), mock.patch.object(sw_assembly, "require_selection") as sel:
            out = sw_assembly.add_mate({"mate_type": "path", "entities": self._ents(2)})
        self.assertFalse(out["ok"])
        self.assertTrue(out["data"]["fenced"])
        sel.assert_not_called()
        self.assertFalse(doc.add_args)

    def test_cam_mate_refused_before_any_com_call(self) -> None:
        doc = FakeAssembly(first_feature=_mate_tree(FakeFeature("Old1", "MateCoincident", FakeMate(0))))
        with _patched(doc), mock.patch.object(sw_assembly, "require_selection") as sel,              mock.patch.object(sw_assembly, "_select_mate_entity") as pick:
            out = sw_assembly.add_mate({"mate_type": "cam", "entities": self._ents(2)})
        self.assertFalse(out["ok"])
        self.assertTrue(out["data"]["fenced"])
        self.assertTrue(out["message"].startswith("Not supported on SOLIDWORKS 2017:"))
        sel.assert_not_called(); pick.assert_not_called()
        self.assertFalse(doc.add_args)

    def test_cam_marks_default_and_roles(self) -> None:
        out, doc, marks = self._run({"mate_type": "cam", "entities": self._ents(3)}, built_type=9, selected=0)
        self.assertTrue(out["ok"], out)
        cam, follower = sw_mates_adv.LIVE_PROBE_CAM_MARKS["cam"], sw_mates_adv.LIVE_PROBE_CAM_MARKS["follower"]
        self.assertEqual([m for m, _ in marks], [cam, cam, follower])
        self.assertEqual(doc.add_args[0], 9)
        o, _, marks = self._run({"mate_type": "cam", "entities": [
            {"component": "A-1", "face": 0, "role": "follower"}, {"component": "B-1", "face": 0, "role": "cam"}]},
            built_type=9, selected=0)
        self.assertEqual([m for m, _ in marks], [follower, cam])

    def test_explicit_mark_wins_over_role_mark(self) -> None:
        _, _, marks = self._run({"mate_type": "cam", "entities": [
            {"component": "A-1", "face": 0, "mark": 5}, {"component": "B-1", "face": 0}]}, built_type=9, selected=0)
        self.assertEqual(marks[0][0], 5)

    def test_unknown_role_rejected_before_com(self) -> None:
        out, doc, marks = self._run({"mate_type": "cam", "entities": [
            {"component": "A-1", "face": 0, "role": "concentric"}, {"component": "B-1", "face": 0}]}, selected=0)
        self.assertFalse(out["ok"])
        self.assertEqual(marks, [])
        self.assertIsNone(doc.add_args)

    def test_hinge_four_entities_marks_and_minimum(self) -> None:
        out, doc, marks = self._run({"mate_type": "hinge", "entities": self._ents(4)}, built_type=22, selected=0)
        self.assertTrue(out["ok"], out)
        h = sw_mates_adv.LIVE_PROBE_HINGE_MARKS
        self.assertEqual([m for m, _ in marks], [h["concentric"]] * 2 + [h["coincident"]] * 2)
        self.assertEqual(doc.add_args[0], 22)
        o, d, _ = self._run({"mate_type": "hinge", "entities": self._ents(2)}, selected=0)
        self.assertFalse(o["ok"])
        self.assertIsNone(d.add_args)

    def test_hinge_angle_limits(self) -> None:
        out, doc, _ = self._run({"mate_type": "hinge", "entities": self._ents(4), "min_angle_deg": 0, "max_angle_deg": 120},
                                built_type=22, selected=0)
        self.assertTrue(out["ok"], out)
        self.assertAlmostEqual(doc.add_args[9], math.radians(120))
        o, d, _ = self._run({"mate_type": "hinge", "entities": self._ents(4), "min_angle_deg": 0}, selected=0)
        self.assertFalse(o["ok"])

    def test_path_marks(self) -> None:
        out, doc, marks = self._run({"mate_type": "path", "entities": self._ents(2)}, built_type=15, selected=0)
        self.assertTrue(out["ok"], out)
        p = sw_mates_adv.LIVE_PROBE_PATH_MARKS
        self.assertEqual([m for m, _ in marks], [p["point"], p["path"]])
        self.assertEqual(doc.add_args[0], 15)

    # -- 1.7 slot, 1.9 symmetric / width --
    def test_slot_constraints(self) -> None:
        c = sw_mates_adv.LIVE_PROBE_SLOT_CONSTRAINT
        for constraint, extra, option, dist in (
            ("free", {}, c["free"], 0.0),
            ("center", {}, c["center"], 0.0),
            ("distance", {"distance_mm": 5}, c["distance"], 0.005),
            ("percent", {"slot_percent": 25}, c["percent"], 0.25),
        ):
            out, doc, _ = self._run({"mate_type": "slot", "selection": {"faces": [0, 1]},
                                     "slot_constraint": constraint, **extra}, built_type=21)
            self.assertTrue(out["ok"], (constraint, out))
            a = doc.add_args
            self.assertEqual((a[0], a[13]), (21, option), constraint)
            self.assertAlmostEqual(a[3], dist, msg=constraint)

    def test_slot_validation(self) -> None:
        for bad in ({"slot_constraint": "bogus"}, {"slot_constraint": "distance"}, {"slot_constraint": "percent"},
                    {"slot_constraint": "percent", "slot_percent": 101}):
            out, doc, _ = self._run({"mate_type": "slot", "selection": {"faces": [0, 1]}, **bad})
            self.assertFalse(out["ok"], bad)
            self.assertIsNone(doc.add_args, bad)

    def test_slot_without_constraint_is_plain_mate(self) -> None:
        out, doc, _ = self._run({"mate_type": "slot", "selection": {"faces": [0, 1]}}, built_type=21)
        self.assertTrue(out["ok"])
        self.assertNotIn("requested_type", out["data"])
        self.assertEqual(doc.add_args[0], 21)

    def test_width_percent(self) -> None:
        out, doc, _ = self._run({"mate_type": "width", "width_option": "percent", "width_percent": 30,
                                 "selection": {"faces": [0, 1, 2, 3]}}, built_type=11, selected=4)
        self.assertTrue(out["ok"], out)
        a = doc.add_args
        self.assertEqual((a[0], a[13]), (11, 3))
        self.assertAlmostEqual(a[3], 0.30)
        o, d, _ = self._run({"mate_type": "width", "width_percent": 30, "selection": {"faces": [0, 1, 2, 3]}}, selected=4)
        self.assertFalse(o["ok"])  # needs width_option=percent
        self.assertIsNone(d.add_args)

    def test_width_tab_mark_still_remapped_to_16(self) -> None:
        out, _, marks = self._run({"mate_type": "width", "width_option": "percent", "width_percent": 50, "entities": [
            {"component": "A", "face": 0, "mark": 1}, {"component": "A", "face": 1, "mark": 1},
            {"component": "B", "face": 0, "mark": 2}, {"component": "B", "face": 1, "mark": 2}]}, built_type=11, selected=0)
        self.assertTrue(out["ok"], out)
        self.assertEqual([m for m, _ in marks], [1, 1, 16, 16])

    def test_symmetric_roles(self) -> None:
        out, doc, marks = self._run({"mate_type": "symmetric", "entities": [
            {"component": "A", "plane": "Front Plane", "role": "symmetry_plane"},
            {"component": "A", "face": 0}, {"component": "B", "face": 0}]}, built_type=8, selected=0)
        self.assertTrue(out["ok"], out)
        s = sw_mates_adv.LIVE_PROBE_SYMMETRIC_MARKS
        self.assertEqual([m for m, _ in marks], [s["symmetry_plane"], s["entity"], s["entity"]])
        self.assertEqual(doc.add_args[0], 8)

    def test_symmetric_without_roles_keeps_batchA_path(self) -> None:
        out, doc, marks = self._run({"mate_type": "symmetric", "entities": self._ents(3)}, selected=0)
        self.assertTrue(out["ok"], out)
        self.assertNotIn("requested_type", out["data"])
        self.assertEqual([m for m, _ in marks], [0, 0, 0])

    def test_too_few_selected_entities_blocks_addmate5(self) -> None:
        out, doc, _ = self._run({"mate_type": "gear", "selection": {"faces": [0]}}, selected=1)
        self.assertFalse(out["ok"])
        self.assertIsNone(doc.add_args)

    def test_result_reports_counts(self) -> None:
        doc_args = {"mate_type": "screw", "selection": {"faces": [0, 1]}, "pitch_mm": 2}
        out, doc, _ = self._run(doc_args, built_type=17)
        d = out["data"]
        for key in ("mate_count_before", "mate_count_after", "feature_count_before", "feature_count_after", "live_probe"):
            self.assertIn(key, d)


# --------------------------------------------------------------------------
# add_mate_reference (1.10)
# --------------------------------------------------------------------------


class FakeMRFeature:
    def __init__(self, name: str, type_name: str = "MateReference") -> None:
        self.Name, self.GetTypeName2 = name, type_name
        self.GetNextFeature = None


class FakeMRFM:
    def __init__(self, doc: "FakeMRDoc", create: bool = True) -> None:
        self.doc, self.create, self.calls = doc, create, []

    def InsertMateReference2(self, *args: Any) -> Any:
        self.calls.append(args)
        if not self.create:
            return None
        feature = FakeMRFeature("MateReference1")
        self.doc.features.append(feature)
        return feature


class FakeMRDoc:
    def __init__(self) -> None:
        self.features: list[Any] = [FakeMRFeature("Origin", "OriginProfileFeature")]


class AddMateReferenceTests(unittest.TestCase):
    def _run(self, args: dict[str, Any], create: bool = True, faces: int = 3, edges: int = 2):
        doc = FakeMRDoc()
        fm = FakeMRFM(doc, create)
        face_objs = [(f"face{i}", None) for i in range(faces)]
        edge_objs = [(f"edge{i}", None) for i in range(edges)]
        with mock.patch.multiple(
            sw_mates_adv,
            require_part=lambda: (None, doc),
            feature_manager=lambda d: fm,
            iter_face_objects=lambda d: face_objs,
            iter_edge_objects=lambda d: edge_objs,
            iter_feature_objects=lambda d: list(d.features),
            dialogs_suppressed=lambda: mock.MagicMock(),
            clear_selection=lambda d: None,
        ):
            out = sw_mates_adv.add_mate_reference(args)
        return out, fm

    def test_twelve_args_in_typelib_order(self) -> None:
        out, fm = self._run({"name": "Ref", "references": [
            {"face": 1, "type": "coincident", "alignment": "aligned", "align_axes": True},
            {"edge": 0, "type": "concentric", "alignment": "anti_aligned"}]})
        self.assertTrue(out["ok"], out)
        (args,) = fm.calls
        self.assertEqual(len(args), 12)
        self.assertEqual(args[0], "Ref")
        self.assertEqual(args[1:5], ("face1", 2, 1, True))      # primary entity, type, alignment, align axes
        self.assertEqual(args[5:9], ("edge0", 3, 2, False))     # secondary
        self.assertEqual((args[9].varianttype, args[9].value), (9, None))  # tertiary: typed null
        self.assertEqual(args[10:12], (0, 0))
        d = out["data"]
        self.assertEqual((d["mate_references_before"], d["mate_references_after"]), (0, 1))
        self.assertEqual((d["feature_count_before"], d["feature_count_after"]), (1, 2))

    def test_single_reference_pads_unused_slots(self) -> None:
        out, fm = self._run({"references": [{"face": 0}]})
        (args,) = fm.calls
        self.assertEqual(len(args), 12)
        self.assertEqual(args[0], "MateReference")
        self.assertEqual(args[1:5], ("face0", 0, 0, False))
        self.assertEqual(args[6:9], (0, 0, False))

    def test_no_feature_returned_is_failure(self) -> None:
        out, _ = self._run({"references": [{"face": 0}]}, create=False)
        self.assertFalse(out["ok"])

    def test_validation_before_com(self) -> None:
        for bad in (
            {}, {"references": []}, {"references": [{"face": 0}] * 4}, {"references": [{}]},
            {"references": [{"face": 0, "edge": 0}]}, {"references": [{"face": -1}]},
            {"references": [{"face": True}]}, {"references": [{"face": 0, "type": "bogus"}]},
            {"references": [{"face": 0, "alignment": "bogus"}]}, {"references": [{"face": 99}]},
        ):
            out, fm = self._run(bad)
            self.assertFalse(out["ok"], bad)
            self.assertEqual(fm.calls, [], bad)


# --------------------------------------------------------------------------
# Component patterns, mirror, sub-assembly
# --------------------------------------------------------------------------


class Comp:
    def __init__(self, name: str, x: float = 0.0) -> None:
        self.Name2 = name
        self.GetSelectByIDString = f"{name}@Assem1"
        self.Transform2 = self
        self.ArrayData = [1, 0, 0, 0, 1, 0, 0, 0, 1, x, 0.0, 0.0, 1.0, 0, 0, 0]


class FeatureStub:
    def __init__(self, name: str, type_name: str) -> None:
        self.Name, self.GetTypeName2 = name, type_name


class AsmDoc:
    """Assembly fake whose feature manager and doc calls mutate the component list."""

    def __init__(self, names: list[str]) -> None:
        self.components = [Comp(n, 0.01 * i) for i, n in enumerate(names)]
        self.tree: list[Any] = [FeatureStub("Origin", "OriginProfileFeature")]
        self.fm = self
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.add_per_call: list[str] = []      # components a pattern call adds
        self.return_feature = True
        self.mirror_adds: list[str] = []
        self.virtual_children: list[str] = []  # children InsertNewVirtualAssembly "moves" in
        self.file_ok = True

    def _created(self, member: str, args: tuple[Any, ...], type_name: str) -> Any:
        self.calls.append((member, args))
        if not self.return_feature:
            return None
        feature = FeatureStub(f"{type_name}1", type_name)
        self.tree.append(feature)
        self.components.extend(Comp(n, 0.5) for n in self.add_per_call)
        return feature

    def FeatureLinearPattern5(self, *a: Any) -> Any:
        return self._created("FeatureLinearPattern5", a, "LocalLPattern")

    def FeatureCircularPattern5(self, *a: Any) -> Any:
        return self._created("FeatureCircularPattern5", a, "LocalCirPattern")

    def InsertDerivedPattern2(self, *a: Any) -> Any:
        return self._created("InsertDerivedPattern2", a, "LocalDerivedPattern")

    def MirrorComponents3(self, *a: Any) -> Any:
        self.calls.append(("MirrorComponents3", a))
        self.components.extend(Comp(n, -0.5) for n in self.mirror_adds)
        return None

    def InsertNewVirtualAssembly(self, holder: Any) -> int:
        self.calls.append(("InsertNewVirtualAssembly", (holder,)))
        doc = self

        class Sub(Comp):
            """Renaming the sub-assembly renames the path of its children, as SOLIDWORKS does."""

            @property
            def Name2(self) -> str:  # type: ignore[override]
                return self._name

            @Name2.setter
            def Name2(self, new: str) -> None:
                old, self._name = getattr(self, "_name", ""), new
                for c in doc.components:
                    if old and c.Name2.startswith(old + "/"):
                        c.Name2 = new + c.Name2[len(old):]

        sub = Sub("Assem2^Assem1-1")
        sub._name = "Assem2^Assem1-1"
        self.components = [c for c in self.components if c.Name2 not in self.virtual_children] + [sub]
        self.components += [Comp(f"{sub.Name2}/{n}") for n in self.virtual_children]
        holder.value = sub
        return 1

    def MakeAssemblyFromSelectedComponents(self, path: str) -> bool:
        self.calls.append(("MakeAssemblyFromSelectedComponents", (path,)))
        if self.file_ok:
            sub = Comp("Group1-1")
            self.components = [c for c in self.components if c.Name2 not in self.virtual_children] + [sub]
            self.components += [Comp(f"Group1-1/{n}") for n in self.virtual_children]
        return self.file_ok


class PatternEnv:
    def __init__(self, doc: AsmDoc, mates: int = 0) -> None:
        self.doc, self.mates = doc, mates
        self.by_id: list[tuple[str, str, int, bool]] = []
        self.refs: list[tuple[dict[str, Any], bool]] = []
        self.patches: list[Any] = []

    def __enter__(self) -> "PatternEnv":
        doc = self.doc

        def iter_components(d: Any, top_only: bool = False) -> list[Any]:
            return [c for c in d.components if not top_only or "/" not in c.Name2]

        def select_by_id(d: Any, name: str, kind: str, mark: int = 0, append: bool = False, ext: Any = None) -> bool:
            self.by_id.append((name, kind, mark, append))
            return True

        def select_ref(d: Any, spec: dict[str, Any], append: bool) -> str:
            self.refs.append((spec, append))
            return "ref"

        common = dict(
            require_assembly=lambda: (None, doc),
            clear_selection=lambda d: None,
            rebuild=lambda d: True,
            iter_components=iter_components,
        )
        for module in (sw_asm_pattern, sw_assembly):
            self.patches.append(mock.patch.multiple(module, **common))
        self.patches.append(mock.patch.multiple(
            sw_asm_pattern,
            dialogs_suppressed=lambda: mock.MagicMock(),
            feature_manager=lambda d: d.fm,
            iter_feature_objects=lambda d: list(d.tree),
            select_by_id=select_by_id,
            select_object=lambda *a, **k: True,
            mate_features=lambda d: [object()] * self.mates,
            rename_feature=lambda f, n: None,
            _select_mate_entity=select_ref,
            find_feature=lambda d, name: ("PLANE", name),
            resolve_plane_name=lambda d, name, planes=None: {"right": "Right Plane"}.get(name, name),
        ))
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in self.patches:
            p.stop()


class LinearComponentPatternTests(unittest.TestCase):
    def _base(self, **extra: Any) -> dict[str, Any]:
        return {"components": ["P-1"], "direction": {"component": "Rail-1", "edge": 0}, "spacing_mm": 25, "count": 3, **extra}

    def test_exact_call_marks_and_counts(self) -> None:
        doc = AsmDoc(["P-1", "Rail-1"])
        doc.add_per_call = ["P-2", "P-3"]
        with PatternEnv(doc) as env:
            out = sw_asm_pattern.linear_component_pattern(self._base())
        self.assertTrue(out["ok"], out)
        ((member, args),) = doc.calls
        self.assertEqual(member, "FeatureLinearPattern5")
        self.assertEqual(len(args), 22)
        self.assertEqual(args[:6], (3, 0.025, 1, 0.0, False, False))
        self.assertEqual(args[6:10], ("", "", False, False))
        self.assertEqual(args[21], False)
        marks = sw_asm_pattern.LIVE_PROBE_PATTERN_MARKS
        self.assertEqual(env.refs[0][0]["mark"], marks["direction1"])
        self.assertEqual(env.by_id, [("P-1@Assem1", "COMPONENT", marks["components"], True)])
        d = out["data"]
        self.assertEqual((d["component_count_before"], d["component_count_after"]), (2, 4))
        self.assertEqual((d["feature_count_before"], d["feature_count_after"]), (1, 2))
        self.assertEqual(d["expected_new_components"], 2)
        self.assertEqual([c["name"] for c in d["new_components"]], ["P-2", "P-3"])
        self.assertEqual(d["feature_type"], "LocalLPattern")

    def test_two_directions(self) -> None:
        doc = AsmDoc(["P-1", "Rail-1"])
        doc.add_per_call = ["P-2", "P-3", "P-4", "P-5", "P-6"]
        with PatternEnv(doc) as env:
            out = sw_asm_pattern.linear_component_pattern(self._base(
                direction2={"component": "Rail-1", "edge": 1}, count2=2, spacing2_mm=10, reverse2=True))
        self.assertTrue(out["ok"], out)
        args = doc.calls[0][1]
        self.assertEqual(args[:6], (3, 0.025, 2, 0.01, False, True))
        self.assertEqual(env.refs[1][0]["mark"], sw_asm_pattern.LIVE_PROBE_PATTERN_MARKS["direction2"])
        self.assertEqual(out["data"]["expected_new_components"], 5)

    def test_returned_feature_but_no_components_is_noop_failure(self) -> None:
        doc = AsmDoc(["P-1", "Rail-1"])
        with PatternEnv(doc):
            out = sw_asm_pattern.linear_component_pattern(self._base())
        self.assertFalse(out["ok"])
        self.assertIn("no-op", out["message"])

    def test_wrong_component_delta_is_failure(self) -> None:
        doc = AsmDoc(["P-1", "Rail-1"])
        doc.add_per_call = ["P-2"]
        with PatternEnv(doc):
            out = sw_asm_pattern.linear_component_pattern(self._base())
        self.assertFalse(out["ok"])
        self.assertIn("expected 2", out["message"])

    def test_no_feature_is_failure(self) -> None:
        doc = AsmDoc(["P-1", "Rail-1"])
        doc.return_feature = False
        with PatternEnv(doc):
            self.assertFalse(sw_asm_pattern.linear_component_pattern(self._base())["ok"])

    def test_validation_before_com(self) -> None:
        doc = AsmDoc(["P-1", "Rail-1"])
        for bad in (
            {"components": []}, {"components": ["P-1", "P-1"]}, {"components": ["Nope-1"]}, {"components": ["P-1/x"]},
            {"components": "P-1"}, {"direction": None}, {"spacing_mm": 0}, {"spacing_mm": -3}, {"spacing_mm": True},
            {"count": 1}, {"count": 5000}, {"count": 2.5}, {"count2": 2},
            {"direction2": {"edge": 0}, "count2": 2},  # second spacing missing
        ):
            with PatternEnv(doc) as env:
                out = sw_asm_pattern.linear_component_pattern({**self._base(), **bad})
            self.assertFalse(out["ok"], bad)
            self.assertEqual(doc.calls, [], bad)
            self.assertEqual(env.by_id, [], bad)

    def test_axis_and_plane_references_use_select_by_id(self) -> None:
        doc = AsmDoc(["P-1", "Rail-1"])
        doc.add_per_call = ["P-2", "P-3"]
        with PatternEnv(doc) as env:
            out = sw_asm_pattern.linear_component_pattern(self._base(direction={"axis": "Axis1"}))
        self.assertTrue(out["ok"], out)
        self.assertEqual(env.by_id[0], ("Axis1", "AXIS", sw_asm_pattern.LIVE_PROBE_PATTERN_MARKS["direction1"], False))


class CircularComponentPatternTests(unittest.TestCase):
    def test_exact_call(self) -> None:
        doc = AsmDoc(["Bolt-1", "Hub-1"])
        doc.add_per_call = ["Bolt-2", "Bolt-3", "Bolt-4"]
        with PatternEnv(doc) as env:
            out = sw_asm_pattern.circular_component_pattern(
                {"components": ["Bolt-1"], "axis": {"axis": "Axis1"}, "count": 4, "angle_deg": 360})
        self.assertTrue(out["ok"], out)
        ((member, args),) = doc.calls
        self.assertEqual(member, "FeatureCircularPattern5")
        self.assertEqual(len(args), 14)
        self.assertEqual(args[0], 4)
        self.assertAlmostEqual(args[1], 2 * math.pi)
        self.assertEqual((args[2], args[3], args[4], args[5]), (False, "", False, True))
        self.assertEqual(args[8:], (False, False, 1, 0.0, "", False))
        marks = sw_asm_pattern.LIVE_PROBE_PATTERN_MARKS
        self.assertEqual(env.by_id[0], ("Axis1", "AXIS", marks["axis"], False))
        self.assertEqual(env.by_id[1], ("Bolt-1@Assem1", "COMPONENT", marks["components"], True))
        self.assertEqual(out["data"]["expected_new_components"], 3)
        self.assertEqual(out["data"]["source_origins_mm"], [[0.0, 0.0, 0.0]])

    def test_noop_and_validation(self) -> None:
        doc = AsmDoc(["Bolt-1", "Hub-1"])
        with PatternEnv(doc):
            out = sw_asm_pattern.circular_component_pattern({"components": ["Bolt-1"], "axis": {"axis": "Axis1"}})
        self.assertFalse(out["ok"])
        doc.calls.clear()
        for bad in ({"count": 1}, {"angle_deg": 0}, {"angle_deg": 400}, {"axis": None}, {"components": ["X-1"]}):
            with PatternEnv(doc):
                o = sw_asm_pattern.circular_component_pattern(
                    {"components": ["Bolt-1"], "axis": {"axis": "Axis1"}, **bad})
            self.assertFalse(o["ok"], bad)
        self.assertEqual(doc.calls[:0], [])
        self.assertEqual([c for c in doc.calls if c[0] == "FeatureCircularPattern5"], [])


class PatternDrivenTests(unittest.TestCase):
    def test_zero_param_call_and_marks(self) -> None:
        doc = AsmDoc(["Pin-1", "Plate-1"])
        doc.add_per_call = ["Pin-2", "Pin-3"]
        with PatternEnv(doc) as env:
            out = sw_asm_pattern.pattern_driven_component_pattern(
                {"components": ["Pin-1"], "driving_feature": "CirPattern1", "driving_component": "Plate-1",
                 "expected_new_components": 2})
        self.assertTrue(out["ok"], out)
        self.assertEqual(doc.calls, [("InsertDerivedPattern2", ())])
        m = sw_asm_pattern.LIVE_PROBE_DERIVED_MARKS
        self.assertEqual(env.by_id[0], ("Pin-1@Assem1", "COMPONENT", m["components"], False))
        self.assertEqual(env.by_id[1], (
            "CirPattern1@Plate-1@Assem1", sw_asm_pattern.LIVE_PROBE_DRIVING_FEATURE_TYPE, m["driving_feature"], True))

    def test_count_mismatch_noop_and_validation(self) -> None:
        doc = AsmDoc(["Pin-1", "Plate-1"])
        doc.add_per_call = ["Pin-2"]
        with PatternEnv(doc):
            out = sw_asm_pattern.pattern_driven_component_pattern(
                {"components": ["Pin-1"], "driving_feature": "CirPattern1", "expected_new_components": 2})
        self.assertFalse(out["ok"])
        doc2 = AsmDoc(["Pin-1"])
        with PatternEnv(doc2):
            self.assertFalse(sw_asm_pattern.pattern_driven_component_pattern(
                {"components": ["Pin-1"], "driving_feature": "CirPattern1"})["ok"])  # no components added
            for bad in ({"driving_feature": ""}, {"driving_component": "Nope-1"}, {"expected_new_components": 0}):
                self.assertFalse(sw_asm_pattern.pattern_driven_component_pattern(
                    {"components": ["Pin-1"], "driving_feature": "F", **bad})["ok"], bad)
        self.assertEqual([c[0] for c in doc2.calls], ["InsertDerivedPattern2"])


class MirrorComponentsTests(unittest.TestCase):
    def test_fourteen_args_and_measurement(self) -> None:
        doc = AsmDoc(["Arm-1", "Base-1"])
        doc.mirror_adds = ["Arm-2"]
        with PatternEnv(doc):
            out = sw_asm_pattern.mirror_components({"components": ["Arm-1"], "plane": "right", "orientation": "rotate_x"})
        self.assertTrue(out["ok"], out)
        ((member, args),) = doc.calls
        self.assertEqual(member, "MirrorComponents3")
        self.assertEqual(len(args), 14)
        self.assertEqual(args[0], ("PLANE", "Right Plane"))
        self.assertEqual(args[1].varianttype, 0x2000 | 9)          # VT_ARRAY | VT_DISPATCH
        self.assertEqual(args[2].varianttype, 0x2000 | 3)          # VT_ARRAY | VT_I4
        self.assertEqual(tuple(args[2].value), (sw_asm_pattern.MIRROR_ORIENTATIONS["rotate_x"],))
        self.assertEqual((args[3], args[5]), (False, False))
        self.assertEqual((args[4].varianttype, args[6].varianttype), (0, 0))  # VT_EMPTY: no opposite-hand files
        self.assertEqual((args[7], args[8], args[9]), (sw_asm_pattern.MIRROR_NAME_MODIFIERS["suffix"], "", ""))
        self.assertEqual(args[11:], (False, False, False))
        d = out["data"]
        self.assertEqual((d["component_count_before"], d["component_count_after"]), (2, 3))
        self.assertEqual(d["source_origins_mm"], [[0.0, 0.0, 0.0]])
        self.assertEqual(d["new_components"], [{"name": "Arm-2", "origin_mm": [-500.0, 0.0, 0.0]}])

    def test_no_new_component_is_failure(self) -> None:
        doc = AsmDoc(["Arm-1"])
        with PatternEnv(doc):
            out = sw_asm_pattern.mirror_components({"components": ["Arm-1"], "plane": "right"})
        self.assertFalse(out["ok"])

    def test_validation_before_com(self) -> None:
        doc = AsmDoc(["Arm-1"])
        for bad in ({"components": []}, {"components": ["Nope"]}, {"plane": ""}, {"orientation": "sideways"}):
            with PatternEnv(doc):
                self.assertFalse(sw_asm_pattern.mirror_components({"components": ["Arm-1"], "plane": "right", **bad})["ok"], bad)
        self.assertEqual(doc.calls, [])

    def test_unknown_plane(self) -> None:
        doc = AsmDoc(["Arm-1"])
        with PatternEnv(doc):
            with mock.patch.object(sw_asm_pattern, "find_feature", return_value=None):
                self.assertFalse(sw_asm_pattern.mirror_components({"components": ["Arm-1"], "plane": "right"})["ok"])
        self.assertEqual(doc.calls, [])


class CreateSubassemblyTests(unittest.TestCase):
    def test_virtual_mode_refused_before_com(self) -> None:
        # Live C1 (2017): InsertNewVirtualAssembly leaves an empty holder, so virtual mode is refused up front.
        doc = AsmDoc(["A-1", "B-1"])
        with PatternEnv(doc) as env:
            out = sw_asm_pattern.create_subassembly({"components": ["A-1", "B-1"], "name": "Group", "mode": "virtual"})
        self.assertFalse(out["ok"])
        self.assertTrue(out["data"].get("fenced"))
        self.assertIn("mode=file", out["message"])
        self.assertEqual(env.by_id, [])
        self.assertEqual(doc.calls, [])

    def test_default_mode_is_file(self) -> None:
        doc = AsmDoc(["A-1", "B-1", "C-1"])
        doc.virtual_children = ["A-1", "B-1"]
        with PatternEnv(doc):
            sw_asm_pattern.create_subassembly({"components": ["A-1", "B-1"], "name": "GroupD"})
        ((member, _),) = doc.calls
        self.assertEqual(member, "MakeAssemblyFromSelectedComponents")

    def test_file_mode_path_under_output_root(self) -> None:
        doc = AsmDoc(["A-1", "B-1", "C-1"])
        doc.virtual_children = ["A-1", "B-1"]
        with PatternEnv(doc):
            out = sw_asm_pattern.create_subassembly({"components": ["A-1", "B-1"], "name": "Group1", "mode": "file"})
        ((member, args),) = doc.calls
        self.assertEqual(member, "MakeAssemblyFromSelectedComponents")
        self.assertEqual(len(args), 1)
        self.assertTrue(Path(args[0]).is_relative_to(sw_core.OUTPUT_ROOT.resolve()))
        self.assertTrue(args[0].lower().endswith("group1.sldasm"))
        self.assertEqual(out["data"]["path"], args[0])

    def test_file_mode_refusal(self) -> None:
        doc = AsmDoc(["A-1", "B-1"])
        doc.file_ok = False
        with PatternEnv(doc):
            out = sw_asm_pattern.create_subassembly({"components": ["A-1", "B-1"], "name": "Group2", "mode": "file"})
        self.assertFalse(out["ok"])

    def test_validation_before_com(self) -> None:
        doc = AsmDoc(["A-1", "B-1"])
        for bad in ({"components": []}, {"components": ["A-1", "Z-9"]}, {"name": ""}, {"name": "..\\evil"},
                    {"name": "a/b"}, {"mode": "dialog"}):
            with PatternEnv(doc) as env:
                out = sw_asm_pattern.create_subassembly({"components": ["A-1", "B-1"], "name": "Group", **bad})
            self.assertFalse(out["ok"], bad)
            self.assertEqual(env.by_id, [], bad)
        self.assertEqual(doc.calls, [])


if __name__ == "__main__":
    unittest.main()
