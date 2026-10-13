# Offline tests for Batch A export: plan_export, preference scoping, export_document options,
# export_bodies, export_components, list_export_formats.  COM objects are fakes.

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

from solidworks_mcp import sw_core, sw_export, sw_file

ENUMS = {}
for _line in (ROOT / "tools" / "compat" / "sw2017_enums.txt").read_text(encoding="utf-8").splitlines():
    if "=" in _line:
        _name, _num = _line.strip().rsplit("=", 1)
        ENUMS[_name] = int(_num)


class FakeApp:
    def __init__(self) -> None:
        self.ints = {75: 214, 78: 2, 211: 0, 212: 0, 384: 1}
        self.doubles = {2: 0.001, 3: 0.5}
        self.toggles = {69: True, 71: False, 72: True, 246: False}
        self.log: list[tuple[str, int, Any]] = []
        self.pdf_data = type("PdfData", (), {})()

    def GetUserPreferenceIntegerValue(self, p: int) -> int:
        return self.ints[p]

    def SetUserPreferenceIntegerValue(self, p: int, v: int) -> bool:
        self.log.append(("int", p, v))
        self.ints[p] = v
        return True

    def GetUserPreferenceDoubleValue(self, p: int) -> float:
        return self.doubles[p]

    def SetUserPreferenceDoubleValue(self, p: int, v: float) -> bool:
        self.log.append(("double", p, v))
        self.doubles[p] = v
        return True

    def GetUserPreferenceToggle(self, p: int) -> bool:
        return self.toggles[p]

    def SetUserPreferenceToggle(self, p: int, v: bool) -> bool:
        self.log.append(("toggle", p, v))
        self.toggles[p] = v
        return True

    def GetExportFileData(self, kind: int) -> Any:
        return self.pdf_data


class FakeExt:
    def __init__(self, doc: "FakeDoc") -> None:
        self.doc = doc

    def SaveAs(self, path: str, version: int, options: int, data: Any, errors: Any, warnings: Any) -> bool:
        if self.doc.fail:
            errors.value = 1
            return False
        Path(path).write_bytes(b"data")
        self.doc.saved.append((path, data))
        self.doc.seen_config.append(self.doc.config)
        return True


class FakeCfg:
    def __init__(self, name: str) -> None:
        self.Name = name


class FakeDoc:
    GetPathName = ""

    def __init__(self, doc_type: int = 1, fail: bool = False) -> None:
        self.GetType = doc_type
        self.fail = fail
        self.saved: list[tuple[str, Any]] = []
        self.seen_config: list[str] = []
        self.config = "Default"
        self.Extension = FakeExt(self)
        self.GetConfigurationNames = ["Default", "Long"]
        self.shown: list[str] = []

    @property
    def GetActiveConfiguration(self) -> FakeCfg:
        return FakeCfg(self.config)

    def ShowConfiguration2(self, name: str) -> bool:
        self.shown.append(name)
        self.config = name
        return True

    def SaveAs(self, path: str) -> bool:
        return False


class FakeBody:
    def __init__(self, name: str, write: bool = True) -> None:
        self.Name, self.write = name, write

    def Save(self, path: str) -> bool:
        if self.write:
            Path(path).write_bytes(b"x_t")
        return self.write


class FakeComponent:
    def __init__(self, name: str, path: str, model: Any, suppressed: bool = False) -> None:
        self.Name2, self.GetPathName, self.IsSuppressed = name, path, suppressed
        self.GetModelDoc2 = model


def patched(root: Path, app: Any, doc: Any, **extra: Any) -> Any:
    stack = unittest.mock.patch.multiple(
        sw_file,
        OUTPUT_ROOT=root,
        active_document=lambda: (app, doc),
        require_part=lambda: (app, doc),
        extension=lambda d: d.Extension,
        clear_selection=lambda d: None,
        **extra,
    )
    return stack


class PlanTests(unittest.TestCase):
    def test_enum_ids_match_2017_typelib(self) -> None:
        pairs = {
            sw_export.PREF_STEP_AP: "swUserPreferenceIntegerValue_e.swStepAP",
            sw_export.PREF_STL_QUALITY: "swUserPreferenceIntegerValue_e.swSTLQuality",
            sw_export.PREF_STL_UNITS: "swUserPreferenceIntegerValue_e.swExportStlUnits",
            sw_export.PREF_VRML_UNITS: "swUserPreferenceIntegerValue_e.swExportVrmlUnits",
            sw_export.PREF_VRML_VERSION: "swUserPreferenceIntegerValue_e.swExportVrmlVersion",
            sw_export.PREF_STL_DEVIATION: "swUserPreferenceDoubleValue_e.swSTLDeviation",
            sw_export.PREF_STL_ANGLE: "swUserPreferenceDoubleValue_e.swSTLAngleTolerance",
            sw_export.TOGGLE_STL_BINARY: "swUserPreferenceToggle_e.swSTLBinaryFormat",
            sw_export.TOGGLE_STL_DONT_TRANSLATE: "swUserPreferenceToggle_e.swSTLDontTranslateToPositive",
            sw_export.TOGGLE_STL_ONE_FILE: "swUserPreferenceToggle_e.swSTLComponentsIntoOneFile",
            sw_export.TOGGLE_VRML_ONE_FILE: "swUserPreferenceToggle_e.swExportVrmlAllComponentsInSingleFile",
        }
        for value, name in pairs.items():
            self.assertEqual(ENUMS[name], value, name)
        for key, name in (("coarse", "Coarse"), ("fine", "Fine"), ("custom", "Custom")):
            self.assertEqual(ENUMS[f"swSTLQuality_e.swSTLQuality_{name}"], sw_export.STL_QUALITY[key])
        self.assertEqual(ENUMS["swLengthUnit_e.swMM"], sw_export.LENGTH_UNITS["mm"])
        self.assertEqual(ENUMS["swLengthUnit_e.swINCHES"], sw_export.LENGTH_UNITS["in"])
        self.assertEqual(ENUMS["swVrmlOutputVersion_e.swVrmlOutputVersion_97"], sw_export.VRML_VERSION["97"])

    def test_step_versions(self) -> None:
        plan = sw_export.plan_export(".step", {"step_version": "ap203"}, 1)
        self.assertEqual(plan.int_prefs, [(75, 203)])
        with self.assertRaises(ValueError):
            sw_export.plan_export(".step", {"step_version": "AP242"}, 1)
        with self.assertRaises(ValueError):
            sw_export.plan_export(".iges", {"step_version": "AP203"}, 1)

    def test_stl_custom_implies_quality(self) -> None:
        plan = sw_export.plan_export(".stl", {"deviation_mm": 0.1, "angle_deg": 10, "stl_format": "ascii", "units": "in"}, 1)
        self.assertIn((78, 3), plan.int_prefs)
        self.assertIn((211, 3), plan.int_prefs)
        self.assertIn((69, False), plan.toggle_prefs)
        self.assertAlmostEqual(plan.double_prefs[0][1], 0.0001)
        with self.assertRaises(ValueError):
            sw_export.plan_export(".stl", {"stl_quality": "fine", "deviation_mm": 0.1}, 1)

    def test_units_rejected_where_unverified(self) -> None:
        with self.assertRaises(ValueError):
            sw_export.plan_export(".step", {"units": "in"}, 1)

    def test_document_type_rules(self) -> None:
        with self.assertRaises(ValueError):
            sw_export.plan_export(".easm", {}, 1)
        with self.assertRaises(ValueError):
            sw_export.plan_export(".stl", {}, 3)
        with self.assertRaises(ValueError):
            sw_export.plan_export(".obj", {}, 1)
        self.assertTrue(sw_export.plan_export(".pdf", {}, 1).pdf_3d)
        self.assertFalse(sw_export.plan_export(".pdf", {}, 3).pdf_3d)

    def test_every_documented_format_is_allowed(self) -> None:
        for ext in (".step", ".iges", ".x_t", ".x_b", ".stl", ".3mf", ".wrl", ".eprt", ".easm", ".sat", ".pdf", ".png", ".jpg", ".tif", ".bmp"):
            self.assertIn(ext, sw_export.EXPORT_FILE_EXTENSIONS)


class ExportDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()

    def test_legacy_call_unchanged(self) -> None:
        doc = FakeDoc()
        with patched(self.root, None, doc):
            out = sw_file.export_document({"path": "a.step"})
        self.assertTrue(out["ok"])
        self.assertNotIn("preferences_applied", out["data"])

    def test_stl_prefs_set_and_restored(self) -> None:
        app, doc = FakeApp(), FakeDoc()
        before = (dict(app.ints), dict(app.doubles), dict(app.toggles))
        with patched(self.root, app, doc):
            out = sw_file.export_document({"path": "a.stl", "stl_format": "ascii", "stl_quality": "fine", "units": "in"})
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["data"]["preferences_restored"])
        self.assertEqual((app.ints, app.doubles, app.toggles), before)
        self.assertIn(("toggle", 69, False), app.log)
        self.assertIn(("int", 211, 3), app.log)

    def test_prefs_restored_when_save_fails(self) -> None:
        app, doc = FakeApp(), FakeDoc(fail=True)
        with patched(self.root, app, doc):
            out = sw_file.export_document({"path": "a.step", "step_version": "AP203"})
        self.assertFalse(out["ok"])
        self.assertEqual(app.ints[75], 214)

    def test_configuration_switched_and_restored(self) -> None:
        app, doc = FakeApp(), FakeDoc()
        with patched(self.root, app, doc):
            out = sw_file.export_document({"path": "a.step", "configuration": "long"})
        self.assertTrue(out["ok"])
        self.assertEqual(doc.seen_config, ["Long"])
        self.assertEqual(doc.config, "Default")

    def test_unknown_configuration_raises(self) -> None:
        with patched(self.root, FakeApp(), FakeDoc()):
            with self.assertRaises(RuntimeError):
                sw_file.export_document({"path": "a.step", "configuration": "nope"})

    def test_bad_option_is_a_clean_failure(self) -> None:
        with patched(self.root, FakeApp(), FakeDoc()):
            out = sw_file.export_document({"path": "a.step", "stl_format": "ascii"})
        self.assertFalse(out["ok"])
        self.assertFalse((self.root / "a.step").exists())

    def test_pdf_3d_passes_export_data(self) -> None:
        app, doc = FakeApp(), FakeDoc()
        with patched(self.root, app, doc):
            out = sw_file.export_document({"path": "a.pdf"})
        self.assertTrue(out["ok"], out)
        self.assertIs(doc.saved[0][1], app.pdf_data)
        self.assertTrue(app.pdf_data.ExportAs3D)

    def test_outside_root_refused(self) -> None:
        with patched(self.root, FakeApp(), FakeDoc()):
            with self.assertRaises(RuntimeError):
                sw_file.export_document({"path": str(self.root.parent / "evil.step")})

    def test_new_formats_accepted(self) -> None:
        doc = FakeDoc(2)
        for name in ("a.wrl", "a.easm", "a.sat", "a.tif", "a.x_b"):
            with patched(self.root, FakeApp(), doc):
                self.assertTrue(sw_file.export_document({"path": name})["ok"], name)


class ExportBodiesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.picked: list[str] = []

    def patch(self, bodies: list[Any], doc: Any | None = None, pick: bool = True) -> Any:
        def select(d: Any, name: str, kind: str, mark: int = 0, append: bool = False, ext: Any = None) -> bool:
            self.picked.append(f"{kind}:{name}")
            return pick

        return patched(self.root, FakeApp(), doc or FakeDoc(), get_bodies=lambda d: bodies, select_by_id=select)

    def test_one_file_per_body_selects_each_solid_body(self) -> None:
        bodies = [FakeBody("Boss-Extrude1"), FakeBody("Boss/Extrude2"), FakeBody("Boss-Extrude1")]
        with self.patch(bodies):
            out = sw_file.export_bodies({"directory": "parts"})
        self.assertTrue(out["ok"], out)
        files = sorted(p.name for p in (self.root / "parts").iterdir())
        self.assertEqual(len(files), 3)
        self.assertIn("Boss_Extrude2.x_t", files)
        self.assertEqual(self.picked, ["SOLIDBODY:Boss-Extrude1", "SOLIDBODY:Boss/Extrude2", "SOLIDBODY:Boss-Extrude1"])

    def test_other_per_body_formats_and_options(self) -> None:
        with self.patch([FakeBody("A")]):
            out = sw_file.export_bodies({"directory": "p", "format": "step", "step_version": "AP214"})
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["data"]["preferences_restored"])
        self.assertTrue((self.root / "p" / "A.step").exists())

    def test_filter_and_unknown_name(self) -> None:
        with self.patch([FakeBody("A"), FakeBody("B")]):
            out = sw_file.export_bodies({"directory": "p", "body_names": ["b"]})
            bad = sw_file.export_bodies({"directory": "p", "body_names": ["zzz"]})
        self.assertEqual([e["body"] for e in out["data"]["exported"]], ["B"])
        self.assertFalse(bad["ok"])

    def test_unsupported_format_selection_and_save_failure(self) -> None:
        with self.patch([FakeBody("A")]):
            self.assertFalse(sw_file.export_bodies({"directory": "p", "format": "3mf"})["ok"])
        with self.patch([FakeBody("A")], pick=False):
            self.assertFalse(sw_file.export_bodies({"directory": "p"})["ok"])
        with self.patch([FakeBody("A")], doc=FakeDoc(fail=True)):
            self.assertFalse(sw_file.export_bodies({"directory": "p"})["ok"])

    def test_directory_outside_root_refused(self) -> None:
        with self.patch([FakeBody("A")]):
            with self.assertRaises(RuntimeError):
                sw_file.export_bodies({"directory": str(self.root.parent / "elsewhere")})


class ExportComponentsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()

    def run_tool(self, comps: list[FakeComponent], app: Any = None, **args: Any) -> dict[str, Any]:
        asm = FakeDoc(2)
        with patched(self.root, app or FakeApp(), asm, iter_components=lambda d, top=True: comps):
            return sw_file.export_components({"directory": "out", **args})

    def test_dedup_skip_and_export(self) -> None:
        part_a, part_b = FakeDoc(1), FakeDoc(1)
        comps = [
            FakeComponent("a-1", "C:/x/a.sldprt", part_a),
            FakeComponent("a-2", "C:/x/a.sldprt", part_a),
            FakeComponent("b-1", "C:/x/b.sldprt", part_b),
            FakeComponent("c-1", "C:/x/c.sldprt", None),
            FakeComponent("d-1", "C:/x/d.sldprt", FakeDoc(1), suppressed=True),
        ]
        out = self.run_tool(comps, format="stl", stl_format="binary")
        self.assertTrue(out["ok"], out)
        self.assertEqual(sorted(p.name for p in (self.root / "out").iterdir()), ["a.stl", "b.stl"])
        reasons = {s["component"]: s["reason"] for s in out["data"]["skipped"]}
        self.assertEqual(set(reasons), {"c-1", "d-1"})
        self.assertTrue(out["data"]["preferences_restored"])

    def test_assembly_component_skipped_for_part_only_format(self) -> None:
        out = self.run_tool([FakeComponent("s", "C:/x/s.sldasm", FakeDoc(2)), FakeComponent("p", "C:/x/p.sldprt", FakeDoc(1))], format="eprt")
        self.assertEqual([e["component"] for e in out["data"]["exported"]], ["p"])
        self.assertEqual(out["data"]["skipped"][0]["component"], "s")

    def test_rejections(self) -> None:
        self.assertFalse(self.run_tool([], format="pdf")["ok"])
        self.assertFalse(self.run_tool([], format="obj")["ok"])
        self.assertFalse(self.run_tool([], configuration="x")["ok"])
        self.assertFalse(self.run_tool([])["ok"])

    def test_requires_assembly(self) -> None:
        with patched(self.root, FakeApp(), FakeDoc(1)):
            self.assertFalse(sw_file.export_components({"directory": "o"})["ok"])


class RegistrationTests(unittest.TestCase):
    def test_tools_registered_once(self) -> None:
        names = [t.name for t in sw_core.TOOLS]
        for name in ("export_document", "export_bodies", "export_components", "list_export_formats"):
            self.assertEqual(names.count(name), 1, name)

    def test_list_export_formats(self) -> None:
        out = sw_file.list_export_formats({})
        self.assertTrue(out["ok"])
        exts = {f["extension"] for f in out["data"]["formats"]}
        self.assertTrue({".step", ".stl", ".wrl", ".easm", ".pdf", ".tif"} <= exts)
        self.assertIn(".obj", out["data"]["unsupported"])


if __name__ == "__main__":
    unittest.main()
