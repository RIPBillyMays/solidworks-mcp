# Offline tests for Batch C3 edit_feature (3.9) and the split_body cut retry (3.11).
# COM objects are fakes; no SOLIDWORKS is touched.

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

from solidworks_mcp import sw_body, sw_core, sw_edit
from test_sw2017_batchC_surface import FakeFM, snap


class FakeData:
    """A definition object: raw (metre/radian) values in ``vals``; records every call."""

    def __init__(self, vals: dict[str, Any], calls: list[tuple[Any, ...]], access: bool = True) -> None:
        self.vals, self.calls, self.access = vals, calls, access

    def _FlagAsMethod(self, *names: str) -> None:
        self.calls.append(("flag", *names))

    def AccessSelections(self, doc: Any, comp: Any) -> bool:
        self.calls.append(("access",))
        return self.access

    def ReleaseSelectionAccess(self) -> None:
        self.calls.append(("release",))

    # IExtrudeFeatureData2
    def GetDepth(self, forward: bool) -> float:
        self.calls.append(("GetDepth", forward))
        return self.vals["depth"]

    def SetDepth(self, forward: bool, depth: float) -> None:
        self.calls.append(("SetDepth", forward, depth))
        self.vals["depth"] = depth

    # IChamferFeatureData2
    def GetEdgeChamferDistance(self, side: int) -> float:
        return self.vals["chamfer"]

    def SetEdgeChamferDistance(self, side: int, dist: float) -> None:
        self.calls.append(("SetEdgeChamferDistance", side, dist))
        self.vals["chamfer"] = dist

    def __getattr__(self, name: str) -> Any:
        keys = {"ReverseDirection": "reverse", "DefaultRadius": "radius", "D1Spacing": "spacing",
                "D1TotalInstances": "lcount", "TotalInstances": "ccount", "Spacing": "angle",
                "Thickness": "thickness"}
        if name in keys and "vals" in self.__dict__:
            return self.__dict__["vals"][keys[name]]
        raise AttributeError(name)

    def __setattr__(self, name: str, val: Any) -> None:
        keys = {"ReverseDirection": "reverse", "DefaultRadius": "radius", "D1Spacing": "spacing",
                "D1TotalInstances": "lcount", "TotalInstances": "ccount", "Spacing": "angle",
                "Thickness": "thickness"}
        if name in keys:
            self.calls.append(("set", name, val))
            self.vals[keys[name]] = val
        else:
            object.__setattr__(self, name, val)


class FakeFeature:
    """A feature whose committed state only changes when ModifyDefinition really applies it."""

    def __init__(self, type_name: str, state: dict[str, Any], calls: list[tuple[Any, ...]],
                 modify_ok: bool = True, applies: bool = True, access: bool = True) -> None:
        self.type_name, self.state, self.calls = type_name, state, calls
        self.modify_ok, self.applies, self.access = modify_ok, applies, access

    def GetDefinition(self) -> FakeData:
        return FakeData(dict(self.state), self.calls, self.access)

    def ModifyDefinition(self, data: FakeData, doc: Any, comp: Any) -> bool:
        self.calls.append(("modify",))
        if self.applies:
            self.state.update(data.vals)
        return self.modify_ok


class Harness:
    def __init__(self, feature: FakeFeature | None, snaps: list[dict[str, Any]] | None = None,
                 problems: list[Any] | None = None) -> None:
        self.feature, self.problems = feature, problems or []
        self.snaps = list(snaps or [snap(volume_mm3=100.0), snap(volume_mm3=120.0)])
        self.patches: list[Any] = []
        self.com_touched = False

    def __enter__(self) -> "Harness":
        def require_part() -> tuple[None, str]:
            self.com_touched = True
            return None, "DOC"

        patch = {
            "require_part": require_part,
            "exit_active_sketch": lambda doc: None,
            "dialogs_suppressed": lambda: mock.MagicMock(),
            "find_feature": lambda doc, name: self.feature,
            "feature_property": lambda f, m, d="": f.type_name,
            "rebuild": lambda doc: True,
            "whats_wrong": lambda doc: self.problems,
            "_snapshot": lambda doc: self.snaps.pop(0),
        }
        for name, repl in patch.items():
            p = mock.patch.object(sw_edit, name, repl)
            p.start()
            self.patches.append(p)
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in self.patches:
            p.stop()


def feature_for(type_name: str, **state: Any) -> tuple[FakeFeature, list[tuple[Any, ...]]]:
    calls: list[tuple[Any, ...]] = []
    return FakeFeature(type_name, state, calls), calls


class AllowListTests(unittest.TestCase):
    def test_exactly_the_six_adr_types(self) -> None:
        self.assertEqual(
            {k: set(v) for k, v in sw_edit.EDIT_TYPES.items()},
            {
                "Extrusion": {"depth_mm", "reverse"}, "Fillet": {"radius_mm"}, "Chamfer": {"distance_mm"},
                "LPattern": {"spacing_mm", "count"}, "CirPattern": {"count", "angle_deg"},
                "Shell": {"thickness_mm"},
            },
        )

    def test_registered_and_not_fenced(self) -> None:
        self.assertIn("edit_feature", sw_core.HANDLERS)
        from solidworks_mcp.sw2017_fences import FENCES

        self.assertNotIn("edit_feature", FENCES)

    def test_data_methods_that_take_arguments_are_flagged(self) -> None:
        feat, calls = feature_for("Extrusion", depth=0.01, reverse=False)
        with Harness(feat):
            sw_edit.edit_feature({"feature_name": "Boss", "params": {"depth_mm": 20}})
        flagged = [c[1] for c in calls if c[0] == "flag"]
        for name in ("GetDepth", "SetDepth", "GetEdgeChamferDistance", "SetEdgeChamferDistance"):
            self.assertIn(name, flagged)
        # flagged before the first member call, on the edited and on the read-back definition
        self.assertLess(calls.index(("flag", "GetDepth")), calls.index(("GetDepth", True)))


class EditRoundTripTests(unittest.TestCase):
    def run_edit(self, type_name: str, state: dict[str, Any], params: dict[str, Any], **kw: Any):
        feat, calls = feature_for(type_name, **state)
        with Harness(feat, **kw):
            out = sw_edit.edit_feature({"feature_name": "F", "params": params})
        return out, calls, feat

    def test_extrude_depth_and_reverse(self) -> None:
        out, calls, feat = self.run_edit("Extrusion", {"depth": 0.01, "reverse": False},
                                         {"depth_mm": 25, "reverse": True})
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["data"]["changed"])
        self.assertIn(("SetDepth", True, 0.025), calls)
        self.assertIn(("set", "ReverseDirection", True), calls)
        self.assertEqual(out["data"]["params"]["depth_mm"],
                         {"requested": 25.0, "before": 10.0, "after": 25.0, "status": "changed"})
        self.assertEqual(out["data"]["volume_before_mm3"], 100.0)
        self.assertEqual(out["data"]["volume_after_mm3"], 120.0)
        self.assertEqual(feat.state["depth"], 0.025)

    def test_call_order_modify_then_release(self) -> None:
        _, calls, _ = self.run_edit("Fillet", {"radius": 0.002}, {"radius_mm": 3})
        order = [c[0] for c in calls if c[0] in ("access", "set", "modify", "release")]
        self.assertEqual(order, ["access", "set", "modify", "release"])

    def test_each_type_writes_the_right_member(self) -> None:
        cases = [
            ("Fillet", {"radius": 0.002}, {"radius_mm": 3}, ("set", "DefaultRadius", 0.003)),
            ("Chamfer", {"chamfer": 0.001}, {"distance_mm": 2}, ("SetEdgeChamferDistance", 0, 0.002)),
            ("LPattern", {"spacing": 0.01, "lcount": 3}, {"spacing_mm": 15}, ("set", "D1Spacing", 0.015)),
            ("LPattern", {"spacing": 0.01, "lcount": 3}, {"count": 5}, ("set", "D1TotalInstances", 5)),
            ("CirPattern", {"ccount": 4, "angle": 1.0}, {"count": 6}, ("set", "TotalInstances", 6)),
            ("CirPattern", {"ccount": 4, "angle": 1.0}, {"angle_deg": 90}, ("set", "Spacing", math.radians(90))),
            ("Shell", {"thickness": 0.001}, {"thickness_mm": 2}, ("set", "Thickness", 0.002)),
        ]
        for type_name, state, params, expected in cases:
            out, calls, _ = self.run_edit(type_name, state, params)
            self.assertTrue(out["ok"], (type_name, out))
            self.assertIn(expected, calls, type_name)

    def test_pattern_count_is_int_in_report(self) -> None:
        out, _, _ = self.run_edit("CirPattern", {"ccount": 4, "angle": 1.0}, {"count": 6})
        self.assertEqual(out["data"]["params"]["count"]["after"], 6)

    def test_no_change_detection_when_modify_is_silent_noop(self) -> None:
        feat, calls = feature_for("Extrusion", depth=0.01, reverse=False)
        feat.applies = False  # ModifyDefinition returns True and changes nothing
        with Harness(feat):
            out = sw_edit.edit_feature({"feature_name": "F", "params": {"depth_mm": 25}})
        self.assertFalse(out["ok"])
        self.assertFalse(out["data"]["changed"])
        self.assertEqual(out["data"]["params"]["depth_mm"]["status"], "failed")
        self.assertIn("read-back", out["message"])
        self.assertIn(("release",), calls)

    def test_requested_value_already_present_skips_modify(self) -> None:
        feat, calls = feature_for("Shell", thickness=0.002)
        with Harness(feat):
            out = sw_edit.edit_feature({"feature_name": "F", "params": {"thickness_mm": 2}})
        self.assertTrue(out["ok"])
        self.assertFalse(out["data"]["changed"])
        self.assertEqual(out["data"]["params"]["thickness_mm"]["status"], "unchanged")
        self.assertNotIn(("modify",), calls)
        self.assertEqual([c[0] for c in calls].count("release"), 1)

    def test_mixed_one_changed_one_unchanged(self) -> None:
        out, _, _ = self.run_edit("LPattern", {"spacing": 0.01, "lcount": 3}, {"spacing_mm": 10, "count": 4})
        self.assertTrue(out["ok"])
        self.assertTrue(out["data"]["changed"])
        self.assertEqual({k: v["status"] for k, v in out["data"]["params"].items()},
                         {"spacing_mm": "unchanged", "count": "changed"})

    def test_rebuild_errors_make_it_fail_even_if_value_moved(self) -> None:
        feat, _ = feature_for("Shell", thickness=0.001)
        with Harness(feat, problems=[{"feature": "Shell1", "code": 1, "is_warning": False}]):
            out = sw_edit.edit_feature({"feature_name": "F", "params": {"thickness_mm": 2}})
        self.assertFalse(out["ok"])
        self.assertTrue(out["data"]["changed"])
        self.assertIn("rebuild errors", out["message"])


class RefusalAndFailureTests(unittest.TestCase):
    def test_unsupported_type_is_refused_listing_the_type(self) -> None:
        feat, calls = feature_for("RefPlane")
        with Harness(feat):
            out = sw_edit.edit_feature({"feature_name": "Plane1", "params": {"depth_mm": 5}})
        self.assertFalse(out["ok"])
        self.assertIn("'RefPlane'", out["message"])
        self.assertIn("Extrusion", out["message"])
        self.assertEqual(out["data"]["feature_type"], "RefPlane")
        self.assertEqual(calls, [])  # never even asked for the definition

    def test_param_not_valid_for_type(self) -> None:
        feat, calls = feature_for("Fillet", radius=0.002)
        with Harness(feat):
            out = sw_edit.edit_feature({"feature_name": "F", "params": {"depth_mm": 5}})
        self.assertFalse(out["ok"])
        self.assertIn("radius_mm", out["message"])
        self.assertEqual(calls, [])

    def test_unknown_feature(self) -> None:
        with Harness(None):
            out = sw_edit.edit_feature({"feature_name": "Nope", "params": {"depth_mm": 5}})
        self.assertFalse(out["ok"])
        self.assertIn("No feature named", out["message"])

    def test_input_validation_never_touches_com(self) -> None:
        bad_inputs = [
            {}, {"feature_name": "", "params": {"depth_mm": 1}}, {"feature_name": "F"},
            {"feature_name": "F", "params": {}}, {"feature_name": "F", "params": {"bogus": 1}},
            {"feature_name": "F", "params": {"depth_mm": -1}}, {"feature_name": "F", "params": {"depth_mm": "x"}},
            {"feature_name": "F", "params": {"count": 1}}, {"feature_name": "F", "params": {"count": 2.5}},
            {"feature_name": "F", "params": {"reverse": 1}}, {"feature_name": "F", "params": {"angle_deg": 400}},
            {"feature_name": "F", "params": {"radius_mm": True}},
        ]
        for bad in bad_inputs:
            feat, _ = feature_for("Extrusion", depth=0.01, reverse=False)
            with Harness(feat) as h:
                out = sw_edit.edit_feature(bad)
            self.assertFalse(out["ok"], bad)
            self.assertFalse(h.com_touched, bad)

    def test_modify_failure_releases_selection_access(self) -> None:
        feat, calls = feature_for("Extrusion", depth=0.01, reverse=False)
        feat.modify_ok = False
        with Harness(feat):
            out = sw_edit.edit_feature({"feature_name": "F", "params": {"depth_mm": 25}})
        self.assertFalse(out["ok"])
        self.assertIn("ModifyDefinition reported failure", out["message"])
        self.assertEqual([c[0] for c in calls if c[0] in ("access", "modify", "release")], ["access", "modify", "release"])

    def test_write_error_releases_and_skips_modify(self) -> None:
        feat, calls = feature_for("Extrusion", depth=0.01, reverse=False)

        def boom(data: Any, raw: Any) -> None:
            raise RuntimeError("setter exploded")

        patched = sw_edit.EditParam("length_mm", sw_edit.EDIT_TYPES["Extrusion"]["depth_mm"].read, boom)
        with Harness(feat), mock.patch.dict(sw_edit.EDIT_TYPES["Extrusion"], {"depth_mm": patched}):
            out = sw_edit.edit_feature({"feature_name": "F", "params": {"depth_mm": 25}})
        self.assertFalse(out["ok"])
        self.assertIn("setter exploded", out["message"])
        self.assertNotIn(("modify",), calls)
        self.assertIn(("release",), calls)

    def test_access_refused_does_not_release_or_modify(self) -> None:
        feat, calls = feature_for("Extrusion", depth=0.01, reverse=False)
        feat.access = False
        with Harness(feat):
            out = sw_edit.edit_feature({"feature_name": "F", "params": {"depth_mm": 25}})
        self.assertFalse(out["ok"])
        self.assertIn("refused selection access", out["message"])
        self.assertNotIn(("modify",), calls)


class SplitViaCutTests(unittest.TestCase):
    def run_split(self, snaps: list[dict[str, Any]], tool_selection: Any, problems: list[Any] | None = None,
                  new_feature: Any = "auto"):
        fm = FakeFM()
        feature = object() if new_feature == "auto" else new_feature
        patch = {
            "require_part": lambda: (None, "DOC"),
            "exit_active_sketch": lambda doc: None,
            "select_sketch_for_feature": lambda doc, name: name,
            "feature_manager": lambda doc: fm,
            "dialogs_suppressed": lambda: mock.MagicMock(),
            "rename_feature": lambda f, n: None,
            "whats_wrong": lambda doc: problems or [],
            "_snapshot": lambda doc: snaps.pop(0),
            "_feature_names": lambda doc: [],
            "_resolve": lambda doc, returned, names: feature,
        }
        patches = [mock.patch.object(sw_edit, k, v) for k, v in patch.items()]
        for p in patches:
            p.start()
        try:
            out = sw_edit.split_via_cut({"tool_selection": tool_selection})
        finally:
            for p in patches:
                p.stop()
        return out, fm

    def test_featurecut4_27_args_through_all_both_ways(self) -> None:
        out, fm = self.run_split(
            [snap(solid_bodies=1, volume_mm3=1000.0), snap(solid_bodies=2, volume_mm3=990.0)],
            {"sketches": ["Kerf"]},
        )
        self.assertTrue(out["ok"], out)
        a = fm.last("FeatureCut4")
        self.assertEqual(len(a), 27)
        self.assertEqual((a[0], a[3], a[4]), (False, 1, 1))  # two directions, through all both
        self.assertEqual(out["data"]["kerf_volume_mm3"], 10.0)
        self.assertEqual((out["data"]["solid_bodies_before"], out["data"]["solid_bodies_after"]), (1, 2))

    def test_body_count_not_rising_is_failure(self) -> None:
        out, _ = self.run_split([snap(solid_bodies=1), snap(solid_bodies=1)], {"sketches": ["Kerf"]})
        self.assertFalse(out["ok"])
        self.assertIn("not split", out["message"])

    def test_no_feature_and_errors_fail(self) -> None:
        out, _ = self.run_split([snap(), snap()], {"sketches": ["K"]}, new_feature=None)
        self.assertFalse(out["ok"])
        out, _ = self.run_split([snap(solid_bodies=1), snap(solid_bodies=2)], {"sketches": ["K"]},
                                problems=[{"feature": "Cut1"}])
        self.assertFalse(out["ok"])

    def test_selection_validation_before_com(self) -> None:
        for bad in ({}, {"planes": ["front"]}, {"sketches": ["A", "B"]}, {"sketches": ["A"], "planes": ["front"]}):
            with mock.patch.object(sw_edit, "require_part", side_effect=AssertionError("COM touched")):
                out = sw_edit.split_via_cut({"tool_selection": bad})
            self.assertFalse(out["ok"], bad)


class SplitBodyDispatchTests(unittest.TestCase):
    def test_method_cut_routes_to_split_via_cut(self) -> None:
        with mock.patch.object(sw_edit, "split_via_cut", return_value={"ok": True, "message": "cut"}) as routed:
            out = sw_body.split_body({"method": "cut", "tool_selection": {"sketches": ["K"]}})
        self.assertEqual(out["message"], "cut")
        routed.assert_called_once()

    def test_unknown_method_refused_before_com(self) -> None:
        with mock.patch.object(sw_body, "require_part", side_effect=AssertionError("COM touched")):
            out = sw_body.split_body({"method": "zap", "tool_selection": {"planes": ["front"]}})
        self.assertFalse(out["ok"])

    def test_schema_offers_method(self) -> None:
        schema = next(t for t in sw_core.TOOLS if t.name == "split_body").inputSchema
        self.assertEqual(schema["properties"]["method"]["enum"], ["split", "cut"])
        self.assertEqual(schema["required"], ["tool_selection"])

    def test_split_body_stays_fenced(self) -> None:
        from solidworks_mcp.sw2017_fences import FENCES

        self.assertIn("split_body", FENCES)
        self.assertIn("combine_bodies", FENCES)
        self.assertIn("set_mass_override", FENCES)


if __name__ == "__main__":
    unittest.main()
