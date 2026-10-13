# Offline regression tests for the defects found by the live Batch A run on SOLIDWORKS 2017.
# Each test pins a behaviour that was verified against the real application; no COM is touched.

from __future__ import annotations

import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solidworks_mcp import sw_assembly, sw_export, sw_feature, sw_file, sw_select  # noqa: E402


class CoupledStlApp:
    """Mimics 2017: quality 1/2 rewrite the doubles; quality 3 can only be entered via a double."""

    def __init__(self, quality: int, deviation: float, angle: float) -> None:
        self.q, self.dev, self.ang = quality, deviation, angle
        self.ints = {211: 0}

    def GetUserPreferenceIntegerValue(self, p: int) -> int:
        return self.q if p == sw_export.PREF_STL_QUALITY else self.ints[p]

    def SetUserPreferenceIntegerValue(self, p: int, v: int) -> bool:
        if p == sw_export.PREF_STL_QUALITY:
            if v == 1:
                self.q, self.dev, self.ang = 1, 0.0006, 0.52
            elif v == 2:
                self.q, self.dev, self.ang = 2, 0.0002, 0.17
            # 3 (custom) is ignored, as on the real application
        else:
            self.ints[p] = v
        return True

    def GetUserPreferenceDoubleValue(self, p: int) -> float:
        return self.dev if p == sw_export.PREF_STL_DEVIATION else self.ang

    def SetUserPreferenceDoubleValue(self, p: int, v: float) -> bool:
        self.q = 3
        if p == sw_export.PREF_STL_DEVIATION:
            self.dev = v
        else:
            self.ang = v
        return True

    def GetUserPreferenceToggle(self, p: int) -> bool:
        return False

    def SetUserPreferenceToggle(self, p: int, v: bool) -> bool:
        return True


class StlQualityRestoreTests(unittest.TestCase):
    def roundtrip(self, app: CoupledStlApp, args: dict[str, Any]) -> None:
        plan = sw_export.plan_export(".stl", args, 1)
        scope = sw_export.PreferenceScope(app)
        scope.apply(plan)
        self.assertEqual(scope.restore(), [])

    def test_custom_quality_user_survives_coarse_export(self) -> None:
        app = CoupledStlApp(3, 2.86e-05, 0.1745)
        self.roundtrip(app, {"stl_quality": "coarse"})
        self.assertEqual((app.q, app.dev, app.ang), (3, 2.86e-05, 0.1745))

    def test_custom_quality_user_survives_custom_export(self) -> None:
        app = CoupledStlApp(3, 2.86e-05, 0.1745)
        self.roundtrip(app, {"deviation_mm": 0.005, "angle_deg": 5})
        self.assertEqual((app.q, app.dev, app.ang), (3, 2.86e-05, 0.1745))

    def test_preset_user_gets_preset_back(self) -> None:
        app = CoupledStlApp(2, 0.0002, 0.17)
        self.roundtrip(app, {"deviation_mm": 0.005})
        self.assertEqual(app.q, 2)

    def test_vrml_aliases_match_header_semantics(self) -> None:
        # Live: 1 writes "#VRML V2.0 utf8", 2 writes "#VRML V1.0 ascii".
        self.assertEqual(sw_export.VRML_VERSION["97"], 1)
        self.assertEqual(sw_export.VRML_VERSION["01"], 2)
        self.assertNotIn("2001", sw_export.VRML_VERSION)


class BmpTests(unittest.TestCase):
    def test_bmp_uses_save_bmp_not_save_as(self) -> None:
        class Doc:
            GetPathName = ""

            def __init__(self) -> None:
                self.calls: list[tuple] = []

            def SaveBMP(self, path: str, w: int, h: int) -> bool:
                self.calls.append((path, w, h))
                Path(path).write_bytes(b"BM")
                return True

        doc = Doc()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "x.bmp"
            self.assertTrue(sw_file._save_as(doc, str(target)))
        self.assertEqual(doc.calls[0][1:], (1280, 720))


class WidthMarkTests(unittest.TestCase):
    def test_tab_mark_is_sent_as_16(self) -> None:
        seen: list[int] = []

        def pick(doc: Any, spec: dict[str, Any], append: bool) -> str:
            seen.append(spec.get("mark", 0))
            return "x"

        doc = type("Doc", (), {"AddMate5": lambda self, *a: None})()
        with unittest.mock.patch.object(sw_assembly, "require_assembly", return_value=(None, doc)), \
                unittest.mock.patch.object(sw_assembly, "clear_selection"), \
                unittest.mock.patch.object(sw_assembly, "rebuild"), \
                unittest.mock.patch.object(sw_assembly, "mate_features", return_value=[]), \
                unittest.mock.patch.object(sw_assembly, "_select_mate_entity", side_effect=pick):
            sw_assembly.add_mate({"mate_type": "width", "entities": [
                {"component": "a", "face": 0, "mark": 1}, {"component": "a", "face": 1, "mark": 1},
                {"component": "b", "face": 0, "mark": 2}, {"component": "b", "face": 1, "mark": 2}]})
            self.assertEqual(seen, [1, 1, 16, 16])
            seen.clear()
            sw_assembly.add_mate({"mate_type": "coincident", "entities": [
                {"component": "a", "face": 0, "mark": 2}, {"component": "b", "face": 0}]})
            self.assertEqual(seen, [2, 0])  # only width mates remap


class ThinTypeTests(unittest.TestCase):
    def values(self, thin: dict[str, Any]) -> tuple[Any, ...]:
        return sw_feature._ExtrudePlan({"thin": thin}).thin_values()

    def test_thin_type_codes(self) -> None:
        # swThinWallType_e travels in the RevThinDir argument: 0 one, 1 opposite, 2 mid-plane, 3 two.
        self.assertEqual(self.values({"thickness_mm": 2})[3], 0)
        self.assertEqual(self.values({"thickness_mm": 2, "reverse": True})[3], 1)
        mid = self.values({"thickness_mm": 2, "type": "mid_plane"})
        self.assertEqual((mid[0], mid[1], mid[3]), (0.002, 0.0, 2))
        two = self.values({"thickness_mm": 2, "type": "two_directions", "thickness2_mm": 1})
        self.assertEqual((two[0], two[1], two[3]), (0.002, 0.001, 3))


class RedoFenceTests(unittest.TestCase):
    def test_redo_is_fenced(self) -> None:
        from solidworks_mcp import sw2017_fences

        self.assertIn("redo", sw2017_fences.FENCES)
        self.assertTrue(callable(sw_select.redo))


if __name__ == "__main__":
    unittest.main()
