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

"""Offline tests for Batch C2 sheet metal tools (plan items 2.1-2.6).

COM objects are fakes that record the exact member and argument count; no
SOLIDWORKS is touched.
"""

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
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from solidworks_mcp import sw_core, sw_file, sw_sheetmetal as sm
from test_sw2017_enums import ev

BEFORE = {"features": 5, "volume_mm3": 100.0, "size_mm": [10.0, 10.0, 10.0]}


class FakeData:
    """Feature-definition stand-in that records attribute writes and SetFixedFace."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def SetFixedFace(self, *a: Any) -> None:
        self.calls.append(("SetFixedFace", a))


class FakeFM:
    def __init__(self, returns: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.returns = returns or {}
        self.data = FakeData()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args: Any) -> Any:
            self.calls.append((name, args))
            if name == "CreateDefinition":
                return self.data
            return self.returns.get(name, object())

        return call

    def last(self, name: str) -> tuple[Any, ...]:
        return [a for n, a in self.calls if n == name][-1]

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]


class FakeDoc:
    def __init__(self, path: str = "") -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.path = path
        self.export_writes: bytes | None = b"0\nSECTION\n2\nENTITIES\n0\nENDSEC\n"

    def ExportToDWG2(self, *a: Any) -> bool:
        self.calls.append(("ExportToDWG2", a))
        if self.export_writes is not None:
            Path(a[0]).write_bytes(self.export_writes)
        return True


class Harness:
    def __init__(self, fm: FakeFM, after: dict[str, Any] | None = None, flat: bool = True, path: str = "") -> None:
        self.fm = fm
        self.doc = FakeDoc(path)
        self.after = after if after is not None else {"features": 8, "volume_mm3": 120.0, "size_mm": [10.0, 10.0, 14.0]}
        self.snaps = [BEFORE, self.after]
        self.flat = flat
        self.bodies = 1
        self.selected: list[tuple[Any, int, bool]] = []
        self.values: list[str] = []
        self.suppress_selected: list[Any] = []
        self.patches: list[Any] = []

    def __enter__(self) -> "Harness":
        def snapshot(doc: Any) -> dict[str, Any]:
            return self.snaps.pop(0) if len(self.snaps) > 1 else self.snaps[0]

        def feature_result(doc: Any, feature: Any, action: str, **data: Any) -> dict[str, Any]:
            return sw_core.result(feature is not None, action, **data)

        def require_selection(doc: Any, spec: Any, mark: int = 0, append: bool = False) -> int:
            self.selected.append((spec, mark, append))
            return 1

        def select_object(doc: Any, obj: Any, mark: int = 0, append: bool = True) -> bool:
            self.selected.append((obj, mark, append))
            return True

        def value(obj: Any, member: str) -> Any:
            self.values.append(member)
            return True

        flat_feature = mock.MagicMock()
        flat_feature.Select2.side_effect = lambda *a: True

        common = {
            "require_part": lambda: (None, self.doc),
            "feature_manager": lambda doc: self.fm,
            "select_sketch_for_feature": lambda doc, name: name or "Sketch1",
            "dialogs_suppressed": lambda: mock.MagicMock(),
            "rename_feature": lambda f, n: None,
            "feature_result": feature_result,
            "part_snapshot": snapshot,
            "exit_active_sketch": lambda doc: None,
            "clear_selection": lambda doc: None,
            "require_selection": require_selection,
            "select_object": select_object,
            "resolve_sketch": lambda doc, name: (name or "Sketch1", ("sketch", name)),
            "iter_edge_objects": lambda doc: [(f"edge{i}", None) for i in range(4)],
            "iter_feature_objects": lambda doc: [flat_feature] if self.flat else [],
            "feature_property": lambda f, m, d="": "FlatPattern",
            "selectable": lambda obj: obj,
            "value": value,
            "rebuild": lambda doc: True,
            "get_bodies": lambda doc: [object()] * self.bodies,
        }
        for name, repl in common.items():
            p = mock.patch.object(sm, name, repl)
            p.start()
            self.patches.append(p)
        self.flat_feature = flat_feature
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in self.patches:
            p.stop()


class ConstantTests(unittest.TestCase):
    def test_constants_match_2017_enums(self) -> None:
        self.assertEqual(sm.FM_SKETCH_BEND, ev("swFeatureNameID_e.swFmSketchBend"))
        self.assertEqual(sm.SM_END_BLIND, ev("swEndConditions_e.swEndCondBlind"))
        self.assertEqual(sm.SM_RELIEF_RECTANGULAR, ev("swSheetMetalReliefTypes_e.swSheetMetalReliefRectangular"))
        self.assertEqual(sm.SM_HEM_TEAR_RIP, ev("swReliefTearTypes_e.swReliefTearTypeRip"))
        self.assertEqual(sm.EXPORT_ACTION_SHEET_METAL, ev("swExportToDWG_e.swExportToDWG_ExportSheetMetal"))
        for key, name in (("open", "Open"), ("closed", "Closed"), ("tear_drop", "TearDrop"),
                          ("rolled", "Rolled"), ("double", "Double")):
            self.assertEqual(sm.HEM_TYPES[key], ev(f"swHemTypes_e.swHemType{name}"))
        self.assertEqual(sm.HEM_POSITIONS["inside"], ev("swHemPositionTypes_e.swHemPositionTypeInside"))
        self.assertEqual(sm.HEM_POSITIONS["outside"], ev("swHemPositionTypes_e.swHemPositionTypeOutside"))
        for key, name in (("material_inside", "MaterialInside"), ("material_outside", "MaterialOutside"),
                          ("bend_outside", "BendOutside"), ("bend_centerline", "BendCenterLine"),
                          ("bend_sharp", "BendSharp"), ("bend_tangent", "BendTangent")):
            self.assertEqual(sm.FLANGE_POSITIONS[key], ev(f"swFlangePositionTypes_e.swFlangePositionType{name}"))
        for attr, name in (("EDGE_OPT_DEFAULT_RADIUS", "UseDefaultRadius"), ("EDGE_OPT_FLIP_DIR", "FlipDir"),
                           ("EDGE_OPT_DO_OFFSET", "DoOffset"), ("EDGE_OPT_REVERSE_OFFSET", "ReverseOffsetDir"),
                           ("EDGE_OPT_DEFAULT_RELIEF", "UseDefaultRelief")):
            self.assertEqual(getattr(sm, attr), ev(f"swInsertEdgeFlangeOptions_e.swInsertEdgeFlange{name}"))

    def test_tools_registered(self) -> None:
        for name in ("sheet_metal_base_flange", "sheet_metal_edge_flange", "sheet_metal_sketched_bend",
                     "sheet_metal_hem", "sheet_metal_fold_unfold", "export_flat_pattern"):
            self.assertIn(name, sw_core.HANDLERS)
        self.assertIn("InsertSheetMetalBaseFlange2", sw_core._REGISTERED_FLAGS["IFeatureManager"])
        self.assertIn("ExportToDWG2", sw_core._REGISTERED_FLAGS["IPartDoc"])


class BaseFlangeTests(unittest.TestCase):
    ARGS = {"thickness_mm": 2, "bend_radius_mm": 3, "depth_mm": 50}

    def test_exact_call_has_19_args(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            out = sm.sheet_metal_base_flange(dict(self.ARGS, reverse=True))
        self.assertTrue(out["ok"], out)
        a = fm.last("InsertSheetMetalBaseFlange2")
        self.assertEqual(len(a), 19)
        self.assertEqual((a[0], a[1], a[2], a[3], a[4], a[5]), (0.002, True, 0.003, 0.05, 0.0, False))
        self.assertEqual((a[6], a[7]), (0, 0))
        self.assertIsNotNone(a[9])  # PCBA is a typed null, never None
        self.assertEqual(a[16:], (False, False, False))
        self.assertEqual(out["data"]["before"], BEFORE)
        self.assertIn("after", out["data"])

    def test_bad_input_never_reaches_com(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            for bad in ({"thickness_mm": 0, "bend_radius_mm": 1, "depth_mm": 1},
                        {"thickness_mm": 1, "bend_radius_mm": -1, "depth_mm": 1},
                        {"thickness_mm": 1, "bend_radius_mm": 1}):
                self.assertFalse(sm.sheet_metal_base_flange(bad)["ok"])
        self.assertEqual(fm.calls, [])

    def test_unchanged_tree_is_a_failure(self) -> None:
        fm = FakeFM()
        with Harness(fm, after=dict(BEFORE)):
            out = sm.sheet_metal_base_flange(dict(self.ARGS))
        self.assertFalse(out["ok"])
        self.assertIn("silent no-op", out["message"])

    def test_zero_volume_or_wrong_body_count_is_a_failure(self) -> None:
        for after, bodies in (({"features": 8, "volume_mm3": 0.0, "size_mm": [1, 1, 1]}, 1), (None, 2)):
            fm = FakeFM()
            h = Harness(fm, after=after)
            h.bodies = bodies
            with h:
                out = sm.sheet_metal_base_flange(dict(self.ARGS))
            self.assertFalse(out["ok"], out)

    def test_none_return_is_a_failure(self) -> None:
        fm = FakeFM({"InsertSheetMetalBaseFlange2": None})
        with Harness(fm):
            self.assertFalse(sm.sheet_metal_base_flange(dict(self.ARGS))["ok"])


class EdgeFlangeTests(unittest.TestCase):
    def args(self, **extra: Any) -> dict[str, Any]:
        base = {"selection": {"edges": [1, 2]}, "profile_sketches": ["P1", "P2"]}
        base.update(extra)
        return base

    def test_exact_call_has_13_args_and_option_bits(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            out = sm.sheet_metal_edge_flange(self.args(angle_deg=90, radius_mm=2, position="bend_outside",
                                                       offset_mm=-1.5, flip=True))
        self.assertTrue(out["ok"], out)
        a = fm.last("InsertSheetMetalEdgeFlange2")
        self.assertEqual(len(a), 13)
        self.assertEqual(a[2], 128 | 2 | 4 | 8)  # default relief, flip, offset, reverse offset; radius given
        self.assertAlmostEqual(a[3], 1.5707963, places=5)
        self.assertAlmostEqual(a[4], 0.002)
        self.assertEqual(a[5], 3)
        self.assertAlmostEqual(a[6], 0.0015)
        self.assertIsNotNone(a[12])

    def test_default_radius_bit(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            sm.sheet_metal_edge_flange(self.args())
        self.assertEqual(fm.last("InsertSheetMetalEdgeFlange2")[2], 128 | 1)

    def test_validation_before_com(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            self.assertFalse(sm.sheet_metal_edge_flange({"selection": {"edges": [0]}, "profile_sketches": ["a", "b"]})["ok"])
            self.assertFalse(sm.sheet_metal_edge_flange(self.args(angle_deg=0))["ok"])
            self.assertFalse(sm.sheet_metal_edge_flange(self.args(position="nope"))["ok"])
            self.assertFalse(sm.sheet_metal_edge_flange({"selection": {"edges": [99]}, "profile_sketches": ["a"]})["ok"])
        self.assertEqual(fm.calls, [])

    def test_no_geometry_change_fails(self) -> None:
        fm = FakeFM()
        with Harness(fm, after=dict(BEFORE, features=6)):
            self.assertFalse(sm.sheet_metal_edge_flange(self.args())["ok"])


class SketchedBendTests(unittest.TestCase):
    def test_create_definition_route(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            out = sm.sheet_metal_sketched_bend({"fixed_point_mm": [1, 2, 3], "angle_deg": 45, "radius_mm": 2,
                                                "position": "bend_centerline", "reverse": True})
        self.assertTrue(out["ok"], out)
        self.assertEqual(fm.names(), ["CreateDefinition", "CreateFeature"])
        self.assertEqual(fm.last("CreateDefinition"), (35,))
        self.assertIs(fm.last("CreateFeature")[0], fm.data)
        self.assertAlmostEqual(fm.data.BendAngle, 0.7853981, places=5)
        self.assertEqual(fm.data.PositionType, 4)
        self.assertIs(fm.data.ReverseDirection, True)
        self.assertIs(fm.data.UseDefaultBendRadius, False)
        self.assertAlmostEqual(fm.data.BendRadius, 0.002)
        sfx = fm.data.calls[0]
        self.assertEqual(sfx[0], "SetFixedFace")
        self.assertEqual(len(sfx[1]), 4)
        self.assertEqual(sfx[1][:3], (0.001, 0.002, 0.003))
        self.assertEqual(h.selected[0][1], sm.SB_MARK_SKETCH)

    def test_default_radius(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            sm.sheet_metal_sketched_bend({"fixed_point_mm": [0, 0, 0]})
        self.assertIs(fm.data.UseDefaultBendRadius, True)

    def test_validation(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            for bad in ({}, {"fixed_point_mm": [1, 2]}, {"fixed_point_mm": [0, 0, 0], "angle_deg": 0},
                        {"fixed_point_mm": [0, 0, 0], "angle_deg": 270}, {"fixed_point_mm": [0, 0, 0], "position": "x"}):
                self.assertFalse(sm.sheet_metal_sketched_bend(bad)["ok"], bad)
        self.assertEqual(fm.calls, [])

    def test_unchanged_geometry_fails(self) -> None:
        fm = FakeFM()
        with Harness(fm, after=dict(BEFORE, features=6)):
            self.assertFalse(sm.sheet_metal_sketched_bend({"fixed_point_mm": [0, 0, 0]})["ok"])


class HemTests(unittest.TestCase):
    def test_exact_call_has_16_args(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            out = sm.sheet_metal_hem({"selection": {"edges": [3]}, "type": "tear_drop", "length_mm": 6,
                                      "gap_mm": 0.5, "angle_deg": 200, "radius_mm": 1.5, "position": "outside"})
        self.assertTrue(out["ok"], out)
        a = fm.last("InsertSheetMetalHem2")
        self.assertEqual(len(a), 16)
        self.assertEqual((a[0], a[1], a[2]), (2, 1, False))
        self.assertEqual((a[3], a[4]), (0.006, 0.0005))
        self.assertAlmostEqual(a[5], 3.4906585, places=5)
        self.assertAlmostEqual(a[6], 0.0015)
        self.assertIsNotNone(a[8])
        self.assertEqual(h.selected[0][0], {"edges": [3]})

    def test_validation(self) -> None:
        fm = FakeFM()
        with Harness(fm):
            for bad in ({"selection": {"edges": [1]}}, {"selection": {"edges": [1]}, "length_mm": 0},
                        {"selection": {}, "length_mm": 5}, {"selection": {"edges": [1]}, "length_mm": 5, "type": "zz"}):
                self.assertFalse(sm.sheet_metal_hem(bad)["ok"], bad)
        self.assertEqual(fm.calls, [])

    def test_volume_must_grow(self) -> None:
        fm = FakeFM()
        with Harness(fm, after=dict(BEFORE, features=6)):
            self.assertFalse(sm.sheet_metal_hem({"selection": {"edges": [1]}, "length_mm": 5})["ok"])


class FoldTests(unittest.TestCase):
    def test_unfold_uses_marks_and_zero_arg_member(self) -> None:
        fm = FakeFM()
        with Harness(fm) as h:
            out = sm.sheet_metal_fold_unfold({"action": "unfold", "fixed_face": {"faces": [0]}, "bends": {"faces": [1]}})
        self.assertTrue(out["ok"], out)
        self.assertEqual(h.values, ["InsertSheetMetalUnfold"])
        self.assertEqual([m for _, m, _ in h.selected], [sm.SM_MARK_FIXED_FACE, sm.SM_MARK_BENDS])

    def test_fold(self) -> None:
        with Harness(FakeFM()) as h:
            sm.sheet_metal_fold_unfold({"action": "fold", "fixed_face": {"faces": [0]}, "bends": {"faces": [1]}})
        self.assertEqual(h.values, ["InsertSheetMetalFold"])

    def test_flatten_and_unflatten_toggle_suppression(self) -> None:
        with Harness(FakeFM()) as h:
            self.assertTrue(sm.sheet_metal_fold_unfold({"action": "flatten"})["ok"])
        self.assertEqual(h.values, ["EditUnsuppress2"])
        with Harness(FakeFM()) as h:
            sm.sheet_metal_fold_unfold({"action": "unflatten"})
        self.assertEqual(h.values, ["EditSuppress2"])

    def test_unchanged_box_is_failure(self) -> None:
        with Harness(FakeFM(), after=dict(BEFORE)):
            self.assertFalse(sm.sheet_metal_fold_unfold({"action": "flatten"})["ok"])

    def test_validation(self) -> None:
        with Harness(FakeFM()) as h:
            self.assertFalse(sm.sheet_metal_fold_unfold({"action": "spin"})["ok"])
            self.assertFalse(sm.sheet_metal_fold_unfold({"action": "unfold"})["ok"])
        self.assertEqual(h.values, [])

    def test_no_flat_pattern_refused(self) -> None:
        with Harness(FakeFM(), flat=False) as h:
            self.assertFalse(sm.sheet_metal_fold_unfold({"action": "flatten"})["ok"])
        self.assertEqual(h.values, [])


class ExportFlatPatternTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.patch = mock.patch.object(sw_file, "OUTPUT_ROOT", self.root)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.tmp.cleanup()

    def test_exact_call_has_9_args(self) -> None:
        with Harness(FakeFM(), path="C:/x/part.sldprt") as h:
            h.doc.GetPathName = "C:/x/part.sldprt"
            with mock.patch.object(sm, "safe", lambda obj, member, default=None: obj.path):
                out = sm.export_flat_pattern({"path": "flat.dxf", "include_sketches": True})
        self.assertTrue(out["ok"], out)
        a = h.doc.calls[-1][1]
        self.assertEqual(len(a), 9)
        self.assertEqual(Path(a[0]), self.root / "flat.dxf")
        self.assertEqual(a[1:4], ("C:/x/part.sldprt", 1, True))
        self.assertEqual(a[5:8], (False, False, 1 | 4 | 8))
        self.assertTrue(out["data"]["entities_section"])
        self.assertGreater(out["data"]["size_bytes"], 0)

    def test_outside_root_and_bad_extension_refused(self) -> None:
        with Harness(FakeFM(), path="p") as h:
            for bad in ("../escape.dxf", str(self.root.parent / "other.dxf"), "flat.step"):
                self.assertFalse(sm.export_flat_pattern({"path": bad})["ok"], bad)
        self.assertEqual(h.doc.calls, [])

    def test_empty_file_is_failure(self) -> None:
        with Harness(FakeFM(), path="p") as h:
            h.doc.export_writes = None
            with mock.patch.object(sm, "safe", lambda obj, member, default=None: obj.path):
                out = sm.export_flat_pattern({"path": "none.dxf"})
        self.assertFalse(out["ok"])

    def test_file_without_entities_is_failure(self) -> None:
        with Harness(FakeFM(), path="p") as h:
            h.doc.export_writes = b"junk"
            with mock.patch.object(sm, "safe", lambda obj, member, default=None: obj.path):
                self.assertFalse(sm.export_flat_pattern({"path": "junk.dxf"})["ok"])

    def test_unsaved_part_and_non_sheet_metal_refused(self) -> None:
        with Harness(FakeFM(), path="") as h:
            with mock.patch.object(sm, "safe", lambda obj, member, default=None: obj.path):
                self.assertFalse(sm.export_flat_pattern({"path": "a.dxf"})["ok"])
        with Harness(FakeFM(), flat=False, path="p") as h:
            self.assertFalse(sm.export_flat_pattern({"path": "b.dxf"})["ok"])
        self.assertEqual(h.doc.calls, [])

    def test_existing_file_needs_overwrite(self) -> None:
        (self.root / "e.dxf").write_bytes(b"x")
        with Harness(FakeFM(), path="p") as h:
            self.assertFalse(sm.export_flat_pattern({"path": "e.dxf"})["ok"])
        self.assertEqual(h.doc.calls, [])


if __name__ == "__main__":
    unittest.main()
