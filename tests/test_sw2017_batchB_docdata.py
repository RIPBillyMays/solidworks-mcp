# Offline tests for batch B document-data tools (sw_docdata.py).
# COM objects are fakes; no SOLIDWORKS is touched.

from __future__ import annotations

import sys
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solidworks_mcp import sw_core, sw_docdata as dd  # noqa: E402

ENUMS_FILE = ROOT / "tools" / "compat" / "sw2017_enums.txt"


def enum_value(qualified: str) -> int:
    for line in ENUMS_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(qualified + "="):
            return int(line.split("=")[1])
    raise KeyError(qualified)


class FakeCfg:
    def __init__(self, name: str, parent: "FakeCfg | None" = None) -> None:
        self.Name, self.Description, self.Comment, self.AlternateName = name, "", "", ""
        self._parent = parent
        self.IsDerived = parent is not None

    def GetParent(self) -> Any:
        return self._parent


class FakeConfigManager:
    def __init__(self, doc: "FakeDoc") -> None:
        self.doc = doc
        self.calls: list[tuple] = []

    def _FlagAsMethod(self, *n: str) -> None:
        pass

    def AddConfiguration(self, *a: Any) -> Any:
        self.calls.append(a)
        parent = self.doc.cfgs[a[4]]
        return self.doc._add(a[0], parent, a[3])


class FakeMassProp:
    def __init__(self, doc: "FakeDoc") -> None:
        self.doc = doc
        self.UserAssigned = False

    @property
    def Mass(self) -> float:
        return self.doc.mass_by_cfg[self.doc.active] if self.doc.override is None else self.doc.override

    Volume = property(lambda self: 1e-6)
    SurfaceArea = property(lambda self: 6e-4)
    CenterOfMass = property(lambda self: (0.0, 0.0, 0.005))

    @property
    def OverrideMass(self) -> float:
        return 0.0

    @OverrideMass.setter
    def OverrideMass(self, v: float) -> None:
        if self.doc.persist_override:
            self.doc.override = v if v else None


class FakeExt:
    def __init__(self, doc: "FakeDoc") -> None:
        self.doc = doc

    def _FlagAsMethod(self, *n: str) -> None:
        pass

    def CustomPropertyManager(self, cfg: str) -> Any:
        return self.doc.props.setdefault(cfg, FakeProps())

    @property
    def CreateMassProperty(self) -> Any:
        return FakeMassProp(self.doc)


class FakeProps:
    TYPES = {30: 30, 3: 3, 5: 5, 64: 64, 11: 11}

    def __init__(self) -> None:
        self.data: dict[str, tuple[int, str]] = {}

    def _FlagAsMethod(self, *n: str) -> None:
        pass

    def GetNames(self) -> tuple:
        return tuple(self.data) or None

    def Add3(self, name: str, kind: int, val: str, opt: int) -> int:
        self.data[name] = (kind, val)
        return 0

    def Delete2(self, name: str) -> int:
        return 0 if self.data.pop(name, None) is not None else 1

    def GetType2(self, name: str) -> int:
        return self.data[name][0]

    def Get4(self, name: str, cached: bool, raw: Any, resolved: Any) -> int:
        kind, val = self.data[name]
        raw.value = val
        resolved.value = val.replace("$PRP", "R")
        return 2


class FakeEq:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, float]] = []
        self.Status = 0
        self.evaluated = 0
        self.add_calls: list[tuple] = []
        self.set_calls: list[tuple] = []

    def _FlagAsMethod(self, *n: str) -> None:
        pass

    def GetCount(self) -> int:
        return len(self.rows)

    def Equation(self, i: int) -> str:
        return self.rows[i][0]

    def Value(self, i: int) -> float:
        return self.rows[i][2]

    def GlobalVariable(self, i: int) -> bool:
        return self.rows[i][1]

    def EvaluateAll(self) -> int:
        self.evaluated += 1
        return 0

    def Add3(self, index: int, text: str, solve: bool, opt: int, names: Any) -> int:
        self.add_calls.append((index, text, opt, names))
        self.rows.append((text, text.startswith('"') and "@" not in text, 1.0))
        return len(self.rows) - 1

    def SetEquationAndConfigurationOption(self, i: int, text: str, opt: int, names: Any) -> int:
        self.set_calls.append((i, text, opt))
        self.rows[i] = (text, self.rows[i][1], 2.0)
        return 0

    def Delete(self, i: int) -> None:
        self.rows.pop(i)


class FakeFeature:
    def __init__(self, name: str) -> None:
        self.Name = name
        self.state: dict[str, bool] = {}
        self.calls: list[tuple] = []

    def _FlagAsMethod(self, *n: str) -> None:
        pass

    def SetSuppression2(self, action: int, opt: int, names: Any) -> bool:
        self.calls.append((action, opt, names))
        return True

    def IsSuppressed2(self, opt: int, names: Any) -> list[bool]:
        return [self.state.get(n, False) for n in names]


class FakeDim:
    def __init__(self) -> None:
        self.SystemValue = 0.01
        self.calls: list[tuple] = []

    def _FlagAsMethod(self, *n: str) -> None:
        pass

    def SetSystemValue3(self, v: float, scope: int, names: Any) -> int:
        self.calls.append((v, scope, names))
        self.SystemValue = v
        return 0


class FakeDoc:
    def __init__(self) -> None:
        self.cfgs: dict[str, FakeCfg] = {}
        self.active = "Default"
        self._add("Default", None, 0)
        self.mass_by_cfg = {"Default": 0.5}
        self.props: dict[str, FakeProps] = {}
        self.override: float | None = None
        self.persist_override = True
        self.eq = FakeEq()
        self.dim = FakeDim()
        self.features = {"Boss": FakeFeature("Boss")}
        self.prefs: dict[int, int] = {263: 5, 47: 0, 49: 2, 51: 0, 52: 2, 258: 0, 259: 2, 260: 4, 261: 3}
        self.pref_calls: list[tuple[int, int]] = []
        self.reject_prefs: set[int] = set()
        self.ConfigurationManager = FakeConfigManager(self)
        self.Extension = FakeExt(self)
        self.shown: list[str] = []
        self.deleted: list[str] = []

    def _add(self, name: str, parent: FakeCfg | None, opts: int) -> FakeCfg:
        cfg = FakeCfg(name, parent)
        self.cfgs[name] = cfg
        self.mass_by_cfg = getattr(self, "mass_by_cfg", {})
        self.mass_by_cfg.setdefault(name, 0.5)
        if not opts & 128 and len(self.cfgs) > 1:
            self.active = name
        return cfg

    def _FlagAsMethod(self, *n: str) -> None:
        pass

    def GetConfigurationNames(self) -> tuple:
        return tuple(c.Name for c in self.cfgs.values())

    def GetActiveConfiguration(self) -> FakeCfg:
        return self.cfgs[self.active]

    def GetConfigurationByName(self, n: str) -> Any:
        return next((c for c in self.cfgs.values() if c.Name == n), None)

    def AddConfiguration3(self, name: str, comment: str, alt: str, opts: int) -> FakeCfg:
        cfg = self._add(name, None, opts)
        cfg.Comment = comment
        return cfg

    def ShowConfiguration2(self, n: str) -> bool:
        self.shown.append(n)
        if n in self.cfgs:
            self.active = n
            return True
        return False

    def DeleteConfiguration2(self, n: str) -> bool:
        if n == self.active:
            return False
        self.cfgs.pop(n)
        self.deleted.append(n)
        return True

    def GetEquationMgr(self) -> FakeEq:
        return self.eq

    def Parameter(self, name: str) -> Any:
        return self.dim if name == "D1@Sketch1" else None

    def GetUserPreferenceIntegerValue(self, pref: int) -> int:
        return self.prefs[pref]

    def SetUserPreferenceIntegerValue(self, pref: int, val: int) -> bool:
        self.pref_calls.append((pref, val))
        if pref in self.reject_prefs:
            return False
        self.prefs[pref] = val
        return True

    def GetType(self) -> int:
        return 1


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = FakeDoc()
        self.app = mock.Mock()
        patches = [
            mock.patch.object(dd, "active_document", lambda: (self.app, self.doc)),
            mock.patch.object(dd, "document_type", lambda d: 1),
            mock.patch.object(dd, "rebuild", lambda d: True),
            mock.patch.object(dd, "exit_active_sketch", lambda d: None),
            mock.patch.object(dd, "clear_selection", lambda d: None),
            mock.patch.object(dd, "find_feature", lambda d, n: d.features.get(n)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class RegistrationAndEnumTests(unittest.TestCase):
    def test_tools_registered(self) -> None:
        names = {t.name for t in sw_core.TOOLS}
        expected = {
            "list_configurations", "add_configuration", "activate_configuration", "delete_configuration",
            "rename_configuration", "set_config_feature_suppression", "set_dimension_config",
            "list_equations", "add_equation", "edit_equation", "delete_equation",
            "list_custom_properties", "set_custom_property", "delete_custom_property",
            "get_configuration_mass_properties", "set_mass_override",
            "get_document_units", "set_document_units",
        }
        self.assertTrue(expected <= names, expected - names)

    def test_enums_match_2017_typelib(self) -> None:
        self.assertEqual(dd.CFG_THIS, enum_value("swInConfigurationOpts_e.swThisConfiguration"))
        self.assertEqual(dd.CFG_ALL, enum_value("swInConfigurationOpts_e.swAllConfiguration"))
        self.assertEqual(dd.CFG_SPECIFIC, enum_value("swInConfigurationOpts_e.swSpecifyConfiguration"))
        self.assertEqual(dd.SET_VALUE_SCOPES["this"], enum_value("swSetValueInConfiguration_e.swSetValue_InThisConfiguration"))
        self.assertEqual(dd.SET_VALUE_SCOPES["all"], enum_value("swSetValueInConfiguration_e.swSetValue_InAllConfigurations"))
        self.assertEqual(dd.SET_VALUE_SCOPES["specified"], enum_value("swSetValueInConfiguration_e.swSetValue_InSpecificConfigurations"))
        self.assertEqual(dd.CFG_OPT_DONT_ACTIVATE, enum_value("swConfigurationOptions2_e.swConfigOption_DontActivate"))
        self.assertEqual(dd.SUPPRESS_FEATURE, enum_value("swFeatureSuppressionAction_e.swSuppressFeature"))
        self.assertEqual(dd.PROP_REPLACE_VALUE, enum_value("swCustomPropertyAddOption_e.swCustomPropertyReplaceValue"))
        for key, enum in (("text", "Text"), ("number", "Number"), ("double", "Double"), ("date", "Date"), ("yesno", "YesOrNo")):
            self.assertEqual(dd.PROPERTY_TYPES[key], enum_value(f"swCustomInfoType_e.swCustomInfo{enum}"))
        for key, enum in (("cgs", "CGS"), ("mks", "MKS"), ("ips", "IPS"), ("custom", "Custom"), ("mmgs", "MMGS")):
            self.assertEqual(dd.UNIT_SYSTEMS[key], enum_value(f"swUnitSystem_e.swUnitSystem_{enum}"))
        for key, enum in (("mm", "MM"), ("cm", "CM"), ("m", "METER"), ("in", "INCHES"), ("ft", "FEET")):
            self.assertEqual(dd.LENGTH_UNITS[key], enum_value(f"swLengthUnit_e.sw{enum}"))
        for key, enum in (("degrees", "DEGREES"), ("radians", "RADIANS")):
            self.assertEqual(dd.ANGLE_UNITS[key], enum_value(f"swAngleUnit_e.sw{enum}"))
        for key, enum in (("g", "Grams"), ("kg", "Kilograms"), ("lb", "Pounds")):
            self.assertEqual(dd.MASS_UNITS[key], enum_value(f"swUnitsMassPropMass_e.swUnitsMassPropMass_{enum}"))
        for key, enum in (("mm3", "Millimeters3"), ("cm3", "Centimeters3"), ("in3", "Inches3")):
            self.assertEqual(dd.VOLUME_UNITS[key], enum_value(f"swUnitsMassPropVolume_e.swUnitsMassPropVolume_{enum}"))
        for name, const in (
            ("swUnitSystem", dd.PREF_UNIT_SYSTEM), ("swUnitsLinear", dd.PREF_UNIT_LINEAR),
            ("swUnitsLinearDecimalPlaces", dd.PREF_UNIT_LINEAR_DECIMALS), ("swUnitsAngular", dd.PREF_UNIT_ANGULAR),
            ("swUnitsAngularDecimalPlaces", dd.PREF_UNIT_ANGULAR_DECIMALS), ("swUnitsMassPropLength", dd.PREF_MASS_LENGTH),
            ("swUnitsMassPropMass", dd.PREF_MASS_MASS), ("swUnitsMassPropVolume", dd.PREF_MASS_VOLUME),
            ("swUnitsMassPropDecimalPlaces", dd.PREF_MASS_DECIMALS),
        ):
            self.assertEqual(const, enum_value(f"swUserPreferenceIntegerValue_e.{name}"), name)

    def test_members_exist_in_2017_snapshot(self) -> None:
        snapshot = set((ROOT / "tools" / "compat" / "sw2017_api_members.txt").read_text(encoding="utf-8").split())
        for member in (
            "IModelDoc2.GetUserPreferenceIntegerValue", "IModelDoc2.SetUserPreferenceIntegerValue",
            "ICustomPropertyManager.Get4", "ICustomPropertyManager.Add3", "ICustomPropertyManager.Delete2",
            "ICustomPropertyManager.GetType2", "IEquationMgr.Add3", "IEquationMgr.SetEquationAndConfigurationOption",
            "IEquationMgr.EvaluateAll", "IConfigurationManager.AddConfiguration", "IModelDoc2.AddConfiguration3",
            "IModelDoc2.DeleteConfiguration2", "IModelDoc2.ShowConfiguration2", "IFeature.SetSuppression2",
            "IFeature.IsSuppressed2", "IDimension.SetSystemValue3", "IMassProperty.OverrideMass",
            "IModelDocExtension.CreateMassProperty", "IModelDocExtension.CustomPropertyManager",
        ):
            self.assertIn(member, snapshot, member)


class ConfigurationTests(Case):
    def test_list(self) -> None:
        self.doc._add("Short", self.doc.cfgs["Default"], 128)
        out = dd.list_configurations({})
        self.assertTrue(out["ok"])
        rows = {r["name"]: r for r in out["data"]["configurations"]}
        self.assertTrue(rows["Default"]["active"])
        self.assertTrue(rows["Short"]["derived"])
        self.assertEqual(rows["Short"]["parent"], "Default")

    def test_add_plain_does_not_activate(self) -> None:
        out = dd.add_configuration({"name": "Long", "description": "d"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.doc.active, "Default")
        self.assertEqual(self.doc.cfgs["Long"].Description, "d")

    def test_add_activate(self) -> None:
        dd.add_configuration({"name": "Long", "activate": True})
        self.assertEqual(self.doc.active, "Long")

    def test_add_derived_passes_parent(self) -> None:
        out = dd.add_configuration({"name": "Kid", "parent": "Default", "description": "x"})
        self.assertTrue(out["ok"], out)
        call = self.doc.ConfigurationManager.calls[0]
        self.assertEqual((call[0], call[4], call[5]), ("Kid", "Default", "x"))
        self.assertEqual(call[3], 128)
        self.assertTrue(self.doc.cfgs["Kid"].IsDerived)

    def test_add_rejections(self) -> None:
        self.assertFalse(dd.add_configuration({"name": "Default"})["ok"])
        self.assertFalse(dd.add_configuration({"name": "A", "parent": "Nope"})["ok"])

    def test_activate(self) -> None:
        dd.add_configuration({"name": "B"})
        self.assertTrue(dd.activate_configuration({"name": "B"})["ok"])
        self.assertEqual(self.doc.active, "B")
        self.assertFalse(dd.activate_configuration({"name": "Zzz"})["ok"])

    def test_delete_active_switches_first(self) -> None:
        dd.add_configuration({"name": "B"})
        out = dd.delete_configuration({"name": "Default"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["switched_to"], "B")
        self.assertNotIn("Default", self.doc.cfgs)

    def test_delete_last_refused(self) -> None:
        self.assertFalse(dd.delete_configuration({"name": "Default"})["ok"])

    def test_rename(self) -> None:
        out = dd.rename_configuration({"name": "Default", "new_name": "Base"})
        self.assertTrue(out["ok"], out)
        dd.add_configuration({"name": "X"})
        self.assertFalse(dd.rename_configuration({"name": "X", "new_name": "X"})["ok"])

    def test_config_suppression_scopes(self) -> None:
        dd.add_configuration({"name": "B"})
        feat = self.doc.features["Boss"]
        out = dd.set_config_feature_suppression({"feature_names": ["Boss"], "scope": "specified", "configurations": ["B"]})
        self.assertTrue(out["ok"], out)
        action, opt, names = feat.calls[0]
        self.assertEqual((action, opt), (0, 3))
        self.assertEqual(list(names.value), ["B"])
        dd.set_config_feature_suppression({"feature_names": ["Boss"], "suppressed": False, "scope": "all"})
        self.assertEqual(feat.calls[1][:2], (1, 2))
        self.assertFalse(dd.set_config_feature_suppression({"feature_names": ["Boss"], "scope": "specified"})["ok"])
        self.assertFalse(dd.set_config_feature_suppression({"feature_names": ["Nope"]})["ok"])

    def test_set_dimension_config(self) -> None:
        out = dd.set_dimension_config({"full_name": "D1@Sketch1", "value_mm": 25, "scope": "specified", "configurations": ["Default"]})
        self.assertTrue(out["ok"], out)
        value, scope, names = self.doc.dim.calls[0]
        self.assertAlmostEqual(value, 0.025)
        self.assertEqual(scope, 3)
        dd.set_dimension_config({"full_name": "D1@Sketch1", "value_mm": 5})
        self.assertEqual(self.doc.dim.calls[1][1], 1)
        self.assertFalse(dd.set_dimension_config({"full_name": "D9@x", "value_mm": 5})["ok"])
        self.assertFalse(dd.set_dimension_config({"full_name": "D1@Sketch1"})["ok"])


class EquationTests(Case):
    def test_add_global_and_dimension_equation(self) -> None:
        out = dd.add_equation({"global_variable": "width", "expression": "40"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.doc.eq.add_calls[0][1], '"width"= 40')
        self.assertEqual(self.doc.eq.add_calls[0][2], 2)
        out = dd.add_equation({"dimension_name": "D1@Sketch1", "expression": '"width" * 2', "scope": "this"})
        self.assertEqual(self.doc.eq.add_calls[1][1], '"D1@Sketch1"= "width" * 2')
        self.assertEqual(self.doc.eq.add_calls[1][2], 1)
        listing = dd.list_equations({})
        self.assertEqual(listing["data"]["global_variables"], ["width"])
        self.assertGreaterEqual(self.doc.eq.evaluated, 1)

    def test_add_validation(self) -> None:
        self.assertFalse(dd.add_equation({})["ok"])
        self.assertFalse(dd.add_equation({"global_variable": "a", "equation": "b"})["ok"])
        self.assertFalse(dd.add_equation({"global_variable": "a"})["ok"])

    def test_solver_status_reported(self) -> None:
        self.doc.eq.Status = -2
        out = dd.add_equation({"equation": '"a"= 1'})
        # Status is informational on add (live 2017 reads -1 right after a good Add3)
        self.assertEqual(out["data"]["status"], -2)

    def test_edit_by_name_and_index(self) -> None:
        dd.add_equation({"global_variable": "width", "expression": "40"})
        out = dd.edit_equation({"name": "width", "expression": "50"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.doc.eq.rows[0][0], '"width"= 50')
        self.assertTrue(dd.edit_equation({"index": 0, "equation": '"width"= 60'})["ok"])
        self.assertFalse(dd.edit_equation({"name": "nope", "expression": "1"})["ok"])
        self.assertFalse(dd.edit_equation({"name": "width"})["ok"])

    def test_delete(self) -> None:
        dd.add_equation({"global_variable": "w", "expression": "1"})
        out = dd.delete_equation({"name": "w"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["count"], 0)
        self.assertFalse(dd.delete_equation({"index": 5})["ok"])


class PropertyTests(Case):
    def test_roundtrip_file_and_config(self) -> None:
        out = dd.set_custom_property({"name": "Part", "value": "$PRPSHEET", "type": "text"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["property"]["resolved_value"], "$PRPSHEET".replace("$PRP", "R"))
        dd.set_custom_property({"name": "Qty", "value": "4", "type": "number", "configuration": "Default"})
        dd.set_custom_property({"name": "Ok", "value": "Yes", "type": "yesno"})
        file_level = dd.list_custom_properties({})["data"]["properties"]
        self.assertEqual({p["name"]: p["type"] for p in file_level}, {"Part": "text", "Ok": "yesno"})
        cfg_level = dd.list_custom_properties({"configuration": "Default"})["data"]["properties"]
        self.assertEqual([(p["name"], p["type"]) for p in cfg_level], [("Qty", "double")])  # number is written as Add3 type 5 on 2017

    def test_delete(self) -> None:
        dd.set_custom_property({"name": "A", "value": "1"})
        self.assertTrue(dd.delete_custom_property({"name": "A"})["ok"])
        out = dd.delete_custom_property({"name": "A"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["data"]["status"], 1)

    def test_bad_inputs(self) -> None:
        self.assertFalse(dd.set_custom_property({"name": "A", "value": "1", "type": "bogus"})["ok"])
        self.assertFalse(dd.list_custom_properties({"configuration": "Nope"})["ok"])
        self.assertEqual(dd.list_custom_properties({})["data"]["properties"], [])


class MassTests(Case):
    def test_per_configuration_and_restore(self) -> None:
        dd.add_configuration({"name": "Light"})
        self.doc.mass_by_cfg["Light"] = 0.25
        out = dd.get_configuration_mass_properties({})
        self.assertTrue(out["ok"], out)
        rows = out["data"]["configurations"]
        self.assertEqual(rows["Default"]["mass_g"], 500.0)
        self.assertEqual(rows["Light"]["mass_g"], 250.0)
        self.assertEqual(rows["Default"]["volume_mm3"], 1000.0)
        self.assertEqual(self.doc.active, "Default")
        self.assertFalse(dd.get_configuration_mass_properties({"configurations": ["Nope"]})["ok"])

    def test_mass_override_persisted(self) -> None:
        out = dd.set_mass_override({"override_mass_g": 123.0})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["after"]["mass_g"], 123.0)

    def test_mass_override_not_persisted_is_reported(self) -> None:
        self.doc.persist_override = False
        out = dd.set_mass_override({"override_mass_g": 123.0})
        self.assertFalse(out["ok"])
        self.assertFalse(out["data"]["persisted"])

    def test_density_is_what_if_only(self) -> None:
        out = dd.set_mass_override({"density_g_per_cm3": 7.8})
        self.assertTrue(out["ok"])
        self.assertFalse(out["data"]["applied"])
        self.assertAlmostEqual(out["data"]["what_if_mass_g"], 7.8)
        self.assertIsNone(self.doc.override)
        self.assertFalse(dd.set_mass_override({})["ok"])


class UnitTests(Case):
    def test_get(self) -> None:
        units = dd.get_document_units({})["data"]["units"]
        self.assertEqual(units["unit_system"], "mmgs")
        self.assertEqual(units["length_unit"], "mm")
        self.assertEqual(units["length_decimals"], 2)

    def test_set_named_system_and_decimals(self) -> None:
        out = dd.set_document_units({"unit_system": "ips", "length_decimals": 4})
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.doc.pref_calls, [(263, 3), (49, 4)])
        self.assertEqual(out["data"]["units"]["unit_system"], "ips")
        self.assertEqual(out["data"]["before"]["unit_system"], "mmgs")

    def test_custom_length_implies_custom_system(self) -> None:
        out = dd.set_document_units({"length_unit": "in"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.doc.pref_calls[0], (263, 4))
        self.assertEqual(self.doc.pref_calls[1], (47, 3))

    def test_length_with_named_system_refused(self) -> None:
        out = dd.set_document_units({"unit_system": "mmgs", "length_unit": "in"})
        self.assertFalse(out["ok"])
        self.assertEqual(self.doc.pref_calls, [])

    def test_validation_and_rejection(self) -> None:
        self.assertFalse(dd.set_document_units({})["ok"])
        self.assertFalse(dd.set_document_units({"length_decimals": 12})["ok"])
        self.assertFalse(dd.set_document_units({"unit_system": "furlong"})["ok"])
        self.doc.reject_prefs.add(49)
        out = dd.set_document_units({"length_decimals": 3})
        self.assertFalse(out["ok"])
        self.assertEqual(out["data"]["failed"], ["length_decimals"])


if __name__ == "__main__":
    unittest.main()
