# Offline tests for the Batch A assembly tools (sw_assembly.py).
# COM objects are replaced with fakes; no SOLIDWORKS is touched.

from __future__ import annotations

import math
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solidworks_mcp import sw_assembly, sw_core  # noqa: E402

IDENTITY = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]


class FakeDim:
    def __init__(self, name: str, si_value: float) -> None:
        self.Name, self.FullName, self.SystemValue = name, name + "@Assem1.SLDASM", si_value
        self.set_to: list[float] = []

    def SetSystemValue3(self, new: float, scope: int, configs: Any) -> int:
        self.set_to.append(new)
        self.SystemValue = new
        return 0


class FakeDisplay:
    def __init__(self, dim: FakeDim, nxt: "FakeDisplay | None" = None) -> None:
        self.dim, self.nxt = dim, nxt

    def GetDimension2(self, index: int) -> FakeDim:
        return self.dim


class FakeEntity:
    def __init__(self, component: Any) -> None:
        self.ReferenceComponent, self.ReferenceType2 = component, 4
        self.Reference = object()


class FakeMate:
    """IMate2 stand-in."""

    def __init__(self, mate_type: int, alignment: int = 0, flipped: bool = False, comps: tuple = ()) -> None:
        self.Type, self.Alignment, self.Flipped = mate_type, alignment, flipped
        self.MinimumVariation, self.MaximumVariation = 0.0, 0.0
        self.comps = comps
        self.GetMateEntityCount = len(comps)

    def MateEntity(self, index: int) -> FakeEntity:
        return FakeEntity(self.comps[index])


class FakeFeature:
    def __init__(self, name: str, type_name: str, definition: Any = None, dims: list[FakeDim] | None = None,
                 sub: "FakeFeature | None" = None, nxt: "FakeFeature | None" = None) -> None:
        self.Name, self.GetTypeName2 = name, type_name
        self.GetFirstSubFeature, self.GetNextSubFeature, self.GetNextFeature = sub, nxt, None
        self.GetSpecificFeature2 = definition
        self.IsSuppressed = False
        self.selected = False
        displays = None
        for dim in reversed(dims or []):
            displays = FakeDisplay(dim, displays)
        self.GetFirstDisplayDimension = displays.dim and displays if displays else None

    def GetNextDisplayDimension(self, display: FakeDisplay) -> FakeDisplay | None:
        return display.nxt

    def Select2(self, append: bool, mark: int) -> bool:
        self.selected = True
        return True


class FakeComponent:
    def __init__(self, name: str, matrix: list[float] | None = None, fixed: bool = False, path: str = "C:/x/p.sldprt",
                 config: str = "Default", configs: tuple = ("Default", "Long")) -> None:
        self.Name2, self.IsFixed, self.IsSuppressed = name, fixed, False
        self.GetPathName, self.ReferencedConfiguration = path, config
        self.Visible, self.GetSuppression, self.IsVirtual = 1, 2, False
        self.GetSelectByIDString = name + "@Assem1"
        self.matrix = list(matrix or IDENTITY)
        self.constrained = False
        self.GetModelDoc2 = type("Model", (), {"GetConfigurationNames": configs})()
        self.Transform2 = self  # value(Transform2, "ArrayData") below
        self.suppress_calls: list[int] = []

    @property
    def ArrayData(self) -> list[float]:
        return list(self.matrix)

    def SetSuppression2(self, state: int) -> int:
        self.suppress_calls.append(state)
        self.IsSuppressed = state == 0
        return 1


class FakeMathUtility:
    def CreateTransform(self, data: Any) -> list[float]:
        return list(data.value if hasattr(data, "value") else data)


class FakeApp:
    def __init__(self) -> None:
        self.GetMathUtility = FakeMathUtility()
        self.opened: list[tuple] = []
        self.result_doc: Any = type("Opened", (), {"GetTitle": "p.SLDPRT"})()

    def OpenDoc6(self, path: str, doc_type: int, options: int, config: str, errors: Any, warnings: Any) -> Any:
        self.opened.append((path, doc_type, options, config))
        return self.result_doc

    def ActivateDoc3(self, *args: Any) -> Any:
        return None


class FakeAssembly:
    def __init__(self, components: list[FakeComponent] | None = None, first_feature: Any = None) -> None:
        self.components = components or []
        self.FirstFeature = first_feature
        self.GetTitle = "Assem1.SLDASM"
        self.add_args: tuple | None = None
        self.edit_args: tuple | None = None
        self.hidden_calls: list[str] = []
        self.mate_result: Any = object()
        self.on_add: Any = None  # called after AddMate5 so a new mate can appear in the tree
        self.InterferenceDetectionManager: Any = None

    def GetComponents(self, top_only: bool) -> list[FakeComponent]:
        return self.components

    def AddMate5(self, *args: Any) -> Any:
        self.add_args = args
        args[-1].value = 1  # status byref
        if self.on_add:
            self.on_add()
        return self.mate_result

    def EditMate4(self, *args: Any) -> bool:
        self.edit_args = args
        return True

    @property
    def HideComponent2(self) -> None:
        self.hidden_calls.append("hide")

    @property
    def ShowComponent2(self) -> None:
        self.hidden_calls.append("show")

    @property
    def EditSuppress2(self) -> bool:
        self.suppress_called = "suppress"
        return True

    @property
    def EditUnsuppress2(self) -> bool:
        self.suppress_called = "unsuppress"
        return True


def _patched(doc: Any, app: Any = None):
    """Patch the assembly requirement and selection plumbing used by every tool."""
    stack = unittest.mock.patch.multiple(
        sw_assembly,
        require_assembly=unittest.mock.Mock(return_value=(app, doc)),
        clear_selection=unittest.mock.Mock(),
        rebuild=unittest.mock.Mock(return_value=True),
        selectable=unittest.mock.Mock(side_effect=lambda f: f),
    )
    return stack


def _mate_tree(*mates: FakeFeature) -> FakeFeature:
    for left, right in zip(mates, mates[1:]):
        left.GetNextSubFeature = right
    return FakeFeature("Mates", "MateGroup", sub=mates[0])


class RegistrationTests(unittest.TestCase):
    def test_new_tools_registered(self) -> None:
        names = {t.name for t in sw_core.TOOLS}
        expected = {
            "edit_mate", "set_mate_suppression", "move_component", "rotate_component",
            "set_component_configuration", "set_component_visibility", "set_component_suppression",
            "replace_component", "open_component", "interference_detection",
            "list_components", "list_mates", "add_mate", "insert_component",
        }
        self.assertTrue(expected <= names, expected - names)

    def test_add_mate_requires_only_mate_type(self) -> None:
        schema = next(t for t in sw_core.TOOLS if t.name == "add_mate").inputSchema
        self.assertEqual(schema["required"], ["mate_type"])
        self.assertIn("entities", schema["properties"])


class TransformMathTests(unittest.TestCase):
    def test_translate(self) -> None:
        moved = sw_assembly.translate_matrix(IDENTITY, [0.1, 0.0, -0.2])
        self.assertEqual(moved[9:12], [0.1, 0.0, -0.2])

    def test_rotate_90_about_z_through_origin(self) -> None:
        matrix = list(IDENTITY)
        matrix[9:12] = [1.0, 0.0, 0.0]
        out = sw_assembly.rotate_matrix(matrix, [0, 0, 1], math.pi / 2, pivot_m=[0.0, 0.0, 0.0])
        # Origin swung from +X to +Y.
        self.assertAlmostEqual(out[9], 0.0, places=9)
        self.assertAlmostEqual(out[10], 1.0, places=9)
        # Component X axis now points along +Y: apply_transform maps (1,0,0) -> origin + (0,1,0).
        mapped = sw_core.apply_transform([1.0, 0.0, 0.0], out)
        self.assertAlmostEqual(mapped[0], 0.0, places=9)
        self.assertAlmostEqual(mapped[1], 2.0, places=9)

    def test_rotate_about_own_origin_keeps_translation(self) -> None:
        matrix = list(IDENTITY)
        matrix[9:12] = [0.3, 0.2, 0.1]
        out = sw_assembly.rotate_matrix(matrix, [0, 1, 0], math.pi / 3)
        self.assertEqual([round(v, 9) for v in out[9:12]], [0.3, 0.2, 0.1])

    def test_zero_axis_rejected(self) -> None:
        with self.assertRaises(ValueError):
            sw_assembly.rotation_about([0, 0, 0], 1.0)


class ListMatesTests(unittest.TestCase):
    def _doc(self) -> tuple[FakeAssembly, FakeFeature]:
        a, b = FakeComponent("A-1"), FakeComponent("B-1")
        dist = FakeFeature("Distance1", "MateDistanceDim", FakeMate(5, 1, True, (a, b)), [FakeDim("D1@Distance1", 0.012)])
        coin = FakeFeature("Coincident1", "MateCoincident", FakeMate(0, 2, False, (a, b)))
        coin.IsSuppressed = True
        angle = FakeFeature("Angle1", "MateAngleDim", FakeMate(6), [FakeDim("D1@Angle1", math.pi / 2)])
        group = _mate_tree(coin, dist, angle)
        return FakeAssembly(first_feature=group), dist

    def test_full_entry(self) -> None:
        doc, _ = self._doc()
        with _patched(doc):
            out = sw_assembly.list_mates({})
        self.assertTrue(out["ok"])
        by_name = {m["name"]: m for m in out["data"]["mates"]}
        dist = by_name["Distance1"]
        self.assertEqual(dist["mate_type"], "distance")
        self.assertEqual(dist["alignment"], "anti_aligned")
        self.assertTrue(dist["flipped"])
        self.assertEqual(dist["dimension_name"], "D1@Distance1")
        self.assertEqual(dist["distance_mm"], 12.0)
        self.assertEqual([e["component"] for e in dist["entities"]], ["A-1", "B-1"])
        self.assertTrue(by_name["Coincident1"]["suppressed"])
        self.assertEqual(by_name["Coincident1"]["dimensions"], [])
        self.assertEqual(by_name["Angle1"]["angle_deg"], 90.0)


class EditMateTests(unittest.TestCase):
    def _doc(self) -> tuple[FakeAssembly, FakeDim]:
        dim = FakeDim("D1@Distance1", 0.012)
        feat = FakeFeature("Distance1", "MateDistanceDim", FakeMate(5, 0, False), [dim])
        return FakeAssembly(first_feature=_mate_tree(feat)), dim

    def test_value_only_uses_dimension(self) -> None:
        doc, dim = self._doc()
        with _patched(doc):
            out = sw_assembly.edit_mate({"mate_name": "Distance1", "distance_mm": 20})
        self.assertTrue(out["ok"], out)
        self.assertAlmostEqual(dim.set_to[0], 0.020)
        self.assertIsNone(doc.edit_args)
        self.assertEqual(out["data"]["previous"]["distance_mm"], 12.0)

    def _recreate(self, doc: FakeAssembly, args: dict[str, Any]) -> dict[str, Any]:
        # EditMate4 is a no-op on 2017, so edits re-create the mate: delete it, reselect its
        # entities, AddMate5 again.
        deleted: list[str] = []

        def fake_delete(a: dict[str, Any]) -> dict[str, Any]:
            deleted.append(a["mate_name"])
            return {"ok": True, "message": "deleted"}

        self.deleted = deleted
        with _patched(doc), unittest.mock.patch.object(sw_assembly, "delete_mate", fake_delete),                 unittest.mock.patch.object(sw_assembly, "select_object", return_value=True):
            return sw_assembly.edit_mate({"mate_name": "Distance1", **args})

    def _doc_with_entities(self) -> FakeAssembly:
        dim = FakeDim("D1@Distance1", 0.012)
        mate = FakeMate(5, 0, False, comps=(FakeComponent("a-1"), FakeComponent("b-1")))
        feat = FakeFeature("Distance1", "MateDistanceDim", mate, [dim])
        return FakeAssembly(first_feature=_mate_tree(feat))

    def test_flip_recreates_the_mate(self) -> None:
        doc = self._doc_with_entities()
        out = self._recreate(doc, {"flip": True, "alignment": "anti_aligned"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.deleted, ["Distance1"])
        args = doc.add_args
        self.assertEqual(args[0], 5)      # mate type preserved
        self.assertEqual(args[1], 1)      # anti-aligned
        self.assertTrue(args[2])          # flip
        self.assertAlmostEqual(args[3], 0.012)  # current distance preserved
        self.assertIsNone(doc.edit_args)  # EditMate4 is never called

    def test_limits_passed(self) -> None:
        doc = self._doc_with_entities()
        out = self._recreate(doc, {"min_distance_mm": 5, "max_distance_mm": 30})
        self.assertTrue(out["ok"], out)
        self.assertAlmostEqual(doc.add_args[4], 0.030)
        self.assertAlmostEqual(doc.add_args[5], 0.005)

    def test_refused_edit_restores_original(self) -> None:
        doc = self._doc_with_entities()
        calls: list[tuple] = []

        def add(*a: Any) -> Any:
            calls.append(a)
            a[-1].value = 0
            return None if len(calls) == 1 else object()

        doc.AddMate5 = add  # type: ignore[method-assign]
        out = self._recreate(doc, {"flip": True})
        self.assertFalse(out["ok"])
        self.assertTrue(out["data"]["restored"])
        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[1][2])     # original (unflipped) settings used for the restore

    def test_bad_inputs(self) -> None:
        doc, _ = self._doc()
        with _patched(doc):
            self.assertFalse(sw_assembly.edit_mate({"mate_name": "Nope", "flip": True})["ok"])
            self.assertFalse(sw_assembly.edit_mate({"mate_name": "Distance1"})["ok"])
            self.assertFalse(sw_assembly.edit_mate({"mate_name": "Distance1", "angle_deg": 5})["ok"])
            self.assertFalse(
                sw_assembly.edit_mate({"mate_name": "Distance1", "min_distance_mm": 9, "max_distance_mm": 1})["ok"]
            )


class MateSuppressionTests(unittest.TestCase):
    def test_suppress_with_readback(self) -> None:
        feat = FakeFeature("Distance1", "MateDistanceDim", FakeMate(5))
        doc = FakeAssembly(first_feature=_mate_tree(feat))

        def flip_state(*_: Any) -> bool:
            feat.IsSuppressed = True
            return True

        with _patched(doc), unittest.mock.patch.object(sw_assembly, "value", side_effect=lambda o, m: (
            flip_state() if m == "EditSuppress2" else sw_core.value(o, m)
        )):
            out = sw_assembly.set_mate_suppression({"mate_names": ["Distance1"], "suppressed": True})
        self.assertTrue(out["ok"], out)
        self.assertTrue(feat.selected)
        self.assertEqual(out["data"]["suppressed_state"], {"Distance1": True})

    def test_unknown_mate(self) -> None:
        doc = FakeAssembly(first_feature=_mate_tree(FakeFeature("A", "MateCoincident", FakeMate(0))))
        with _patched(doc):
            self.assertFalse(sw_assembly.set_mate_suppression({"mate_names": ["Zzz"]})["ok"])


class AddMateTests(unittest.TestCase):
    def test_requires_something_to_mate(self) -> None:
        with _patched(FakeAssembly()):
            self.assertFalse(sw_assembly.add_mate({"mate_type": "coincident"})["ok"])

    def test_limit_distance_values(self) -> None:
        doc = FakeAssembly(first_feature=_mate_tree(FakeFeature("Limit1", "MateDistanceDim", FakeMate(5))))
        with _patched(doc), unittest.mock.patch.object(sw_assembly, "require_selection", return_value=2):
            out = sw_assembly.add_mate({
                "mate_type": "distance", "selection": {"faces": [0, 1]},
                "distance_mm": 10, "min_distance_mm": 5, "max_distance_mm": 20,
            })
        self.assertTrue(out["ok"], out)
        a = doc.add_args
        self.assertEqual((a[3], a[4], a[5]), (0.010, 0.020, 0.005))
        self.assertEqual(a[13], 0)  # width option default: centered

    def test_inverted_limits_rejected(self) -> None:
        with _patched(FakeAssembly()), unittest.mock.patch.object(sw_assembly, "require_selection", return_value=2):
            out = sw_assembly.add_mate({
                "mate_type": "distance", "selection": {"faces": [0, 1]}, "min_distance_mm": 9, "max_distance_mm": 1,
            })
        self.assertFalse(out["ok"])

    def test_width_option_and_new_mate_reported(self) -> None:
        doc = FakeAssembly(first_feature=_mate_tree(FakeFeature("Old1", "MateCoincident", FakeMate(0))))
        doc.on_add = lambda: setattr(doc.FirstFeature.GetFirstSubFeature, "GetNextSubFeature",
                                     FakeFeature("Width1", "MateWidth", FakeMate(11)))
        with _patched(doc), unittest.mock.patch.object(sw_assembly, "require_selection", return_value=4):
            out = sw_assembly.add_mate({
                "mate_type": "width", "selection": {"faces": [0, 1, 2, 3]}, "width_option": "free",
            })
        self.assertEqual(doc.add_args[13], 1)
        self.assertEqual(out["data"]["mate"], "Width1")

    def test_entities_selected_by_component(self) -> None:
        a, b = FakeComponent("A-1"), FakeComponent("B-1")
        doc = FakeAssembly([a, b], first_feature=_mate_tree(FakeFeature("Coincident1", "MateCoincident", FakeMate(0))))
        calls: list[Any] = []
        face_a, face_b = object(), object()
        bodies = {"A-1": [type("Body", (), {"GetFaces": [face_a]})()], "B-1": [type("Body", (), {"GetFaces": [face_b]})()]}
        with _patched(doc), \
             unittest.mock.patch.object(sw_assembly, "component_bodies", side_effect=lambda c: bodies[c.Name2]), \
             unittest.mock.patch.object(sw_assembly, "select_object", side_effect=lambda d, o, m, ap: calls.append((o, ap)) or True):
            out = sw_assembly.add_mate({
                "mate_type": "coincident",
                "entities": [{"component": "A-1", "face": 0}, {"component": "B-1", "face": 0, "mark": 0}],
            })
        self.assertTrue(out["ok"], out)
        self.assertEqual(calls, [(face_a, False), (face_b, True)])
        self.assertEqual(out["data"]["picked"], ["face 0 of A-1", "face 0 of B-1"])

    def test_entity_index_out_of_range(self) -> None:
        a = FakeComponent("A-1")
        doc = FakeAssembly([a])
        with _patched(doc), unittest.mock.patch.object(sw_assembly, "component_bodies", return_value=[]):
            out = sw_assembly.add_mate({"mate_type": "coincident", "entities": [{"component": "A-1", "face": 3}]})
        self.assertFalse(out["ok"])
        self.assertIn("out of range", out["message"])


class ComponentToolTests(unittest.TestCase):
    def test_list_components_fields(self) -> None:
        matrix = list(IDENTITY)
        matrix[9:12] = [0.1, 0.0, 0.0]
        comp = FakeComponent("A-1", matrix)
        comp.Visible = 0
        with _patched(FakeAssembly([comp])):
            out = sw_assembly.list_components({})
        item = out["data"]["components"][0]
        self.assertEqual(item["configuration"], "Default")
        self.assertTrue(item["hidden"])
        self.assertEqual(item["suppression_state"], "resolved")
        self.assertEqual(item["origin_mm"], [100.0, 0.0, 0.0])
        self.assertEqual(item["transform"]["translation_mm"], [100.0, 0.0, 0.0])

    def test_move_relative_and_fixed_refusal(self) -> None:
        app = FakeApp()
        comp, fixed = FakeComponent("A-1"), FakeComponent("F-1", fixed=True)
        doc = FakeAssembly([comp, fixed])

        def solve(c: FakeComponent):
            def _set(transform: Any) -> None:
                c.matrix = list(transform)
            return _set

        with _patched(doc, app), unittest.mock.patch.object(sw_assembly, "_set_component_matrix",
                                                             side_effect=lambda a, c, m: setattr(c, "matrix", list(m))):
            out = sw_assembly.move_component({"component": "A-1", "x_mm": 50, "y_mm": 0, "z_mm": 25})
            self.assertTrue(out["ok"], out)
            self.assertEqual(out["data"]["origin_mm"], [50.0, 0.0, 25.0])
            self.assertNotIn("warning", out["data"])
            refused = sw_assembly.move_component({"component": "F-1", "x_mm": 1})
            self.assertFalse(refused["ok"])
            self.assertIn("fixed", refused["message"])
            absolute = sw_assembly.move_component({"component": "A-1", "x_mm": 5, "y_mm": 6, "z_mm": 7, "mode": "absolute"})
            self.assertEqual(absolute["data"]["origin_mm"], [5.0, 6.0, 7.0])

    def test_move_warns_when_mates_push_back(self) -> None:
        comp = FakeComponent("A-1")
        doc = FakeAssembly([comp])
        with _patched(doc, FakeApp()), unittest.mock.patch.object(sw_assembly, "_set_component_matrix"):
            out = sw_assembly.move_component({"component": "A-1", "x_mm": 50})
        self.assertTrue(out["ok"])
        self.assertIn("warning", out["data"])

    def test_rotate_component(self) -> None:
        matrix = list(IDENTITY)
        matrix[9:12] = [0.1, 0.0, 0.0]
        comp = FakeComponent("A-1", matrix)
        with _patched(FakeAssembly([comp]), FakeApp()), unittest.mock.patch.object(
            sw_assembly, "_set_component_matrix", side_effect=lambda a, c, m: setattr(c, "matrix", list(m))
        ):
            out = sw_assembly.rotate_component({"component": "A-1", "axis": "z", "angle_deg": 90, "pivot_mm": [0, 0, 0]})
        self.assertTrue(out["ok"], out)
        origin = out["data"]["origin_mm"]
        self.assertAlmostEqual(origin[0], 0.0, places=4)
        self.assertAlmostEqual(origin[1], 100.0, places=4)

    def test_rotate_rejects_bad_axis(self) -> None:
        with _patched(FakeAssembly([FakeComponent("A-1")]), FakeApp()):
            self.assertFalse(sw_assembly.rotate_component({"component": "A-1", "axis": [0, 0, 0], "angle_deg": 5})["ok"])

    def test_set_configuration(self) -> None:
        comp = FakeComponent("A-1")
        with _patched(FakeAssembly([comp])):
            ok = sw_assembly.set_component_configuration({"component": "A-1", "configuration": "Long"})
            bad = sw_assembly.set_component_configuration({"component": "A-1", "configuration": "Nope"})
        self.assertTrue(ok["ok"], ok)
        self.assertEqual(comp.ReferencedConfiguration, "Long")
        self.assertFalse(bad["ok"])
        self.assertIn("Available", bad["message"])

    def test_visibility(self) -> None:
        comp = FakeComponent("A-1")
        doc = FakeAssembly([comp])

        def hide(*_: Any) -> None:
            comp.Visible = 0

        with _patched(doc), unittest.mock.patch.object(sw_assembly, "require_selection", return_value=1), \
             unittest.mock.patch.object(sw_assembly, "value", side_effect=lambda o, m: hide() if m == "HideComponent2" else sw_core.value(o, m)):
            out = sw_assembly.set_component_visibility({"component_names": ["A-1"], "visible": False})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["data"]["visible_state"], {"A-1": False})

    def test_suppression(self) -> None:
        comp = FakeComponent("A-1")
        with _patched(FakeAssembly([comp])):
            sup = sw_assembly.set_component_suppression({"component_names": ["A-1"], "suppressed": True})
            res = sw_assembly.set_component_suppression({"component_names": ["A-1"], "suppressed": False})
        self.assertTrue(sup["ok"] and res["ok"])
        self.assertEqual(comp.suppress_calls, [0, 2])

    def test_open_component_virtual_refused(self) -> None:
        comp = FakeComponent("V-1", path="")
        with _patched(FakeAssembly([comp]), FakeApp()):
            out = sw_assembly.open_component({"component": "V-1"})
        self.assertFalse(out["ok"])
        self.assertIn("virtual", out["message"])

    def test_open_component(self) -> None:
        app = FakeApp()
        comp = FakeComponent("A-1", path="C:/x/p.sldprt", config="Long")
        with _patched(FakeAssembly([comp]), app):
            out = sw_assembly.open_component({"component": "A-1"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(app.opened[0], ("C:/x/p.sldprt", 1, 0, "Long"))
        self.assertEqual(out["data"]["title"], "p.SLDPRT")

    def test_insert_subassembly_with_configuration(self) -> None:
        app = FakeApp()
        placed = FakeComponent("Sub-1", config="Big")
        doc = FakeAssembly([placed])
        seen: dict[str, Any] = {}

        def add(path: str, option: int, new_name: str, use_existing: bool, config: str, x: float, y: float, z: float) -> Any:
            seen.update(path=path, option=option, config=config)
            return placed

        doc.AddComponent5 = add
        with tempfile.TemporaryDirectory() as tmp:
            asm = Path(tmp) / "sub.sldasm"
            asm.write_text("x")
            with _patched(doc, app):
                out = sw_assembly.insert_component({"path": str(asm), "configuration": "Big"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(seen["option"], 0)  # CurrentSelectedConfig + ExistingConfigName; 2 creates a new config
        self.assertEqual(seen["config"], "Big")
        self.assertTrue(out["data"]["is_assembly"])
        self.assertEqual(app.opened[0][1], 2)  # opened as an assembly
        self.assertNotIn("configuration_warning", out["data"])

    def test_replace_component(self) -> None:
        app = FakeApp()
        comp = FakeComponent("A-1")
        doc = FakeAssembly([comp], first_feature=_mate_tree(FakeFeature("C1", "MateCoincident", FakeMate(0))))
        seen: dict[str, Any] = {}
        doc.ReplaceComponents2 = lambda *a: seen.setdefault("args", a) and True
        with tempfile.TemporaryDirectory() as tmp:
            new = Path(tmp) / "new.sldprt"
            new.write_text("x")
            with _patched(doc, app), unittest.mock.patch.object(sw_assembly, "require_selection", return_value=1):
                out = sw_assembly.replace_component({"component": "A-1", "new_path": str(new)})
        self.assertTrue(out["ok"], out)
        self.assertEqual(seen["args"][0], str(new.resolve()))
        self.assertTrue(seen["args"][4])  # keep_mates default
        self.assertEqual((out["data"]["mates_before"], out["data"]["mates_after"]), (1, 1))

    def test_replace_missing_file(self) -> None:
        with _patched(FakeAssembly([FakeComponent("A-1")]), FakeApp()):
            self.assertFalse(sw_assembly.replace_component({"component": "A-1", "new_path": "C:/nope/x.sldprt"})["ok"])


class FakeInterference:
    def __init__(self, names: tuple, volume: float) -> None:
        self.Components = [FakeComponent(n) for n in names]
        self.Volume, self.IsPossibleInterference = volume, False


class FakeInterferenceMgr:
    def __init__(self, found: list[FakeInterference]) -> None:
        self.found, self.closed = found, False
        self.TreatCoincidenceAsInterference = True

    @property
    def GetInterferences(self) -> list[FakeInterference]:
        return self.found

    @property
    def Done(self) -> None:
        self.closed = True


class InterferenceTests(unittest.TestCase):
    def test_pairs_and_volumes(self) -> None:
        mgr = FakeInterferenceMgr([FakeInterference(("A-1", "B-1"), 2.0e-6), FakeInterference(("B-1", "C-1"), 1.0e-6)])
        doc = FakeAssembly()
        doc.InterferenceDetectionManager = mgr
        with _patched(doc):
            out = sw_assembly.interference_detection({})
        self.assertTrue(out["ok"], out)
        data = out["data"]
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["interferences"][0]["components"], ["A-1", "B-1"])
        self.assertAlmostEqual(data["interferences"][0]["volume_mm3"], 2000.0)
        self.assertAlmostEqual(data["total_volume_mm3"], 3000.0)
        self.assertFalse(mgr.TreatCoincidenceAsInterference)
        self.assertTrue(mgr.closed)

    def test_none_found(self) -> None:
        mgr = FakeInterferenceMgr([])
        doc = FakeAssembly()
        doc.InterferenceDetectionManager = mgr
        with _patched(doc):
            out = sw_assembly.interference_detection({})
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"]["count"], 0)
        self.assertTrue(mgr.closed)


if __name__ == "__main__":
    unittest.main()
