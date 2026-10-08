# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
from solidworks_mcp import sw_wrap as wrap

ARGS = {"sketch_name": "Profile", "face_index": 0}


class WrapContracts(unittest.TestCase):
    def test_invalid_arguments_never_touch_com(self):
        for change in ({"mode": "other"}, {"method": "other"}, {"thickness_mm": float("nan")},
                       {"thickness_mm": .001}, {"mesh_factor": True}, {"mesh_factor": 11},
                       {"face_index": -1}, {"sketch_name": " "}):
            with patch.object(wrap, "require_part") as part:
                with self.assertRaises(RuntimeError): wrap.wrap_sketch({**ARGS, **change})
                part.assert_not_called()

    def setup_calls(self, stack, manager, delta=2, faces=8):
        info = {"mode": "emboss", "source_sketch": "Profile", "has_target_face": True,
                "reverse_direction": False, "has_pull_direction": False, "thickness_mm": 1,
                "solid_volume_mm3": 100 + delta, "solid_face_count": faces}
        for name, returned in {"require_part": (None, "doc"), "feature_manager": manager,
                               "_feature_names": [], "_feature_created_after": "recovered", "_wrap_info": info,
                               "_geometry": {"solid_volume_mm3": 100, "solid_face_count": 3}}.items():
            stack.enter_context(patch.object(wrap, name, return_value=returned))
        for name in ("exit_active_sketch", "clear_selection"):
            stack.enter_context(patch.object(wrap, name))
        stack.enter_context(patch.object(wrap, "_finish", side_effect=lambda *a: {"ok": True, "data": {"feature": a[1]}}))
        return stack.enter_context(patch.object(wrap, "require_selection", return_value=1))

    def test_marks_units_and_void_feature_recovery(self):
        create = Mock(return_value=None)
        with ExitStack() as stack:
            select = self.setup_calls(stack, SimpleNamespace(InsertWrapFeature2=create))
            payload = wrap.wrap_sketch(ARGS)
        create.assert_called_once_with(0, .001, False, 0, 5)
        self.assertEqual([c.kwargs["mark"] for c in select.call_args_list], [4, 1])
        self.assertTrue(select.call_args_list[1].kwargs["append"])
        self.assertEqual(payload["data"]["feature"], "recovered")
        self.assertTrue(payload["ok"])

    def test_legacy_rejects_spline_before_mutation(self):
        create = Mock()
        with ExitStack() as stack:
            select = self.setup_calls(stack, SimpleNamespace(InsertWrapFeature=create))
            with self.assertRaisesRegex(RuntimeError, "older method"):
                wrap.wrap_sketch({**ARGS, "method": "spline"})
            select.assert_not_called(); create.assert_not_called()
            wrap.wrap_sketch(ARGS)
        create.assert_called_once_with(0, .001, False)

    def test_modern_errors_are_not_retried(self):
        legacy = Mock()
        with ExitStack() as stack:
            self.setup_calls(stack, SimpleNamespace(InsertWrapFeature2=Mock(side_effect=RuntimeError("native failure")), InsertWrapFeature=legacy))
            with self.assertRaisesRegex(RuntimeError, "native failure"): wrap.wrap_sketch(ARGS)
        legacy.assert_not_called()

    def test_non_effective_feature_is_preserved_as_failure(self):
        with ExitStack() as stack:
            self.setup_calls(stack, SimpleNamespace(InsertWrapFeature2=lambda *a: "feature"), delta=0)
            payload = wrap.wrap_sketch(ARGS)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["data"]["feature"], "feature")

    def test_geometry_read_after_releasing_rollback(self):
        events = []
        definition = SimpleNamespace(AccessSelections=lambda *a: True, ReleaseSelectionAccess=lambda: events.append("release"),
                                     SourceSketch=SimpleNamespace(Name="Profile"), Type=2, Thickness=.001,
                                     ReverseDirection=False, Face=object(), PullDirection=None)
        feature = SimpleNamespace(GetTypeName2=lambda: "Emboss", GetDefinition=lambda: definition, GetFaces=lambda: [])
        with patch.object(wrap, "_geometry", side_effect=lambda d: events.append("geometry") or {}):
            info = wrap._wrap_info("doc", feature)
        self.assertEqual(events, ["release", "geometry"])
        self.assertEqual(info["mode"], "scribe")
        self.assertIn("method", info["unreadable_parameters"])


if __name__ == "__main__":
    unittest.main()
