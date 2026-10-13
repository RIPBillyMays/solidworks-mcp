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

"""Offline tests for sw_core.register_flag_methods and sw_core.feature_data."""

from __future__ import annotations

import unittest

from solidworks_mcp import sw_core


class FlagRecorder:
    def __init__(self):
        self.flagged = []

    def _FlagAsMethod(self, name):
        self.flagged.append(name)


class FakeDoc:
    def __init__(self):
        self.FeatureManager = FlagRecorder()
        self.SketchManager = FlagRecorder()
        self.Extension = FlagRecorder()


class RegisterFlagMethodsTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: list(v) for k, v in sw_core._REGISTERED_FLAGS.items()}
        sw_core._REGISTERED_FLAGS.clear()

    def tearDown(self):
        sw_core._REGISTERED_FLAGS.clear()
        sw_core._REGISTERED_FLAGS.update(self._saved)

    def test_builtin_lists_unchanged_without_registration(self):
        fm = sw_core.feature_manager(FakeDoc())
        self.assertEqual(tuple(fm.flagged), sw_core._FEATURE_MANAGER_METHODS)

    def test_registered_names_are_merged(self):
        before = sw_core._FEATURE_MANAGER_METHODS
        sw_core.register_flag_methods("IFeatureManager", ["InsertSewRefSurface", "PreTrimSurface"])
        fm = sw_core.feature_manager(FakeDoc())
        self.assertEqual(tuple(fm.flagged), before + ("InsertSewRefSurface", "PreTrimSurface"))
        self.assertIs(sw_core._FEATURE_MANAGER_METHODS, before)

    def test_idempotent(self):
        sw_core.register_flag_methods("IFeatureManager", ["X"])
        sw_core.register_flag_methods("IFeatureManager", ["X", "Y"])
        self.assertEqual(sw_core._REGISTERED_FLAGS["IFeatureManager"], ["X", "Y"])

    def test_other_interfaces_unaffected(self):
        sw_core.register_flag_methods("IFeatureManager", ["OnlyFM"])
        doc = FakeDoc()
        self.assertEqual(tuple(sw_core.sketch_manager(doc).flagged), sw_core._SKETCH_MANAGER_METHODS)
        self.assertEqual(tuple(sw_core.extension(doc).flagged), sw_core._EXTENSION_METHODS)

    def test_extension_and_sketch_merge(self):
        sw_core.register_flag_methods("IModelDocExtension", ["E1"])
        sw_core.register_flag_methods("ISketchManager", ["S1"])
        doc = FakeDoc()
        self.assertEqual(sw_core.extension(doc).flagged[-1], "E1")
        self.assertEqual(sw_core.sketch_manager(doc).flagged[-1], "S1")

    def test_single_string_is_one_name(self):
        sw_core.register_flag_methods("IFeatureManager", "Abc")
        self.assertEqual(sw_core._REGISTERED_FLAGS["IFeatureManager"], ["Abc"])


class FakeData:
    def __init__(self, calls, access=True, access_raises=False):
        self.calls, self.access, self.access_raises = calls, access, access_raises

    def AccessSelections(self, doc, comp):
        self.calls.append(("access", doc, comp))
        if self.access_raises:
            raise RuntimeError("com boom")
        return self.access

    def ReleaseSelectionAccess(self):
        self.calls.append(("release",))


class FakeFeature:
    def __init__(self, calls, data, modify_ok=True):
        self.calls, self.data, self.modify_ok = calls, data, modify_ok

    def GetDefinition(self):
        self.calls.append(("get",))
        return self.data

    def ModifyDefinition(self, data, doc, comp):
        self.calls.append(("modify", data, doc, comp))
        return self.modify_ok


class FeatureDataTests(unittest.TestCase):
    def test_normal_path_order(self):
        calls = []
        data = FakeData(calls)
        with sw_core.feature_data(FakeFeature(calls, data), "DOC") as got:
            self.assertIs(got, data)
            calls.append(("edit",))
        self.assertEqual([c[0] for c in calls], ["get", "access", "edit", "modify", "release"])
        # The component arg is VT_DISPATCH in the typelib, so a typed null is passed.
        self.assertEqual(calls[1][:2], ("access", "DOC"))
        self.assertEqual((calls[1][2].varianttype, calls[1][2].value), (9, None))
        self.assertEqual(calls[3][:3], ("modify", data, "DOC"))
        self.assertEqual((calls[3][3].varianttype, calls[3][3].value), (9, None))

    def test_exception_releases_and_skips_modify(self):
        calls = []
        with self.assertRaises(ValueError):
            with sw_core.feature_data(FakeFeature(calls, FakeData(calls)), "DOC"):
                raise ValueError("caller failed")
        self.assertEqual([c[0] for c in calls], ["get", "access", "release"])

    def test_access_refused_raises_without_release_or_modify(self):
        calls = []
        with self.assertRaises(RuntimeError):
            with sw_core.feature_data(FakeFeature(calls, FakeData(calls, access=False)), "DOC"):
                self.fail("body must not run")
        self.assertEqual([c[0] for c in calls], ["get", "access"])

    def test_access_raises_releases_defensively(self):
        calls = []
        with self.assertRaises(RuntimeError):
            with sw_core.feature_data(FakeFeature(calls, FakeData(calls, access_raises=True)), "DOC"):
                self.fail("body must not run")
        self.assertEqual([c[0] for c in calls], ["get", "access", "release"])

    def test_no_definition(self):
        calls = []
        with self.assertRaises(RuntimeError):
            with sw_core.feature_data(FakeFeature(calls, None), "DOC"):
                self.fail("body must not run")
        self.assertEqual([c[0] for c in calls], ["get"])

    def test_modify_failure_raises_and_still_releases(self):
        calls = []
        with self.assertRaises(RuntimeError):
            with sw_core.feature_data(FakeFeature(calls, FakeData(calls), modify_ok=False), "DOC"):
                pass
        self.assertEqual([c[0] for c in calls], ["get", "access", "modify", "release"])


if __name__ == "__main__":
    unittest.main()
