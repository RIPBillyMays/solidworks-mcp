# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
from solidworks_mcp import sw_dome as dome


def geometry(**changes):
    return {"input_geometry": {"solid_volume_mm3": 100}, "solid_volume_mm3": 110,
            "reverse_direction": False, "has_constraint": False, "height_mm": 5,
            "center_probes": [{"normal_displacement_mm": 5}], **changes}


class DomeContracts(unittest.TestCase):
    def test_invalid_inputs_do_not_access_com(self):
        for changes in ({"height_mm": 0}, {"height_mm": float("nan")}, {"face_index": -1},
                        {"face_indices": [0, 0]}, {"reverse_direction": 1}, {"elliptical": 1},
                        {"direction_edge_index": True},
                        {"constraint_selection": {"sketch_name": "Apex", "sketch_points": [0]}}):
            with patch.object(dome, "require_part") as part:
                with self.assertRaises(RuntimeError):
                    dome.dome({"height_mm": 5, "face_index": 0, **changes})
                part.assert_not_called()

    def test_void_creation_recovers_feature_and_uses_native_units(self):
        create = Mock(return_value=None)
        doc = SimpleNamespace(InsertDome=create)
        info = geometry(input_face_count=1, elliptical=False)
        with ExitStack() as stack:
            for name, returned in (("require_part", (None, doc)), ("_feature_names", []),
                                   ("_feature_created_after", "recovered"), ("_dome_info", info)):
                stack.enter_context(patch.object(dome, name, return_value=returned))
            for name in ("exit_active_sketch", "clear_selection"):
                stack.enter_context(patch.object(dome, name))
            select = stack.enter_context(patch.object(dome, "require_selection"))
            stack.enter_context(patch.object(dome, "_finish", return_value={"ok": True, "data": {"feature": "recovered"}}))
            payload = dome.dome({"height_mm": 5, "face_index": 2})
        create.assert_called_once_with(.005, False, False)
        select.assert_called_once_with(doc, {"faces": [2]}, mark=1)
        self.assertTrue(payload["ok"])

    def test_zero_effect_and_incorrect_height_are_unconfirmed(self):
        for info in (geometry(solid_volume_mm3=100), geometry(center_probes=[]),
                     geometry(center_probes=[{"normal_displacement_mm": 8.888}]),
                     geometry(ellipsoid_check={"confirmed": False})):
            self.assertFalse(dome._geometry_confirmed(info)[1])

    def test_concave_requires_negative_volume_and_displacement(self):
        self.assertTrue(dome._geometry_confirmed(geometry(reverse_direction=True, solid_volume_mm3=90,
                            center_probes=[{"normal_displacement_mm": -5}]))[1])
        self.assertFalse(dome._geometry_confirmed(geometry(reverse_direction=True))[1])

    def test_constraint_controls_height_when_native_height_is_zero(self):
        for gap, expected in ((.001, True), (.1, False), (None, False)):
            self.assertEqual(dome._geometry_confirmed(geometry(has_constraint=True, height_mm=0,
                                 constraint_surface_gap_mm=gap))[1], expected)

    def test_rollback_is_released_before_output_geometry(self):
        events = []
        data = SimpleNamespace(AccessSelections=lambda *a: True, GetFaceCount=lambda: 0, Faces=[],
                               Height=.005, ReverseDir=False, Elliptical=False, Direction=None,
                               ConstraintPointOrSketch=None, ReleaseSelectionAccess=lambda: events.append("release"))
        feature = SimpleNamespace(GetTypeName2=lambda: "Dome", GetDefinition=lambda: data, GetFaces=lambda: [])
        with patch.object(dome, "_geometry", side_effect=lambda d: events.append("geometry") or {}):
            dome._dome_info("doc", feature)
        self.assertEqual(events, ["geometry", "release", "geometry"])

    def test_face_count_error_still_releases_rollback(self):
        released = Mock()
        data = SimpleNamespace(AccessSelections=lambda *a: True, GetFaceCount=lambda: 1,
                               Faces=[], ReleaseSelectionAccess=lambda: released())
        feature = SimpleNamespace(GetTypeName2=lambda: "Dome", GetDefinition=lambda: data)
        with self.assertRaisesRegex(RuntimeError, "references differ"):
            dome._dome_info("doc", feature)
        released.assert_called_once()

    def test_unsupported_boundary_cannot_prove_ellipsoid(self):
        self.assertIsNone(dome._ellipsoid_queries(SimpleNamespace(GetEdges=lambda: []), 5, False))

    def test_failed_edit_releases_native_selection_access(self):
        released = Mock()
        data = SimpleNamespace(AccessSelections=lambda *a: True, ReleaseSelectionAccess=lambda: released())
        feature = SimpleNamespace(GetDefinition=lambda: data, ModifyDefinition=lambda *a: False)
        info = geometry()
        with ExitStack() as stack:
            for name, returned in (("require_part", (None, "doc")), ("find_feature", feature),
                                   ("_dome_info", info), ("whats_wrong", [])):
                stack.enter_context(patch.object(dome, name, return_value=returned))
            for name in ("exit_active_sketch", "clear_selection", "rebuild"):
                stack.enter_context(patch.object(dome, name))
            payload = dome.set_dome_parameters({"name": "Dome", "height_mm": 5})
        released.assert_called_once()
        self.assertFalse(payload["ok"])

    def test_constraint_requires_exactly_one_named_sketch_point(self):
        for spec in ({"sketch_name": "A", "sketch_points": []},
                     {"sketch_name": "A", "sketch_points": [0, 1]},
                     {"sketch_name": "", "sketch_points": [0]},
                     {"sketch_name": "A", "sketch_points": [True]}):
            with patch.object(dome, "require_part") as part:
                with self.assertRaises(RuntimeError):
                    dome.set_dome_parameters({"name": "Dome", "constraint_selection": spec})
                part.assert_not_called()


if __name__ == "__main__":
    unittest.main()
