# Copyright 2026 JIALE LIU (upstream); fork additions for SOLIDWORKS 2017 support.
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

"""Offline check that the numeric constants in the server match the 2017 enums.

SOLIDWORKS takes enum arguments as plain longs, so a wrong number is not a
type error: it silently selects a different option (or none).  This test pins
every enum-backed constant in ``solidworks_mcp/*.py`` to the value that the
installed 2017 ``swconst.tlb`` declares, as dumped into
``tools/compat/sw2017_enums.txt`` by ``tools/compat/dump_sw_tlb.py``.

Part 2 (``Phase2Claim*``) settles the tool catalog's unverified section-5
claims (PLAN task 2.6).  Where the code is confirmed WRONG the test asserts the
correct 2017 value.  All six confirmed bugs were fixed by implementer C, so
none of these tests is an ``expectedFailure`` any more.  Evidence and the fix
for each are in ``docs/reports/phase2-static-compat.md``.

Inline literals (not importable constants) are read from the source with
``ast`` so the test follows the code rather than a copy of it.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solidworks_mcp import sw_assembly, sw_core, sw_drawing, sw_file, sw_inspect, sw_sketch  # noqa: E402

PACKAGE_DIR = ROOT / "solidworks_mcp"
ENUMS_FILE = ROOT / "tools" / "compat" / "sw2017_enums.txt"


# ---------------------------------------------------------------------------
# 2017 enum data.
# ---------------------------------------------------------------------------


def load_enums() -> dict[str, dict[str, int]]:
    enums: dict[str, dict[str, int]] = {}
    for line in ENUMS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        ref, _, number = line.rpartition("=")
        enum_name, _, member = ref.partition(".")
        enums.setdefault(enum_name, {})[member] = int(number)
    return enums


ENUMS = load_enums()


def ev(ref: str) -> int:
    """2017 value of ``enumName.memberName``; KeyError if the 2017 enum lacks it."""
    enum_name, _, member = ref.partition(".")
    return ENUMS[enum_name][member]


# ---------------------------------------------------------------------------
# Source readers for inline literals.
# ---------------------------------------------------------------------------


def _function(module_file: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((PACKAGE_DIR / module_file).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{module_file} has no function {name}()")


def _assigned(func: ast.FunctionDef, var: str) -> ast.AST:
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == var for t in node.targets):
            return node.value
    raise AssertionError(f"{func.name}() does not assign {var}")


def _const(node: ast.AST) -> Any:
    return ast.literal_eval(node)


def _first_dict(func: ast.FunctionDef) -> dict[Any, Any]:
    # Body only: the @tool(...) decorator's JSON-schema dicts also hang off the FunctionDef.
    for node in (n for stmt in func.body for n in ast.walk(stmt)):
        if isinstance(node, ast.Dict):
            try:
                return ast.literal_eval(node)
            except ValueError:
                continue  # a dict built from expressions, not a literal table
    raise AssertionError(f"{func.name}() contains no dict literal")


def _calls(func: ast.FunctionDef, attr: str) -> list[ast.Call]:
    return [
        n for n in ast.walk(func)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr
    ]


# ---------------------------------------------------------------------------
# Part 1: every enum-backed constant matches 2017.
# ---------------------------------------------------------------------------

# name-keyed tables: {python key: "enum.member"} -- the value in the code must equal the enum value.
NAME_KEYED = {
    "sw_core.END_CONDITIONS": (sw_core.END_CONDITIONS, {
        "blind": "swEndConditions_e.swEndCondBlind",
        "through_all": "swEndConditions_e.swEndCondThroughAll",
        "through_next": "swEndConditions_e.swEndCondThroughNext",
        "up_to_vertex": "swEndConditions_e.swEndCondUpToVertex",
        "up_to_surface": "swEndConditions_e.swEndCondUpToSurface",
        "offset_from_surface": "swEndConditions_e.swEndCondOffsetFromSurface",
        "mid_plane": "swEndConditions_e.swEndCondMidPlane",
        "up_to_body": "swEndConditions_e.swEndCondUpToBody",
        "through_all_both": "swEndConditions_e.swEndCondThroughAllBoth",
    }),
    "sw_core.MATE_TYPES": (sw_core.MATE_TYPES, {
        "coincident": "swMateType_e.swMateCOINCIDENT", "concentric": "swMateType_e.swMateCONCENTRIC",
        "perpendicular": "swMateType_e.swMatePERPENDICULAR", "parallel": "swMateType_e.swMatePARALLEL",
        "tangent": "swMateType_e.swMateTANGENT", "distance": "swMateType_e.swMateDISTANCE",
        "angle": "swMateType_e.swMateANGLE", "symmetric": "swMateType_e.swMateSYMMETRIC",
        "width": "swMateType_e.swMateWIDTH", "lock": "swMateType_e.swMateLOCK",
        "slot": "swMateType_e.swMateSLOT", "profile_center": "swMateType_e.swMatePROFILECENTER",
    }),
    "sw_core.MATE_ALIGNMENTS": (sw_core.MATE_ALIGNMENTS, {
        "aligned": "swMateAlign_e.swMateAlignALIGNED", "anti_aligned": "swMateAlign_e.swMateAlignANTI_ALIGNED",
        "closest": "swMateAlign_e.swMateAlignCLOSEST",
    }),
    "sw_core.TRIM_CHOICES": (sw_core.TRIM_CHOICES, {
        "closest": "swSketchTrimChoice_e.swSketchTrimClosest", "corner": "swSketchTrimChoice_e.swSketchTrimCorner",
        "two_entities": "swSketchTrimChoice_e.swSketchTrimTwoEntities",
        "entity_point": "swSketchTrimChoice_e.swSketchTrimEntityPoint",
        "entities": "swSketchTrimChoice_e.swSketchTrimEntities", "outside": "swSketchTrimChoice_e.swSketchTrimOutside",
        "inside": "swSketchTrimChoice_e.swSketchTrimInside",
    }),
    "sw_inspect.NAMED_VIEWS": (sw_inspect.NAMED_VIEWS, {
        "front": "swStandardViews_e.swFrontView", "back": "swStandardViews_e.swBackView",
        "left": "swStandardViews_e.swLeftView", "right": "swStandardViews_e.swRightView",
        "top": "swStandardViews_e.swTopView", "bottom": "swStandardViews_e.swBottomView",
        "isometric": "swStandardViews_e.swIsometricView", "trimetric": "swStandardViews_e.swTrimetricView",
        "dimetric": "swStandardViews_e.swDimetricView",
    }),
    "sw_sketch.RELATIONS": (sw_sketch.RELATIONS, {
        "horizontal": "swConstraintType_e.swConstraintType_HORIZONTAL",
        "vertical": "swConstraintType_e.swConstraintType_VERTICAL",
        "tangent": "swConstraintType_e.swConstraintType_TANGENT",
        "parallel": "swConstraintType_e.swConstraintType_PARALLEL",
        "perpendicular": "swConstraintType_e.swConstraintType_PERPENDICULAR",
        "coincident": "swConstraintType_e.swConstraintType_COINCIDENT",
        "concentric": "swConstraintType_e.swConstraintType_CONCENTRIC",
        "symmetric": "swConstraintType_e.swConstraintType_SYMMETRIC",
        "midpoint": "swConstraintType_e.swConstraintType_ATMIDDLE",
        "intersection": "swConstraintType_e.swConstraintType_ATINTERSECT",
        "equal": "swConstraintType_e.swConstraintType_SAMELENGTH",
        "fixed": "swConstraintType_e.swConstraintType_FIXED",
        "collinear": "swConstraintType_e.swConstraintType_COLINEAR",
        "coradial": "swConstraintType_e.swConstraintType_CORADIAL",
    }),
    "sw_drawing.PAPER_SIZES": (sw_drawing.PAPER_SIZES, {
        "A": "swDwgPaperSizes_e.swDwgPaperAsize", "A_portrait": "swDwgPaperSizes_e.swDwgPaperAsizeVertical",
        "B": "swDwgPaperSizes_e.swDwgPaperBsize", "C": "swDwgPaperSizes_e.swDwgPaperCsize",
        "D": "swDwgPaperSizes_e.swDwgPaperDsize", "E": "swDwgPaperSizes_e.swDwgPaperEsize",
        "A4": "swDwgPaperSizes_e.swDwgPaperA4size", "A4_portrait": "swDwgPaperSizes_e.swDwgPaperA4sizeVertical",
        "A3": "swDwgPaperSizes_e.swDwgPaperA3size", "A2": "swDwgPaperSizes_e.swDwgPaperA2size",
        "A1": "swDwgPaperSizes_e.swDwgPaperA1size", "A0": "swDwgPaperSizes_e.swDwgPaperA0size",
        "custom": "swDwgPaperSizes_e.swDwgPapersUserDefined",
    }),
    "sw_drawing.ANNOTATION_TYPES": (sw_drawing.ANNOTATION_TYPES, {
        "marked_for_drawing": "swInsertAnnotation_e.swInsertDimensionsMarkedForDrawing",
        "not_marked_for_drawing": "swInsertAnnotation_e.swInsertDimensionsNotMarkedForDrawing",
        "hole_callouts": "swInsertAnnotation_e.swInsertholeCallout",
        "hole_wizard_profile": "swInsertAnnotation_e.swInsertHoleWizardProfileDimensions",
        "hole_wizard_location": "swInsertAnnotation_e.swInsertHoleWizardLocationDimensions",
        "notes": "swInsertAnnotation_e.swInsertNotes",
        "geometric_tolerances": "swInsertAnnotation_e.swInsertGTols",
        "datums": "swInsertAnnotation_e.swInsertDatums",
        "surface_finish": "swInsertAnnotation_e.swInsertSFSymbols",
        "cosmetic_threads": "swInsertAnnotation_e.swInsertCThreads",
        "axes": "swInsertAnnotation_e.swInsertAxes",
        "toleranced_dimensions": "swInsertAnnotation_e.swInsertTolerancedDims",
    }),
    "sw_drawing.AUTODIM_SCHEMES": (sw_drawing.AUTODIM_SCHEMES, {
        "baseline": "swAutodimScheme_e.swAutodimSchemeBaseline", "ordinate": "swAutodimScheme_e.swAutodimSchemeOrdinate",
        "chain": "swAutodimScheme_e.swAutodimSchemeChain", "centerline": "swAutodimScheme_e.swAutodimSchemeCenterline",
    }),
    "sw_drawing.AUTODIM_ENTITIES": (sw_drawing.AUTODIM_ENTITIES, {
        "all": "swAutodimEntities_e.swAutodimEntitiesAll", "selected": "swAutodimEntities_e.swAutodimEntitiesSelected",
        "preselected": "swAutodimEntities_e.swAutodimEntitiesBasedOnPreselect",
    }),
    "sw_drawing.HORIZONTAL_PLACEMENT": (sw_drawing.HORIZONTAL_PLACEMENT, {
        "below": "swAutodimHorizontalPlacement_e.swAutodimHorizontalPlacementBelow",
        "above": "swAutodimHorizontalPlacement_e.swAutodimHorizontalPlacementAbove",
    }),
    "sw_drawing.VERTICAL_PLACEMENT": (sw_drawing.VERTICAL_PLACEMENT, {
        "left": "swAutodimVerticalPlacement_e.swAutodimVerticalPlacementLeft",
        "right": "swAutodimVerticalPlacement_e.swAutodimVerticalPlacementRight",
    }),
    "sw_drawing.CENTER_MARK_STYLES": (sw_drawing.CENTER_MARK_STYLES, {
        "single": "swCenterMarkStyle_e.swCenterMark_Single", "linear": "swCenterMarkStyle_e.swCenterMark_LinearGroup",
        "circular": "swCenterMarkStyle_e.swCenterMark_CircularGroup",
    }),
}

# value-keyed tables: the dict's KEYS are the enum numbers, the values are labels.
VALUE_KEYED = {
    "sw_core.DOC_TYPES": (sw_core.DOC_TYPES, {
        0: "swDocumentTypes_e.swDocNONE", 1: "swDocumentTypes_e.swDocPART",
        2: "swDocumentTypes_e.swDocASSEMBLY", 3: "swDocumentTypes_e.swDocDRAWING",
    }),
    "sw_core.SURFACE_TYPES": (sw_core.SURFACE_TYPES, {
        4001: "swSurfaceTypes_e.PLANE_TYPE", 4002: "swSurfaceTypes_e.CYLINDER_TYPE", 4003: "swSurfaceTypes_e.CONE_TYPE",
        4004: "swSurfaceTypes_e.SPHERE_TYPE", 4005: "swSurfaceTypes_e.TORUS_TYPE", 4006: "swSurfaceTypes_e.BSURF_TYPE",
        4007: "swSurfaceTypes_e.BLEND_TYPE", 4008: "swSurfaceTypes_e.OFFSET_TYPE", 4009: "swSurfaceTypes_e.EXTRU_TYPE",
        4010: "swSurfaceTypes_e.SREV_TYPE",
    }),
    "sw_core.CURVE_TYPES": (sw_core.CURVE_TYPES, {
        3001: "swCurveTypes_e.LINE_TYPE", 3002: "swCurveTypes_e.CIRCLE_TYPE", 3003: "swCurveTypes_e.ELLIPSE_TYPE",
        3004: "swCurveTypes_e.INTERSECTION_TYPE", 3005: "swCurveTypes_e.BCURVE_TYPE", 3006: "swCurveTypes_e.SPCURVE_TYPE",
        3008: "swCurveTypes_e.CONSTPARAM_TYPE", 3009: "swCurveTypes_e.TRIMMED_TYPE",
    }),
    "sw_assembly.ADD_MATE_ERRORS": (sw_assembly.ADD_MATE_ERRORS, {
        0: "swAddMateError_e.swAddMateError_ErrorUknown", 1: "swAddMateError_e.swAddMateError_NoError",
        2: "swAddMateError_e.swAddMateError_IncorrectMateType", 3: "swAddMateError_e.swAddMateError_IncorrectAlignment",
        4: "swAddMateError_e.swAddMateError_IncorrectSelections", 5: "swAddMateError_e.swAddMateError_OverDefinedAssembly",
        6: "swAddMateError_e.swAddMateError_IncorrectGearRatios",
    }),
    "sw_drawing.VIEW_TYPES": (sw_drawing.VIEW_TYPES, {
        1: "swDrawingViewTypes_e.swDrawingSheet", 2: "swDrawingViewTypes_e.swDrawingSectionView",
        3: "swDrawingViewTypes_e.swDrawingDetailView", 4: "swDrawingViewTypes_e.swDrawingProjectedView",
        5: "swDrawingViewTypes_e.swDrawingAuxiliaryView", 6: "swDrawingViewTypes_e.swDrawingStandardView",
        7: "swDrawingViewTypes_e.swDrawingNamedView", 8: "swDrawingViewTypes_e.swDrawingRelativeView",
        9: "swDrawingViewTypes_e.swDrawingDetachedView", 10: "swDrawingViewTypes_e.swDrawingAlternatePositionView",
    }),
}

# scalar constants: {"module.NAME": (value, "enum.member")}
SCALARS = {
    "sw_file._SW_GENERIC_SAVE_ERROR": (sw_file._SW_GENERIC_SAVE_ERROR, "swFileSaveError_e.swGenericSaveError"),
    "sw_core.BODY_SOLID": (sw_core.BODY_SOLID, "swBodyType_e.swSolidBody"),
    "sw_core.BODY_SHEET": (sw_core.BODY_SHEET, "swBodyType_e.swSheetBody"),
    "sw_core.BODY_ALL": (sw_core.BODY_ALL, "swBodyType_e.swAllBodies"),
    "sw_core.FILLET_TYPE_SIMPLE": (sw_core.FILLET_TYPE_SIMPLE, "swFeatureFilletType_e.swFeatureFilletType_Simple"),
    "sw_core.FILLET_PROPAGATE": (sw_core.FILLET_PROPAGATE, "swFeatureFilletOptions_e.swFeatureFilletPropagate"),
    "sw_core.FILLET_UNIFORM_RADIUS": (sw_core.FILLET_UNIFORM_RADIUS, "swFeatureFilletOptions_e.swFeatureFilletUniformRadius"),
    "sw_core.FILLET_KEEP_FEATURES": (sw_core.FILLET_KEEP_FEATURES, "swFeatureFilletOptions_e.swFeatureFilletKeepFeatures"),
    "sw_core.CHAMFER_ANGLE_DISTANCE": (sw_core.CHAMFER_ANGLE_DISTANCE, "swChamferType_e.swChamferAngleDistance"),
    "sw_core.CHAMFER_DISTANCE_DISTANCE": (sw_core.CHAMFER_DISTANCE_DISTANCE, "swChamferType_e.swChamferDistanceDistance"),
    "sw_core.CHAMFER_EQUAL_DISTANCE": (sw_core.CHAMFER_EQUAL_DISTANCE, "swChamferType_e.swChamferEqualDistance"),
    "sw_core.CHAMFER_TANGENT_PROPAGATION": (sw_core.CHAMFER_TANGENT_PROPAGATION, "swFeatureChamferOption_e.swFeatureChamferTangentPropagation"),
    "sw_core.PLANE_PARALLEL": (sw_core.PLANE_PARALLEL, "swRefPlaneReferenceConstraints_e.swRefPlaneReferenceConstraint_Parallel"),
    "sw_core.PLANE_PERPENDICULAR": (sw_core.PLANE_PERPENDICULAR, "swRefPlaneReferenceConstraints_e.swRefPlaneReferenceConstraint_Perpendicular"),
    "sw_core.PLANE_COINCIDENT": (sw_core.PLANE_COINCIDENT, "swRefPlaneReferenceConstraints_e.swRefPlaneReferenceConstraint_Coincident"),
    "sw_core.PLANE_DISTANCE": (sw_core.PLANE_DISTANCE, "swRefPlaneReferenceConstraints_e.swRefPlaneReferenceConstraint_Distance"),
    "sw_core.PLANE_ANGLE": (sw_core.PLANE_ANGLE, "swRefPlaneReferenceConstraints_e.swRefPlaneReferenceConstraint_Angle"),
    "sw_core.PLANE_MIDPLANE": (sw_core.PLANE_MIDPLANE, "swRefPlaneReferenceConstraints_e.swRefPlaneReferenceConstraint_MidPlane"),
    "sw_core.PLANE_FLIP": (sw_core.PLANE_FLIP, "swRefPlaneReferenceConstraints_e.swRefPlaneReferenceConstraint_OptionFlip"),
    "sw_core.SW_INPUT_DIM_VAL_ON_CREATE": (sw_core.SW_INPUT_DIM_VAL_ON_CREATE, "swUserPreferenceToggle_e.swInputDimValOnCreate"),
    "sw_file.SW_DEFAULT_TEMPLATE_PART": (sw_file.SW_DEFAULT_TEMPLATE_PART, "swUserPreferenceStringValue_e.swDefaultTemplatePart"),
    "sw_file.SW_DEFAULT_TEMPLATE_ASSEMBLY": (sw_file.SW_DEFAULT_TEMPLATE_ASSEMBLY, "swUserPreferenceStringValue_e.swDefaultTemplateAssembly"),
    "sw_file.SW_DEFAULT_TEMPLATE_DRAWING": (sw_file.SW_DEFAULT_TEMPLATE_DRAWING, "swUserPreferenceStringValue_e.swDefaultTemplateDrawing"),
}

# Module-level constants that are deliberately NOT enum-backed (or are verified elsewhere
# in this file); the coverage test below fails on any new numeric table not listed here
# or above, so a fresh enum table cannot slip in unchecked.
VERIFIED_ELSEWHERE = {
    "sw_drawing.DISPLAY_MODES": "Phase2ClaimTests.test_display_mode_values_match_swDisplayMode_e (CONFIRMED wrong)",
    "sw_sketch._DIMENSION_METHODS": "member names, not numbers (test_sw2017_api_compat)",
}
NOT_ENUM = {
    "sw_sketch.DIMENSION_DIRECTIONS": "defined but unused; no SOLIDWORKS call consumes it",
    "sw_core.SELECT_TYPE_FACE": "SelectByID2 type string, not a number",
    "sw_core.SELECT_TYPE_EDGE": "SelectByID2 type string",
    "sw_core.SELECT_TYPE_VERTEX": "SelectByID2 type string",
    "sw_core.EXPORT_EXTENSIONS": "file suffixes",
    "sw_core.TEMPLATE_SUFFIXES": "file suffixes",
    "sw_sketch.RELATION_NAMES": "inverse of RELATIONS (checked via RELATIONS)",
    "sw_sketch._XY": "JSON schema fragment",
    "sw_sketch.ANNOTATION_TYPES.dimensions": "composite, checked in test_annotation_dimensions_is_the_union",
}


class EnumTableTests(unittest.TestCase):
    def test_enum_snapshot_looks_right(self) -> None:
        self.assertGreater(len(ENUMS), 400)
        self.assertEqual(0, ev("swEndConditions_e.swEndCondBlind"))
        self.assertEqual(6, ev("swEndConditions_e.swEndCondMidPlane"))

    def test_name_keyed_tables_match_2017(self) -> None:
        for label, (actual, expected) in NAME_KEYED.items():
            with self.subTest(table=label):
                missing = set(actual) - set(expected)
                if label == "sw_drawing.ANNOTATION_TYPES":
                    missing.discard("dimensions")  # composite flag, own test
                self.assertEqual(set(), missing, f"{label} has keys this test does not map to a 2017 enum member")
                for key, ref in expected.items():
                    self.assertIn(key, actual, f"{label} lost key {key!r}")
                    self.assertEqual(ev(ref), actual[key], f"{label}[{key!r}] should be {ref} = {ev(ref)}")

    def test_value_keyed_tables_match_2017(self) -> None:
        for label, (actual, expected) in VALUE_KEYED.items():
            with self.subTest(table=label):
                self.assertEqual(set(expected), set(actual), f"{label} keys differ from the enum members mapped here")
                for number, ref in expected.items():
                    self.assertEqual(number, ev(ref), f"{label}: {ref} is {ev(ref)} in 2017, table says {number}")

    def test_scalar_constants_match_2017(self) -> None:
        for label, (actual, ref) in SCALARS.items():
            with self.subTest(constant=label):
                self.assertEqual(ev(ref), actual, f"{label} should be {ref} = {ev(ref)}")

    def test_annotation_dimensions_is_the_union(self) -> None:
        expected = (
            ev("swInsertAnnotation_e.swInsertDimensions")
            | ev("swInsertAnnotation_e.swInsertDimensionsMarkedForDrawing")
            | ev("swInsertAnnotation_e.swInsertDimensionsNotMarkedForDrawing")
        )
        self.assertEqual(expected, sw_drawing.ANNOTATION_TYPES["dimensions"])

    def test_inline_sketch_segment_types_match_2017(self) -> None:
        mapping = _first_dict(_function("sw_core.py", "enumerate_sketch_segments"))
        expected = {
            ev("swSketchSegments_e.swSketchLINE"): "line", ev("swSketchSegments_e.swSketchARC"): "arc",
            ev("swSketchSegments_e.swSketchELLIPSE"): "ellipse", ev("swSketchSegments_e.swSketchSPLINE"): "spline",
            ev("swSketchSegments_e.swSketchTEXT"): "text", ev("swSketchSegments_e.swSketchPARABOLA"): "parabola",
        }
        self.assertEqual(expected, mapping)

    def test_inline_constrained_status_matches_2017(self) -> None:
        mapping = _first_dict(_function("sw_sketch.py", "_sketch_status"))
        expected = {
            ev("swConstrainedStatus_e.swUnknownConstraint"): "unknown",
            ev("swConstrainedStatus_e.swUnderConstrained"): "under_defined",
            ev("swConstrainedStatus_e.swFullyConstrained"): "fully_defined",
            ev("swConstrainedStatus_e.swOverConstrained"): "over_defined",
            ev("swConstrainedStatus_e.swNoSolution"): "no_solution",
            ev("swConstrainedStatus_e.swInvalidSolution"): "invalid_solution",
            ev("swConstrainedStatus_e.swAutosolveOff"): "autosolve_off",
        }
        self.assertEqual(expected, mapping)

    def test_set_system_value_scope_is_all_configurations(self) -> None:
        # sw_sketch.py passes the literal 2 to SetSystemValue3 (catalog item 24).
        source = (PACKAGE_DIR / "sw_sketch.py").read_text(encoding="utf-8")
        self.assertIn("SetSystemValue3(", source)
        self.assertEqual(2, ev("swSetValueInConfiguration_e.swSetValue_InAllConfigurations"))

    def test_all_module_level_numeric_tables_are_covered(self) -> None:
        covered = (
            set(NAME_KEYED) | set(VALUE_KEYED) | set(SCALARS) | set(VERIFIED_ELSEWHERE) | set(NOT_ENUM)
        )
        uncovered = []
        for path in sorted(PACKAGE_DIR.glob("*.py")):
            module = path.stem
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                    continue
                target = node.targets[0]
                if not isinstance(target, ast.Name) or not target.id.lstrip("_").replace("_", "").isupper():
                    continue
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    continue
                numeric = isinstance(value, int) or (
                    isinstance(value, dict) and any(
                        isinstance(k, int) or isinstance(v, int) for k, v in value.items()
                    )
                )
                if numeric and f"{module}.{target.id}" not in covered:
                    uncovered.append(f"{module}.{target.id}")
        self.assertEqual(
            [], uncovered,
            "New numeric constants/tables with no 2017 enum check -- add them to NAME_KEYED / "
            "VALUE_KEYED / SCALARS (or NOT_ENUM with a reason) in tests/test_sw2017_enums.py",
        )


# ---------------------------------------------------------------------------
# Part 2: PLAN 2.6 / tool-catalog section 5 claims.  Evidence: 2017 swconst.tlb
# (sw2017_enums.txt) and sldworksapi.chm / swconst.chm parameter text.
# ---------------------------------------------------------------------------


class Phase2ClaimTests(unittest.TestCase):
    # --- item 8: revolve mid-plane ----------------------------------------
    def test_2017_facts_for_revolve(self) -> None:
        # FeatureRevolve2.Dir1Type is "as defined in swEndConditions_e" (sldworksapi.chm);
        # swRevolveType_e is a different enum used by IRevolveFeatureData2.
        self.assertEqual(6, ev("swEndConditions_e.swEndCondMidPlane"))
        self.assertEqual(4, ev("swEndConditions_e.swEndCondUpToSurface"))

    def test_revolve_mid_plane_uses_swEndCondMidPlane(self) -> None:
        # CONFIRMED (catalog item 8): sw_feature.py revolve() passes 4 for mid_plane, which in
        # swEndConditions_e is swEndCondUpToSurface; mid plane is 6.  See
        # docs/reports/phase2-static-compat.md.  Fix: `direction_type = 6 if mid_plane else 0`.
        expr = _assigned(_function("sw_feature.py", "revolve"), "direction_type")
        self.assertIsInstance(expr, ast.IfExp)
        self.assertEqual(ev("swEndConditions_e.swEndCondMidPlane"), _const(expr.body))
        self.assertEqual(ev("swEndConditions_e.swEndCondBlind"), _const(expr.orelse))

    # --- section view options (item 6) ------------------------------------
    def test_section_view_options_flags(self) -> None:
        # CONFIRMED (catalog item 6): `options = 1 | (2 if exclude_fasteners else 0)`.  In
        # swCreateSectionViewAtOptions_e 1 = NotAligned (the section would NOT snap to its parent;
        # wrong default) and 2 = OffsetSection (not ExcludeFasteners, which is 64).
        # Fix: `options = 0 | (64 if exclude_fasteners else 0)`.
        expr = _assigned(_function("sw_drawing.py", "insert_section_view"), "options")
        self.assertIsInstance(expr, ast.BinOp)
        base = _const(expr.left)
        self.assertNotEqual(ev("swCreateSectionViewAtOptions_e.swCreateSectionView_NotAligned"), base)
        self.assertIsInstance(expr.right, ast.IfExp)
        self.assertEqual(
            ev("swCreateSectionViewAtOptions_e.swCreateSectionView_ExcludeFasteners"), _const(expr.right.body)
        )

    def test_2017_facts_for_section_view(self) -> None:
        e = "swCreateSectionViewAtOptions_e.swCreateSectionView_"
        self.assertEqual((1, 2, 64, 16), (ev(e + "NotAligned"), ev(e + "OffsetSection"), ev(e + "ExcludeFasteners"), ev(e + "Partial")))

    # --- item 7: detail view Style / Showtype -----------------------------
    @staticmethod
    def _detail_args() -> list[ast.AST]:
        value = _assigned(_function("sw_drawing.py", "insert_detail_view"), "detail_args")
        assert isinstance(value, ast.Tuple)
        return value.elts

    def test_detail_view_style_is_leader(self) -> None:
        # CONFIRMED (catalog item 7): CreateDetailViewAt4(X, Y, Z, Style, Scale1, Scale2, LabelIn,
        # Showtype, ...).  Style (4th) is swDetViewStyle_e; the code passes 1 = swDetViewBROKEN
        # (its comment calls 1 "circle profile", an enum that does not exist in 2017).
        # The comment on the 8th argument shows the intent: leader = swDetViewLEADER (2).
        self.assertEqual(ev("swDetViewStyle_e.swDetViewLEADER"), _const(self._detail_args()[3]))

    def test_detail_view_showtype_is_circle(self) -> None:
        # CONFIRMED (catalog item 7): Showtype (8th) is swDetCircleShowType_e; the code passes
        # 2 = swDetCircleDONTSHOW.  The tool draws a sketch circle for the detail, so the intended
        # value is swDetCircleCIRCLE (1).  Net fix: swap the two literals (4th -> 2, 8th -> 1).
        self.assertEqual(ev("swDetCircleShowType_e.swDetCircleCIRCLE"), _const(self._detail_args()[7]))

    # --- item 4: drawing display mode ------------------------------------
    def test_display_mode_values_match_swDisplayMode_e(self) -> None:
        # CONFIRMED (catalog item 4): IView.SetDisplayMode3's Mode is swDisplayMode_e (wireframe 0,
        # hidden-greyed/HLV 1, hidden/HLR 2, shaded 3), but DISPLAY_MODES holds swViewDisplayMode_e
        # numbers (1..5).  Only hidden_lines_removed (2) is right, by coincidence.
        expected = {
            "wireframe": ev("swDisplayMode_e.swWIREFRAME"),
            "hidden_lines_grey": ev("swDisplayMode_e.swHIDDEN_GREYED"),
            "hidden_lines_removed": ev("swDisplayMode_e.swHIDDEN"),
            "shaded": ev("swDisplayMode_e.swSHADED"),
            "shaded_with_edges": ev("swDisplayMode_e.swSHADED"),  # plus Edges=True
        }
        self.assertEqual(expected, sw_drawing.DISPLAY_MODES)

    def test_shaded_with_edges_sets_the_edges_argument(self) -> None:
        # CONFIRMED (catalog item 4): per the help, shaded-with-edges is Mode=swSHADED with
        # Edges=True (4th argument of SetDisplayMode3); _apply_view_options always passes False.
        calls = _calls(_function("sw_drawing.py", "_apply_view_options"), "SetDisplayMode3")
        self.assertEqual(1, len(calls))
        edges_arg = calls[0].args[3]
        self.assertFalse(isinstance(edges_arg, ast.Constant) and edges_arg.value is False,
                         "Edges is hard-coded False, so shaded_with_edges can never show edges")

    def test_2017_facts_for_display_mode(self) -> None:
        self.assertEqual(5, ev("swViewDisplayMode_e.swViewDisplayMode_ShadedWithEdges"))
        self.assertEqual(7, ev("swDisplayMode_e.swSHADED_EDGES"))

    # --- DeleteSelection2 options (item 11) -------------------------------
    def test_delete_selection_option_zero_is_legal(self) -> None:
        # REFUTED as an enum mismatch: DeleteSelection2(0) is a valid (empty) swDeleteSelectionOptions_e
        # combination.  What 0 does NOT do is include children (swDelete_Children = 1), whereas the
        # delete_feature description promises "anything that depends on them" -- a behavioural
        # question for the Phase 3 live run, not an enum bug.
        calls = _calls(_function("sw_feature.py", "delete_feature"), "DeleteSelection2")
        self.assertEqual(1, len(calls))
        self.assertEqual(0, _const(calls[0].args[0]))
        flags = [ev("swDeleteSelectionOptions_e." + n) for n in ("swDelete_Children", "swDelete_Absorbed", "swDelete_Advanced")]
        self.assertEqual([1, 2, 4], flags)

    # --- ViewDisplayShadedwithedges (item 2) ------------------------------
    def test_2017_facts_for_view_display_shaded_with_edges(self) -> None:
        members = (ROOT / "tools" / "compat" / "sw2017_api_members.txt").read_text(encoding="utf-8").splitlines()
        shaded = [m for m in members if m.lower().endswith(".viewdisplayshadedwithedges")]
        self.assertEqual([], shaded, "2017 unexpectedly has ViewDisplayShadedwithedges; re-evaluate item 2")
        self.assertIn("IModelDoc2.ActiveView", members)
        self.assertIn("IModelView.DisplayMode", members)

    def test_set_view_does_not_call_missing_ViewDisplayShadedwithedges(self) -> None:
        # CONFIRMED (catalog item 2): ModelDoc2.ViewDisplayShadedwithedges does not exist in 2017
        # (only ViewDisplayShaded does), so set_view's shaded_with_edges is a silent no-op behind a
        # bare `except: pass`; the comment "4 = shaded with edges" is also wrong (4 is Shaded, 5 is
        # ShadedWithEdges).  Fix: `doc.ActiveView.DisplayMode = 5` (IModelView.DisplayMode, swViewDisplayMode_e).
        func = _function("sw_inspect.py", "set_view")
        attrs = {n.attr for n in ast.walk(func) if isinstance(n, ast.Attribute)}
        self.assertNotIn("ViewDisplayShadedwithedges", attrs)

    # --- TangentEdgeDisplay (item 5) --------------------------------------
    def test_2017_facts_for_tangent_edges(self) -> None:
        self.assertEqual(
            (0, 1, 2),
            (ev("swDisplayTangentEdges_e.swTangentEdgesHidden"),
             ev("swDisplayTangentEdges_e.swTangentEdgesVisibleAndFonted"),
             ev("swDisplayTangentEdges_e.swTangentEdgesVisible")),
        )

    def test_tangent_edge_mapping_matches_swDisplayTangentEdges_e(self) -> None:
        # CONFIRMED (catalog item 5): `target.TangentEdgeDisplay = mode` assigns a property that is
        # not on IView in 2017 (silent no-op); the correct call is IView.SetDisplayTangentEdges2(mode)
        # with swDisplayTangentEdges_e (hidden 0, visible-and-fonted/phantom 1, visible 2), whereas the
        # code's map is visible 1 / hidden 2 / phantom 3.
        mapping = _first_dict(_function("sw_drawing.py", "set_drawing_view"))
        self.assertEqual(
            {
                "visible": ev("swDisplayTangentEdges_e.swTangentEdgesVisible"),
                "hidden": ev("swDisplayTangentEdges_e.swTangentEdgesHidden"),
                "phantom": ev("swDisplayTangentEdges_e.swTangentEdgesVisibleAndFonted"),
            },
            mapping,
        )


if __name__ == "__main__":
    unittest.main()
