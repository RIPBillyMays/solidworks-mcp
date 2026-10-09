# Offline tests for the Phase 4 fixes and fences (fork additions).
#
# No SOLIDWORKS is needed or touched: COM objects are replaced with fakes.
#
#     .venv\Scripts\python.exe -m unittest discover -s tests -v

from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.types import Tool

from solidworks_mcp import sw2017_fences, sw_assembly, sw_core, sw_feature, sw_file


def _tool(name: str, description: str = "does a thing") -> Tool:
    return Tool(name=name, description=description, inputSchema={"type": "object", "properties": {}})


class FenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = [_tool("auto_dimension_view", "Auto-dimension a view."), _tool("other")]
        self.handlers: dict[str, Any] = {
            "auto_dimension_view": lambda a: sw_core.result(True, "should never run"),
            "other": lambda a: sw_core.result(True, "fine"),
        }
        self.env = unittest.mock.patch.dict(os.environ)
        self.env.start()
        os.environ.pop("SW_MCP_DISABLE_FENCES", None)

    def tearDown(self) -> None:
        self.env.stop()

    def test_fenced_handler_is_not_ok_and_flagged(self) -> None:
        sw2017_fences.apply_fences(self.tools, self.handlers)
        payload = self.handlers["auto_dimension_view"]({})
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["data"]["fenced"])
        self.assertIn("Not supported on SOLIDWORKS 2017", payload["message"])

    def test_description_prefixed_and_unfenced_tool_untouched(self) -> None:
        sw2017_fences.apply_fences(self.tools, self.handlers)
        fenced = next(t for t in self.tools if t.name == "auto_dimension_view")
        self.assertTrue(fenced.description.startswith("NOT SUPPORTED ON SOLIDWORKS 2017"))
        self.assertEqual(next(t for t in self.tools if t.name == "other").description, "does a thing")
        self.assertTrue(self.handlers["other"]({})["ok"])

    def test_apply_is_idempotent(self) -> None:
        sw2017_fences.apply_fences(self.tools, self.handlers)
        once = self.tools[0].description
        sw2017_fences.apply_fences(self.tools, self.handlers)
        self.assertEqual(self.tools[0].description, once)

    def test_unknown_tool_name_raises_keyerror(self) -> None:
        with unittest.mock.patch.dict(sw2017_fences.FENCES, {"no_such_tool": "reason"}):
            with self.assertRaises(KeyError):
                sw2017_fences.apply_fences(self.tools, self.handlers)

    def test_env_var_skips_fences(self) -> None:
        os.environ["SW_MCP_DISABLE_FENCES"] = "1"
        sw2017_fences.apply_fences(self.tools, self.handlers)
        self.assertTrue(self.handlers["auto_dimension_view"]({})["ok"])
        self.assertEqual(self.tools[0].description, "Auto-dimension a view.")

    def test_every_fence_names_a_registered_tool(self) -> None:
        import solidworks_mcp.server  # noqa: F401 - registers all tools and applies fences

        names = {t.name for t in sw_core.TOOLS}
        self.assertLessEqual(set(sw2017_fences.FENCES), names)
        fenced = next(t for t in sw_core.TOOLS if t.name == "auto_dimension_view")
        self.assertTrue(fenced.description.startswith("NOT SUPPORTED ON SOLIDWORKS 2017"))
        self.assertTrue(sw_core.HANDLERS["auto_dimension_view"]({})["data"]["fenced"])


class FakeFeatureManager:
    """Records InsertFeatureChamfer / InsertRib calls."""

    def __init__(self) -> None:
        self.chamfer_calls: list[tuple[Any, ...]] = []
        self.rib_calls: list[tuple[Any, ...]] = []

    def InsertFeatureChamfer(self, *args: Any) -> Any:
        self.chamfer_calls.append(args)
        return object()

    def InsertRib(self, *args: Any) -> None:
        self.rib_calls.append(args)


def _feature_result(doc: Any, feature: Any, action: str, **data: Any) -> dict[str, Any]:
    return sw_core.result(feature is not None, f"Created {action}." if feature else f"No {action}.", **data)


class ChamferSubstitutionTests(unittest.TestCase):
    def run_chamfer(self, **args: Any) -> tuple[dict[str, Any], FakeFeatureManager]:
        fm = FakeFeatureManager()
        patches = unittest.mock.patch.multiple(
            sw_feature,
            require_part=lambda: (None, object()),
            exit_active_sketch=lambda doc: None,
            require_selection=lambda doc, spec: 1,
            feature_manager=lambda doc: fm,
            rename_feature=lambda feature, name: None,
            feature_result=_feature_result,
        )
        with patches:
            payload = sw_feature.chamfer({"distance_mm": 2, "selection": {}, **args})
        return payload, fm

    def test_equal_distance_becomes_angle_distance_45(self) -> None:
        payload, fm = self.run_chamfer()
        options, ctype, distance, angle, other = fm.chamfer_calls[0][:5]
        self.assertEqual(ctype, sw_core.CHAMFER_ANGLE_DISTANCE)
        self.assertAlmostEqual(distance, 0.002)
        self.assertAlmostEqual(angle, math.radians(45))
        self.assertEqual(payload["data"]["substituted"], "angle_distance 45°")

    def test_equal_distance_ignores_a_stray_angle(self) -> None:
        _, fm = self.run_chamfer(mode="equal_distance", angle_deg=10)
        self.assertAlmostEqual(fm.chamfer_calls[0][3], math.radians(45))

    def test_angle_distance_is_untouched(self) -> None:
        payload, fm = self.run_chamfer(mode="angle_distance", angle_deg=30)
        self.assertEqual(fm.chamfer_calls[0][1], sw_core.CHAMFER_ANGLE_DISTANCE)
        self.assertAlmostEqual(fm.chamfer_calls[0][3], math.radians(30))
        self.assertNotIn("substituted", payload.get("data", {}))

    def test_distance_distance_is_untouched(self) -> None:
        payload, fm = self.run_chamfer(mode="distance_distance", other_distance_mm=3)
        self.assertEqual(fm.chamfer_calls[0][1], sw_core.CHAMFER_DISTANCE_DISTANCE)
        self.assertNotIn("substituted", payload.get("data", {}))


class RibRetryTests(unittest.TestCase):
    def run_rib(self, succeed_on: int | None, **args: Any) -> tuple[dict[str, Any], FakeFeatureManager]:
        """Rib 'builds' on the Nth InsertRib call (1-based); None means never."""
        fm = FakeFeatureManager()

        def created_after(doc: Any, before: list[str]) -> Any:
            return object() if succeed_on is not None and len(fm.rib_calls) >= succeed_on else None

        patches = unittest.mock.patch.multiple(
            sw_feature,
            require_part=lambda: (None, object()),
            select_sketch_for_feature=lambda doc, name: "Sketch1",
            feature_manager=lambda doc: fm,
            _feature_names=lambda doc: [],
            _feature_created_after=created_after,
            rename_feature=lambda feature, name: None,
            feature_result=_feature_result,
        )
        with patches:
            payload = sw_feature.rib({"thickness_mm": 2, **args})
        return payload, fm

    @staticmethod
    def flags(call: tuple[Any, ...]) -> tuple[bool, bool]:
        """(normal_to_sketch, reverse_material) of one InsertRib call."""
        return call[8], call[4]

    def test_first_try_success_does_not_retry(self) -> None:
        payload, fm = self.run_rib(1)
        self.assertEqual(len(fm.rib_calls), 1)
        self.assertNotIn("retried", payload["data"])

    def test_material_side_flip_is_tried(self) -> None:
        # Phase 3 case: only reverse_material=True works with the default direction.
        payload, fm = self.run_rib(3)
        self.assertEqual([self.flags(c) for c in fm.rib_calls], [(False, False), (True, False), (False, True)])
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["data"]["reverse_material"])
        self.assertEqual(payload["data"]["extrude_direction"], "parallel_to_sketch")
        self.assertTrue(payload["data"]["retried"])

    def test_all_four_combinations_then_stop(self) -> None:
        payload, fm = self.run_rib(None)
        self.assertEqual(
            {self.flags(c) for c in fm.rib_calls}, {(False, False), (True, False), (False, True), (True, True)}
        )
        self.assertEqual(len(fm.rib_calls), 4)
        self.assertFalse(payload["ok"])

    def test_combinations_start_from_requested_settings(self) -> None:
        _, fm = self.run_rib(None, extrude_direction="normal_to_sketch", reverse_material=True)
        self.assertEqual(self.flags(fm.rib_calls[0]), (True, True))
        self.assertEqual(len({self.flags(c) for c in fm.rib_calls}), 4)


class FakeMathUtility:
    def __init__(self) -> None:
        self.created: list[list[float]] = []

    def CreateTransform(self, data: Any) -> str:
        self.created.append(list(data))
        return "transform"


class FakeComponent:
    def __init__(self) -> None:
        self.solved: list[Any] = []

    Name2 = "Part-1"

    def SetTransformAndSolve2(self, transform: Any) -> bool:
        self.solved.append(transform)
        return True


IDENTITY_AT = lambda x, y, z: [1, 0, 0, 0, 1, 0, 0, 0, 1, x, y, z, 1.0, 0, 0, 0]  # noqa: E731


class InsertComponentTests(unittest.TestCase):
    def test_corrective_matrix_math(self) -> None:
        shifted = sw_assembly.corrective_matrix(IDENTITY_AT(-0.010, -0.005, -0.0025), [0.0, 0.0, 0.0])
        self.assertEqual(shifted[9:12], [0.0, 0.0, 0.0])
        self.assertEqual(shifted[:9], [1, 0, 0, 0, 1, 0, 0, 0, 1])
        self.assertEqual(shifted[12], 1.0)

    def test_corrective_matrix_none_when_already_there(self) -> None:
        self.assertIsNone(sw_assembly.corrective_matrix(IDENTITY_AT(0.1, 0.0, 0.02), [0.1, 0.0, 0.02]))

    def run_insert(self, placed_origin: tuple[float, float, float], **args: Any) -> tuple[dict[str, Any], FakeComponent, FakeMathUtility]:
        component, math_utility = FakeComponent(), FakeMathUtility()

        class FakeDoc:
            def AddComponent5(self, *a: Any) -> FakeComponent:
                return component

        class FakeApp:
            GetMathUtility = math_utility

            def OpenDoc6(self, *a: Any) -> None:
                return None

        transforms = [IDENTITY_AT(*placed_origin)]

        def comp_transform(c: Any) -> list[float]:
            # After SetTransformAndSolve2 the origin sits at the corrected translation.
            if math_utility.created:
                return math_utility.created[-1]
            return transforms[0]

        with tempfile.TemporaryDirectory() as tmp:
            part = Path(tmp) / "block.sldprt"
            part.write_bytes(b"x")
            patches = unittest.mock.patch.multiple(
                sw_assembly,
                require_assembly=lambda: (FakeApp(), FakeDoc()),
                component_transform=comp_transform,
                flag_methods=lambda obj, *names: obj,
                double_array=lambda values: list(values),
                rebuild=lambda doc: True,
                byref_long=lambda n=0: object(),
            )
            with patches:
                payload = sw_assembly.insert_component({"path": str(part), **args})
        return payload, component, math_utility

    def test_origin_is_moved_to_requested_point(self) -> None:
        # Phase 3 measurement: asked for (0,0,0), origin landed at (-10,-5,-2.5) mm.
        payload, component, mu = self.run_insert((-0.010, -0.005, -0.0025))
        self.assertEqual(mu.created[0][9:12], [0.0, 0.0, 0.0])
        self.assertEqual(component.solved, ["transform"])
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["data"]["origin_corrected"])
        self.assertEqual(payload["data"]["origin_mm"], [0.0, 0.0, 0.0])

    def test_target_is_in_metres_from_mm_arguments(self) -> None:
        _, _, mu = self.run_insert((0.0, 0.0, 0.0), x_mm=100, z_mm=20)
        self.assertEqual(mu.created[0][9:12], [0.1, 0.0, 0.02])

    def test_no_correction_when_origin_already_right(self) -> None:
        payload, component, mu = self.run_insert((0.0, 0.0, 0.0))
        self.assertEqual(mu.created, [])
        self.assertEqual(component.solved, [])
        self.assertNotIn("origin_corrected", payload["data"])


class FakeExtension:
    """SaveAs writes the file, then reports a warning code like 2017 does for .3mf."""

    def __init__(self, path_to_write: Path | None, returned: bool, errors: int, warnings: int) -> None:
        self.path_to_write, self.returned, self.errors, self.warnings = path_to_write, returned, errors, warnings

    def SaveAs(self, path: str, version: int, options: int, export_data: Any, errors: Any, warnings: Any) -> bool:
        if self.path_to_write is not None:
            self.path_to_write.write_bytes(b"3mf-bytes")
        errors.value, warnings.value = self.errors, self.warnings
        return self.returned


class FakeSaveDoc:
    GetPathName = ""

    def SaveAs(self, path: str) -> bool:  # ModelDoc2 fallback: always fails in these tests
        return False


class ExportWarningTests(unittest.TestCase):
    def run_export(self, returned: bool, errors: int, warnings: int, write: bool = True) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "t.3mf"
            ext = FakeExtension(out if write else None, returned, errors, warnings)
            patches = unittest.mock.patch.multiple(
                sw_file,
                active_document=lambda: (None, FakeSaveDoc()),
                validated_output_path=lambda p, exts, ow=False: out,
                clear_selection=lambda doc: None,
                extension=lambda doc: ext,
            )
            with patches:
                return sw_file.export_document({"path": str(out)})

    def test_warning_code_with_written_file_is_success(self) -> None:
        payload = self.run_export(returned=False, errors=0, warnings=1)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["warnings"], 1)
        self.assertEqual(payload["data"]["errors"], 0)

    def test_error_code_is_failure_even_if_file_exists(self) -> None:
        self.assertFalse(self.run_export(returned=False, errors=2, warnings=0)["ok"])

    def test_no_file_is_failure(self) -> None:
        self.assertFalse(self.run_export(returned=True, errors=0, warnings=0, write=False)["ok"])

    def test_plain_success(self) -> None:
        payload = self.run_export(returned=True, errors=0, warnings=0)
        self.assertTrue(payload["ok"])
        self.assertNotIn("warning code", payload["message"])


class Benign3mfErrorTests(unittest.TestCase):
    """2017 returns swGenericSaveError (1) on every .3mf export yet writes a valid file."""

    def _write(self, name: str, data: bytes) -> Path:
        folder = Path(tempfile.mkdtemp())
        path = folder / name
        path.write_bytes(data)
        return path

    def test_generic_error_on_zip_3mf_is_benign(self) -> None:
        self.assertTrue(sw_file._benign_3mf_error(self._write("a.3mf", b"PKrest"), 1))

    def test_other_error_codes_are_not_benign(self) -> None:
        self.assertFalse(sw_file._benign_3mf_error(self._write("a.3mf", b"PKrest"), 2))

    def test_non_zip_3mf_is_not_benign(self) -> None:
        self.assertFalse(sw_file._benign_3mf_error(self._write("a.3mf", b"garbage"), 1))

    def test_other_formats_are_not_benign(self) -> None:
        self.assertFalse(sw_file._benign_3mf_error(self._write("a.step", b"PKrest"), 1))

    def test_missing_file_is_not_benign(self) -> None:
        self.assertFalse(sw_file._benign_3mf_error(Path(tempfile.mkdtemp()) / "none.3mf", 1))


if __name__ == "__main__":
    unittest.main()
