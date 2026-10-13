# Offline tests for the Phase 5 field fixes in sw_feature: extrude direction (#5),
# delete_feature (#8), set_feature_suppression (#9) and fillet options (#17).
# COM objects are fakes; nothing touches SOLIDWORKS.

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from solidworks_mcp import sw_core, sw_feature  # noqa: E402


# --------------------------------------------------------------------------
# #5 direction
# --------------------------------------------------------------------------


class FakePoint:
    def __init__(self, xyz: list[float]) -> None:
        self.xyz = xyz

    def MultiplyTransform(self, transform: Any) -> "FakePoint":
        return FakePoint(transform.apply(self.xyz))

    @property
    def ArrayData(self) -> list[float]:
        return self.xyz


class FakeTransform:
    """Maps sketch space to model space: sketch +Z points along ``normal`` (rows are not used)."""

    def __init__(self, normal: list[float]) -> None:
        self.normal = normal

    def apply(self, p: list[float]) -> list[float]:
        return [c * p[2] for c in self.normal]

    @property
    def Inverse(self) -> "FakeTransform":
        return self


class FakeSketchObj:
    def __init__(self, normal: list[float]) -> None:
        self.ModelToSketchTransform = FakeTransform(normal)


class FakeSketchFeature:
    def __init__(self, normal: list[float]) -> None:
        self.GetSpecificFeature2 = FakeSketchObj(normal)


class FakeUtil:
    def CreatePoint(self, data: Any) -> FakePoint:
        return FakePoint([float(v) for v in getattr(data, "value", data)])


class FakeApp:
    GetMathUtility = FakeUtil()


class FakeFM:
    def __init__(self, returns_none_first: bool = False) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.none_first = returns_none_first

    def _make(self, name: str, args: tuple[Any, ...]) -> Any:
        self.calls.append((name, args))
        if self.none_first and len(self.calls) == 1:
            return None
        return object()

    def FeatureExtrusion3(self, *a: Any) -> Any:
        return self._make("FeatureExtrusion3", a)

    def FeatureCut4(self, *a: Any) -> Any:
        return self._make("FeatureCut4", a)


class DirectionMappingTests(unittest.TestCase):
    def test_mapping_table(self) -> None:
        # Live 2017: boss defaults +normal, cut defaults -normal, so the flags are opposite.
        self.assertEqual(
            {("boss", "+normal"): False, ("boss", "-normal"): True,
             ("cut", "+normal"): True, ("cut", "-normal"): False},
            dict(sw_feature.DIRECTION_REVERSE_FLAG),
        )

    def test_resolve(self) -> None:
        r = sw_feature.resolve_extrude_direction
        self.assertEqual((False, None), r("boss", {}))
        self.assertEqual((True, None), r("cut", {"reverse": True}))
        self.assertEqual((False, "+normal"), r("boss", {"direction": "+normal"}))
        self.assertEqual((True, "+normal"), r("cut", {"direction": "+normal"}))

    def test_conflict_and_bad_value(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "not both"):
            sw_feature.resolve_extrude_direction("cut", {"direction": "+normal", "reverse": False})
        with self.assertRaisesRegex(RuntimeError, "direction must be"):
            sw_feature.resolve_extrude_direction("boss", {"direction": "up"})

    def test_along_normal_is_inverse_of_table(self) -> None:
        for (kind, direction), flag in sw_feature.DIRECTION_REVERSE_FLAG.items():
            self.assertEqual(direction == "+normal", sw_feature.along_normal(kind, flag))

    def test_schemas_document_direction(self) -> None:
        by_name = {t.name: t for t in sw_core.TOOLS}
        for name in ("boss_extrude", "cut_extrude"):
            props = by_name[name].inputSchema["properties"]
            self.assertEqual(["+normal", "-normal"], props["direction"]["enum"])
            self.assertIn("+normal", by_name[name].description)
            self.assertNotIn("default", props["reverse"])


class ExtrudeRunTests(unittest.TestCase):
    def run_tool(self, fn: Any, args: dict[str, Any], fm: FakeFM, normal: list[float], volumes: list[float | None]) -> dict[str, Any]:
        doc = mock.MagicMock()
        vols = iter(volumes)
        patches = [
            mock.patch.object(sw_feature, "require_part", lambda: (FakeApp(), doc)),
            mock.patch.object(sw_feature, "select_sketch_for_feature", lambda d, n: "Sketch1"),
            mock.patch.object(sw_feature, "feature_manager", lambda d: fm),
            mock.patch.object(sw_feature, "dialogs_suppressed", lambda: mock.MagicMock()),
            mock.patch.object(sw_feature, "rename_feature", lambda f, n: None),
            mock.patch.object(sw_feature, "find_feature", lambda d, n: FakeSketchFeature(normal)),
            mock.patch.object(sw_feature, "_volume_mm3", lambda d: next(vols)),
            mock.patch.object(
                sw_feature, "feature_result",
                lambda d, f, a, **kw: sw_core.result(f is not None, a, **kw),
            ),
        ]
        for p in patches:
            p.start()
        try:
            return fn(args)
        finally:
            for p in patches:
                p.stop()

    def test_boss_plus_normal(self) -> None:
        fm = FakeFM()
        out = self.run_tool(sw_feature.boss_extrude, {"direction": "+normal"}, fm, [0, 0, 1], [100.0, 250.0])
        self.assertFalse(fm.calls[0][1][2])  # Dir flag
        self.assertEqual("+normal", out["data"]["direction"])
        self.assertEqual([0.0, 0.0, 1.0], out["data"]["direction_vector"])
        self.assertEqual(150.0, out["data"]["volume_delta_mm3"])

    def test_boss_minus_normal(self) -> None:
        fm = FakeFM()
        out = self.run_tool(sw_feature.boss_extrude, {"direction": "-normal"}, fm, [0, 0, 1], [100.0, 250.0])
        self.assertTrue(fm.calls[0][1][2])
        self.assertEqual([0.0, 0.0, -1.0], out["data"]["direction_vector"])

    def test_cut_plus_normal_sets_reverse_and_reports_plus_z(self) -> None:
        fm = FakeFM()
        out = self.run_tool(sw_feature.cut_extrude, {"direction": "+normal"}, fm, [0, 0, 1], [300.0, 200.0])
        self.assertTrue(fm.calls[0][1][2])
        self.assertEqual([0.0, 0.0, 1.0], out["data"]["direction_vector"])
        self.assertEqual(-100.0, out["data"]["volume_delta_mm3"])
        self.assertFalse(out["data"]["reversed_automatically"])

    def test_cut_default_goes_minus_normal(self) -> None:
        fm = FakeFM()
        out = self.run_tool(sw_feature.cut_extrude, {}, fm, [0, 0, 1], [300.0, 200.0])
        self.assertFalse(fm.calls[0][1][2])
        self.assertEqual("-normal", out["data"]["direction"])

    def test_cut_auto_reverse_is_reported_and_flips_vector(self) -> None:
        fm = FakeFM(returns_none_first=True)
        out = self.run_tool(sw_feature.cut_extrude, {}, fm, [0, 0, 1], [300.0, 200.0])
        self.assertEqual(2, len(fm.calls))
        self.assertTrue(out["data"]["reversed_automatically"])
        self.assertEqual("+normal", out["data"]["direction"])
        self.assertEqual([0.0, 0.0, 1.0], out["data"]["direction_vector"])
        self.assertIn("other way", out["message"])

    def test_explicit_direction_is_not_retried(self) -> None:
        fm = FakeFM(returns_none_first=True)
        out = self.run_tool(sw_feature.cut_extrude, {"direction": "-normal"}, fm, [0, 0, 1], [300.0, 300.0])
        self.assertEqual(1, len(fm.calls))
        self.assertFalse(out["ok"])
        self.assertIn("not retried", out["message"])

    def test_conflicting_args_never_reach_com(self) -> None:
        fm = FakeFM()
        with self.assertRaises(RuntimeError):
            self.run_tool(sw_feature.boss_extrude, {"direction": "+normal", "reverse": True}, fm, [0, 0, 1], [1.0, 2.0])
        self.assertEqual([], fm.calls)

    def test_symmetric_has_no_vector(self) -> None:
        fm = FakeFM()
        out = self.run_tool(sw_feature.boss_extrude, {"end_condition": "mid_plane"}, fm, [0, 0, 1], [1.0, 2.0])
        self.assertEqual("symmetric", out["data"]["direction"])
        self.assertIsNone(out["data"]["direction_vector"])

    def test_first_boss_missing_before_volume_counts_as_zero(self) -> None:
        fm = FakeFM()
        out = self.run_tool(sw_feature.boss_extrude, {}, fm, [0, 0, 1], [None, 500.0])
        self.assertEqual(0.0, out["data"]["volume_before_mm3"])
        self.assertEqual(500.0, out["data"]["volume_delta_mm3"])

    def test_unreadable_normal_and_volume_degrade_to_none(self) -> None:
        fm = FakeFM()
        with mock.patch.object(sw_feature, "_sketch_plane_normal", return_value=None):
            out = self.run_tool(sw_feature.boss_extrude, {}, fm, [0, 0, 1], [None, None])
        self.assertTrue(out["ok"])
        self.assertIsNone(out["data"]["direction_vector"])
        self.assertIsNone(out["data"]["volume_delta_mm3"])


# --------------------------------------------------------------------------
# Feature tree fakes for #8 and #9
# --------------------------------------------------------------------------


class Feat:
    def __init__(self, name: str, kind: str = "ProfileFeature", suppressed: bool = False) -> None:
        self.Name, self.GetTypeName2, self.suppressed = name, kind, suppressed
        self.tree: "Tree | None" = None
        self.children: list[str] = []

    def IsSuppressed2(self, option: int, names: Any) -> list[bool]:
        return [self.suppressed]

    def Select2(self, append: bool, mark: int) -> bool:
        self.tree.select(self, append)  # type: ignore[union-attr]
        return True


class Tree:
    """A feature list that acts as the document, its extension and its selection."""

    def __init__(self, feats: list[Feat], delete_works: bool = True, wrong_delete: str | None = None) -> None:
        self.feats = feats
        for f in feats:
            f.tree = self
        self.selected: list[Feat] = []
        self.preselected: list[Feat] = []
        self.delete_works, self.wrong_delete = delete_works, wrong_delete
        self.log: list[str] = []
        self.Extension = self
        self.GetActiveConfiguration = mock.MagicMock(Name="Default")

    def select(self, f: Feat, append: bool) -> None:
        self.log.append(f"Select2({append},{f.Name})")
        self.selected = (self.selected if append else []) + [f]

    def ClearSelection2(self, flag: bool) -> bool:
        self.log.append("ClearSelection2")
        self.selected = []
        return True

    def DeleteSelection2(self, opts: int) -> bool:
        self.log.append("DeleteSelection2")
        doomed = {f.Name for f in self.selected}
        if self.wrong_delete:
            doomed = {self.wrong_delete}
        if not self.delete_works:
            return False
        for f in list(self.selected):
            doomed.update(f.children)
        self.feats = [f for f in self.feats if f.Name not in doomed]
        return True

    def EditSuppress2(self) -> bool:
        return self._set(True)

    def EditUnsuppress2(self) -> bool:
        return self._set(False)

    def _set(self, state: bool) -> bool:
        for f in self.selected:
            f.suppressed = state
            for child in self.feats:
                if child.Name in f.children:
                    child.suppressed = state
        return True

    def EditRebuild3(self) -> bool:
        return True


def patch_tree(tree: Tree) -> list[Any]:
    patches = [
        mock.patch.object(sw_feature, "active_document", lambda: (None, tree)),
        mock.patch.object(sw_feature, "exit_active_sketch", lambda d: None),
        mock.patch.object(sw_feature, "iter_feature_objects", lambda d: list(tree.feats)),
        mock.patch.object(sw_feature, "iter_features", lambda d: [{"name": f.Name, "type": f.GetTypeName2} for f in tree.feats]),
        mock.patch.object(sw_feature, "whats_wrong", lambda d: []),
        mock.patch.object(sw_feature, "extension", lambda d: tree),
        mock.patch.object(sw_feature, "rebuild", lambda d: True),
        mock.patch.object(sw_feature, "clear_selection", lambda d: d.ClearSelection2(True)),
    ]
    for p in patches:
        p.start()
    return patches


class TreeTestCase(unittest.TestCase):
    def use(self, tree: Tree) -> Tree:
        for p in patch_tree(tree):
            self.addCleanup(p.stop)
        return tree


class DeleteFeatureTests(TreeTestCase):
    def test_clears_then_selects_without_append_and_reports(self) -> None:
        tree = self.use(Tree([Feat("Sketch1"), Feat("Base", "Extrusion"), Feat("Sketch2")]))
        tree.selected = [tree.feats[2]]  # stale selection from an earlier tool
        out = sw_feature.delete_feature({"feature_names": ["Sketch1"]})
        self.assertTrue(out["ok"], out)
        self.assertEqual(["ClearSelection2", "Select2(False,Sketch1)", "DeleteSelection2", "ClearSelection2"], tree.log[:4])
        self.assertEqual([{"name": "Sketch1", "type": "ProfileFeature"}], out["data"]["deleted"])
        self.assertEqual(3, out["data"]["feature_count_before"])
        self.assertEqual(2, out["data"]["feature_count_after"])
        self.assertEqual(["Sketch2", "Base"], sorted([f.Name for f in tree.feats], reverse=True))

    def test_second_feature_is_appended(self) -> None:
        tree = self.use(Tree([Feat("A"), Feat("B"), Feat("C")]))
        out = sw_feature.delete_feature({"feature_names": ["A", "B"]})
        self.assertTrue(out["ok"])
        self.assertEqual(["Select2(False,A)", "Select2(True,B)"], [e for e in tree.log if e.startswith("Select2")])

    def test_wrong_feature_deleted_is_failure(self) -> None:
        tree = self.use(Tree([Feat("Mine"), Feat("Empty")], wrong_delete="Empty"))
        out = sw_feature.delete_feature({"feature_names": ["Mine"]})
        self.assertFalse(out["ok"])
        self.assertEqual(["Mine"], out["data"]["still_present"])

    def test_dependents_reported(self) -> None:
        sketch = Feat("Sketch1")
        sketch.children = ["Boss"]
        tree = self.use(Tree([sketch, Feat("Boss", "Extrusion")]))
        out = sw_feature.delete_feature({"feature_names": ["Sketch1"]})
        self.assertTrue(out["ok"])
        self.assertEqual([{"name": "Boss", "type": "Extrusion"}], out["data"]["also_deleted"])

    def test_refused_delete(self) -> None:
        self.use(Tree([Feat("A")], delete_works=False))
        self.assertFalse(sw_feature.delete_feature({"feature_names": ["A"]})["ok"])

    def test_exact_name_beats_case_insensitive_and_ambiguity_is_refused(self) -> None:
        tree = self.use(Tree([Feat("sketch1"), Feat("Sketch1")]))
        out = sw_feature.delete_feature({"feature_names": ["Sketch1"]})
        self.assertTrue(out["ok"])
        self.assertEqual(["sketch1"], [f.Name for f in tree.feats])
        tree2 = self.use(Tree([Feat("sketch1"), Feat("SKETCH1")]))
        out2 = sw_feature.delete_feature({"feature_names": ["Sketch1"]})
        self.assertFalse(out2["ok"])
        self.assertEqual(2, len(tree2.feats))

    def test_unique_loose_match_and_unknown(self) -> None:
        self.use(Tree([Feat("Sketch1")]))
        self.assertTrue(sw_feature.delete_feature({"feature_names": ["sketch1 "]})["ok"])
        self.assertFalse(sw_feature.delete_feature({"feature_names": ["Nope"]})["ok"])


class SuppressionTests(TreeTestCase):
    def test_already_in_state_is_ok(self) -> None:
        tree = self.use(Tree([Feat("A", suppressed=True)]))
        out = sw_feature.set_feature_suppression({"feature_names": ["A"], "suppressed": True})
        self.assertTrue(out["ok"], out)
        self.assertTrue(out["data"]["already"])
        self.assertEqual([], out["data"]["changed"])
        self.assertEqual([], [e for e in tree.log if e.startswith("Select2")])

    def test_suppress_with_child_side_effect(self) -> None:
        parent = Feat("Parent", "Extrusion")
        parent.children = ["Child"]
        tree = self.use(Tree([Feat("Base"), parent, Feat("Child", "Fillet")]))
        out = sw_feature.set_feature_suppression({"feature_names": ["Parent"]})
        self.assertTrue(out["ok"], out)
        self.assertEqual(["Parent"], out["data"]["changed"])
        self.assertEqual([{"name": "Child", "suppressed": True}], out["data"]["side_effects"])
        self.assertFalse(tree.feats[0].suppressed)

    def test_unsuppress(self) -> None:
        tree = self.use(Tree([Feat("A", suppressed=True)]))
        out = sw_feature.set_feature_suppression({"feature_names": ["A"], "suppressed": False})
        self.assertTrue(out["ok"])
        self.assertFalse(tree.feats[0].suppressed)
        self.assertFalse(out["data"]["already"])

    def test_final_state_mismatch_fails(self) -> None:
        tree = self.use(Tree([Feat("A")]))
        with mock.patch.object(Tree, "_set", lambda self, state: True):  # API claims success, changes nothing
            out = sw_feature.set_feature_suppression({"feature_names": ["A"]})
        self.assertFalse(out["ok"])
        self.assertEqual(["A"], out["data"]["mismatched"])
        self.assertFalse(tree.feats[0].suppressed)

    def test_unknown_feature(self) -> None:
        self.use(Tree([Feat("A")]))
        self.assertFalse(sw_feature.set_feature_suppression({"feature_names": ["Z"]})["ok"])

    def test_is_suppressed_uses_isSuppressed2_with_active_config(self) -> None:
        seen: list[Any] = []

        class F:
            def IsSuppressed2(self, option: int, names: Any) -> list[bool]:
                seen.append((option, tuple(names.value)))
                return [True]

        doc = mock.MagicMock()
        doc.GetActiveConfiguration = mock.MagicMock(Name="Default")
        self.assertTrue(sw_feature._is_suppressed(doc, F()))
        self.assertEqual([(3, ("Default",))], seen)


# --------------------------------------------------------------------------
# #17 fillets
# --------------------------------------------------------------------------


class FilletFM:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def FeatureFillet3(self, *a: Any) -> Any:
        self.calls.append(a)
        return object()


class FilletTests(unittest.TestCase):
    def run_variant(self, args: dict[str, Any], selected: int = 1) -> tuple[dict[str, Any], FilletFM]:
        fm = FilletFM()
        patches = [
            mock.patch.object(sw_feature, "require_part", lambda: (None, mock.MagicMock())),
            mock.patch.object(sw_feature, "exit_active_sketch", lambda d: None),
            mock.patch.object(sw_feature, "require_selection", lambda d, s, mark=0, append=False: selected),
            mock.patch.object(sw_feature, "clear_selection", lambda d: None),
            mock.patch.object(sw_feature, "feature_manager", lambda d: fm),
            mock.patch.object(sw_feature, "dialogs_suppressed", lambda: mock.MagicMock()),
            mock.patch.object(sw_feature, "rename_feature", lambda f, n: None),
            mock.patch.object(sw_feature, "feature_result", lambda d, f, a, **kw: sw_core.result(f is not None, a, **kw)),
        ]
        for p in patches:
            p.start()
        try:
            return sw_feature.fillet_variant(args), fm
        finally:
            for p in patches:
                p.stop()

    def test_variable_chain_rejected_before_com(self) -> None:
        out, fm = self.run_variant(
            {"type": "variable", "selection": {"edges": [0, 1, 2]}, "radius_mm": 1, "end_radius_mm": 2}
        )
        self.assertFalse(out["ok"])
        self.assertIn("single edge", out["message"])
        self.assertEqual([], fm.calls)

    def test_variable_propagated_chain_rejected_after_selection(self) -> None:
        out, fm = self.run_variant(
            {"type": "variable", "selection": {"edges": [0]}, "radius_mm": 1, "end_radius_mm": 2}, selected=4
        )
        self.assertFalse(out["ok"])
        self.assertEqual([], fm.calls)

    def test_vertex_radii_refused(self) -> None:
        out, fm = self.run_variant(
            {"type": "variable", "selection": {"edges": [0]}, "radius_mm": 1, "end_radius_mm": 2, "vertex_radii": [1, 2]}
        )
        self.assertFalse(out["ok"])
        self.assertEqual([], fm.calls)

    def test_variable_single_edge_still_works(self) -> None:
        out, fm = self.run_variant(
            {"type": "variable", "selection": {"edges": [0]}, "radius_mm": 2, "end_radius_mm": 5}
        )
        self.assertTrue(out["ok"])
        self.assertEqual(1 | 4, fm.calls[0][0])

    def test_constant_fillet_option_bits(self) -> None:
        for propagate, expected in ((False, sw_core.FILLET_UNIFORM_RADIUS), (True, sw_core.FILLET_UNIFORM_RADIUS | 1)):
            fm = FilletFM()
            patches = [
                mock.patch.object(sw_feature, "require_part", lambda: (None, mock.MagicMock())),
                mock.patch.object(sw_feature, "exit_active_sketch", lambda d: None),
                mock.patch.object(sw_feature, "require_selection", lambda d, s, mark=0, append=False: 1),
                mock.patch.object(sw_feature, "feature_manager", lambda d: fm),
                mock.patch.object(sw_feature, "rename_feature", lambda f, n: None),
                mock.patch.object(sw_feature, "feature_result", lambda d, f, a, **kw: sw_core.result(True, a, **kw)),
            ]
            for p in patches:
                p.start()
            try:
                out = sw_feature.fillet({"radius_mm": 4, "selection": {"edges": [0]}, "propagate": propagate})
            finally:
                for p in patches:
                    p.stop()
            self.assertEqual(expected, fm.calls[0][0])
            self.assertEqual(expected, out["data"]["fillet_options"])
        self.assertEqual(2, sw_core.FILLET_UNIFORM_RADIUS)
        self.assertEqual(1, sw_core.FILLET_PROPAGATE)

    def test_fillet_description_documents_missing_tangent_bit(self) -> None:
        desc = {t.name: t.description for t in sw_core.TOOLS}["fillet"]
        self.assertIn("no separate tangent-propagation bit", desc)


if __name__ == "__main__":
    unittest.main()
