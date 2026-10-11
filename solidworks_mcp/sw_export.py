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

"""Export planning for SOLIDWORKS 2017: formats, options, and preference scoping.

Kept free of document I/O so it is unit-testable offline.  ``sw_file`` owns the
tools; this module decides what to write and which user preferences must be
flipped (and restored) around the save.  Export options in 2017 live in user
preferences rather than typed export-data objects, and preferences are global to
the SOLIDWORKS session, so every change is undone in ``PreferenceScope.restore``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .sw_core import flag_methods, logger

# Document types (swDocumentTypes_e).
PART, ASSEMBLY, DRAWING = 1, 2, 3

# swUserPreferenceIntegerValue_e / DoubleValue_e / Toggle_e ids, pinned to
# tools/compat/sw2017_enums.txt by tests/test_sw2017_batchA_export.py.
PREF_STEP_AP = 75
PREF_STL_QUALITY = 78
PREF_STL_UNITS = 211
PREF_VRML_UNITS = 212
PREF_VRML_VERSION = 384
PREF_STL_DEVIATION = 2  # double, swSTLDeviation
PREF_STL_ANGLE = 3  # double, swSTLAngleTolerance
TOGGLE_STL_BINARY = 69
TOGGLE_STL_DONT_TRANSLATE = 71
TOGGLE_STL_ONE_FILE = 72
TOGGLE_VRML_ONE_FILE = 246

STL_QUALITY = {"coarse": 1, "fine": 2, "custom": 3}  # swSTLQuality_e
# swVrmlOutputVersion_e; live-verified: 1 writes "#VRML V2.0 utf8", 2 writes "#VRML V1.0 ascii".
VRML_VERSION = {"97": 1, "vrml97": 1, "2.0": 1, "01": 2, "1.0": 2, "vrml1": 2}

LENGTH_UNITS = {"mm": 0, "cm": 1, "m": 2, "in": 3, "inch": 3, "inches": 3}  # swLengthUnit_e
STEP_VERSIONS = {"AP203": 203, "AP214": 214}

_STL_OPTIONS = ("stl_format", "stl_quality", "deviation_mm", "angle_deg", "units", "single_file", "translate_to_positive")

# extension -> (label, document types that can be saved to it, supported options)
FORMATS: dict[str, tuple[str, set[int], tuple[str, ...]]] = {
    ".step": ("STEP", {PART, ASSEMBLY}, ("step_version",)),
    ".stp": ("STEP", {PART, ASSEMBLY}, ("step_version",)),
    ".iges": ("IGES", {PART, ASSEMBLY}, ()),
    ".igs": ("IGES", {PART, ASSEMBLY}, ()),
    ".x_t": ("Parasolid text", {PART, ASSEMBLY}, ()),
    ".x_b": ("Parasolid binary", {PART, ASSEMBLY}, ()),
    ".sat": ("ACIS SAT", {PART, ASSEMBLY}, ()),
    ".stl": ("STL", {PART, ASSEMBLY}, _STL_OPTIONS),
    ".3mf": ("3MF", {PART, ASSEMBLY}, ()),
    ".wrl": ("VRML", {PART, ASSEMBLY}, ("units", "vrml_version", "single_file")),
    ".eprt": ("eDrawings part", {PART}, ()),
    ".easm": ("eDrawings assembly", {ASSEMBLY}, ()),
    ".pdf": ("PDF (3D for parts/assemblies)", {PART, ASSEMBLY, DRAWING}, ("pdf_3d",)),
    ".png": ("PNG image of the view", {PART, ASSEMBLY, DRAWING}, ()),
    ".jpg": ("JPEG image of the view", {PART, ASSEMBLY, DRAWING}, ()),
    ".jpeg": ("JPEG image of the view", {PART, ASSEMBLY, DRAWING}, ()),
    ".tif": ("TIFF image of the view", {PART, ASSEMBLY, DRAWING}, ()),
    ".tiff": ("TIFF image of the view", {PART, ASSEMBLY, DRAWING}, ()),
    ".bmp": ("BMP image of the view", {PART, ASSEMBLY, DRAWING}, ()),
}
EXPORT_FILE_EXTENSIONS = set(FORMATS)

# Not 2017 SaveAs formats; reported instead of attempted.
UNSUPPORTED = {
    ".obj": "OBJ export arrived in later SOLIDWORKS releases; export STL and convert externally.",
    "AP242": "STEP AP242 needs IModelDocExtension.PublishSTEP242File and an MBD licence; not wired up.",
}

# Formats Extension.SaveAs writes for just the selected body (live-verified on 2017; .3mf ignores the selection).
BODY_FORMATS = {".x_t", ".x_b", ".step", ".stp", ".sat", ".iges", ".igs", ".stl"}

OPTION_KEYS = {
    "step_version", "stl_format", "stl_quality", "deviation_mm", "angle_deg", "units",
    "single_file", "translate_to_positive", "vrml_version", "pdf_3d",
}


@dataclass
class ExportPlan:
    extension: str
    int_prefs: list[tuple[int, int]] = field(default_factory=list)
    toggle_prefs: list[tuple[int, bool]] = field(default_factory=list)
    double_prefs: list[tuple[int, float]] = field(default_factory=list)
    pdf_3d: bool = False
    configuration: str | None = None

    @property
    def has_preferences(self) -> bool:
        return bool(self.int_prefs or self.toggle_prefs or self.double_prefs)


def _choice(name: str, raw: Any, table: dict[str, int]) -> int:
    key = str(raw).strip().lower()
    if key not in table:
        raise ValueError(f"{name} must be one of {sorted(table)}; got {raw!r}.")
    return table[key]


def plan_export(extension: str, args: dict[str, Any], doc_type: int) -> ExportPlan:
    """Validate ``args`` against the format and build the preference changes.

    Raises ``ValueError`` with a user-facing message for anything unsupported, so
    a typo never silently produces a default-settings file.
    """
    ext = extension.lower()
    if ext not in FORMATS:
        raise ValueError(UNSUPPORTED.get(ext, f"Unsupported export format {ext}. See list_export_formats."))
    label, doc_types, supported = FORMATS[ext]
    if doc_type and doc_type not in doc_types:
        raise ValueError(f"{label} export is not available for this document type.")
    for key in sorted(OPTION_KEYS):
        if args.get(key) is not None and key not in supported:
            raise ValueError(f"Option '{key}' is not supported for {label} (supported: {list(supported) or 'none'}).")

    plan = ExportPlan(extension=ext, configuration=args.get("configuration") or None)

    if args.get("step_version") is not None:
        version = str(args["step_version"]).strip().upper()
        if version == "AP242":
            raise ValueError(UNSUPPORTED["AP242"])
        if version not in STEP_VERSIONS:
            raise ValueError(f"step_version must be AP203 or AP214; got {args['step_version']!r}.")
        plan.int_prefs.append((PREF_STEP_AP, STEP_VERSIONS[version]))

    if ext == ".stl":
        if args.get("stl_format") is not None:
            fmt = str(args["stl_format"]).strip().lower()
            if fmt not in ("binary", "ascii"):
                raise ValueError("stl_format must be 'binary' or 'ascii'.")
            plan.toggle_prefs.append((TOGGLE_STL_BINARY, fmt == "binary"))
        quality = args.get("stl_quality")
        custom = args.get("deviation_mm") is not None or args.get("angle_deg") is not None
        if custom and quality is None:
            quality = "custom"
        if quality is not None:
            code = _choice("stl_quality", quality, STL_QUALITY)
            if custom and code != STL_QUALITY["custom"]:
                raise ValueError("deviation_mm/angle_deg require stl_quality 'custom'.")
            plan.int_prefs.append((PREF_STL_QUALITY, code))
        if args.get("deviation_mm") is not None:
            deviation = float(args["deviation_mm"])
            if not deviation > 0:
                raise ValueError("deviation_mm must be positive.")
            plan.double_prefs.append((PREF_STL_DEVIATION, deviation / 1000.0))  # metres
        if args.get("angle_deg") is not None:
            angle = float(args["angle_deg"])
            if not 0 < angle <= 180:
                raise ValueError("angle_deg must be in (0, 180].")
            plan.double_prefs.append((PREF_STL_ANGLE, math.radians(angle)))
        if args.get("translate_to_positive") is not None:
            plan.toggle_prefs.append((TOGGLE_STL_DONT_TRANSLATE, not bool(args["translate_to_positive"])))
        if args.get("single_file") is not None:
            plan.toggle_prefs.append((TOGGLE_STL_ONE_FILE, bool(args["single_file"])))
        if args.get("units") is not None:
            plan.int_prefs.append((PREF_STL_UNITS, _choice("units", args["units"], LENGTH_UNITS)))

    if ext == ".wrl":
        if args.get("units") is not None:
            plan.int_prefs.append((PREF_VRML_UNITS, _choice("units", args["units"], LENGTH_UNITS)))
        if args.get("vrml_version") is not None:
            plan.int_prefs.append((PREF_VRML_VERSION, _choice("vrml_version", args["vrml_version"], VRML_VERSION)))
        if args.get("single_file") is not None:
            plan.toggle_prefs.append((TOGGLE_VRML_ONE_FILE, bool(args["single_file"])))

    if ext == ".pdf" and doc_type in (PART, ASSEMBLY):
        plan.pdf_3d = bool(args.get("pdf_3d", True))
    return plan


class PreferenceScope:
    """Set SOLIDWORKS user preferences and put every one back afterwards."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self._undo: list[tuple[str, int, Any]] = []
        self.applied: list[dict[str, Any]] = []
        self._stl_quality: tuple[int, float, float] | None = None
        flag_methods(
            app,
            "SetUserPreferenceIntegerValue", "GetUserPreferenceIntegerValue",
            "SetUserPreferenceDoubleValue", "GetUserPreferenceDoubleValue",
            "SetUserPreferenceToggle", "GetUserPreferenceToggle",
        )

    def _snapshot_stl_quality(self) -> None:
        # Quality, deviation and angle are coupled: picking coarse/fine rewrites the two doubles,
        # and quality "custom" cannot be set directly (it is entered by setting a double).
        if self._stl_quality is None:
            self._stl_quality = (
                int(self.app.GetUserPreferenceIntegerValue(PREF_STL_QUALITY)),
                float(self.app.GetUserPreferenceDoubleValue(PREF_STL_DEVIATION)),
                float(self.app.GetUserPreferenceDoubleValue(PREF_STL_ANGLE)),
            )

    def apply(self, plan: ExportPlan) -> None:
        if any(p == PREF_STL_QUALITY for p, _ in plan.int_prefs) or plan.double_prefs:
            self._snapshot_stl_quality()
        for pref, new in plan.int_prefs:
            old = int(self.app.GetUserPreferenceIntegerValue(pref))
            self._undo.append(("IntegerValue", pref, old))
            self.app.SetUserPreferenceIntegerValue(pref, new)
            self.applied.append({"pref": pref, "kind": "int", "was": old, "now": new})
        for pref, new in plan.double_prefs:
            old = float(self.app.GetUserPreferenceDoubleValue(pref))
            self._undo.append(("DoubleValue", pref, old))
            self.app.SetUserPreferenceDoubleValue(pref, new)
            self.applied.append({"pref": pref, "kind": "double", "was": old, "now": new})
        for pref, new in plan.toggle_prefs:
            old = bool(self.app.GetUserPreferenceToggle(pref))
            self._undo.append(("Toggle", pref, old))
            self.app.SetUserPreferenceToggle(pref, new)
            self.applied.append({"pref": pref, "kind": "toggle", "was": old, "now": new})

    def restore(self) -> list[str]:
        """Undo in reverse order; returns descriptions of any that failed."""
        failures: list[str] = []
        stl_group = {PREF_STL_QUALITY, PREF_STL_DEVIATION, PREF_STL_ANGLE}
        for kind, pref, old in reversed(self._undo):
            if self._stl_quality is not None and pref in stl_group and kind != "Toggle":
                continue  # restored as a group below
            try:
                if kind == "IntegerValue" and pref == PREF_VRML_VERSION and old == 0:
                    old = VRML_VERSION["01"]  # an unset version is not accepted back and exports VRML 1.0 anyway
                getattr(self.app, f"SetUserPreference{kind}")(pref, old)
                if kind == "IntegerValue" and int(self.app.GetUserPreferenceIntegerValue(pref)) != old:
                    failures.append(f"{kind} {pref} did not read back as {old}")
            except Exception as exc:
                logger.warning("Could not restore user preference %s %s: %s", kind, pref, exc)
                failures.append(f"{kind} {pref}")
        if self._stl_quality is not None:
            quality, deviation, angle = self._stl_quality
            try:
                if quality in (STL_QUALITY["coarse"], STL_QUALITY["fine"]):
                    self.app.SetUserPreferenceIntegerValue(PREF_STL_QUALITY, quality)
                else:
                    self.app.SetUserPreferenceDoubleValue(PREF_STL_DEVIATION, deviation)
                    self.app.SetUserPreferenceDoubleValue(PREF_STL_ANGLE, angle)
            except Exception as exc:
                logger.warning("Could not restore STL quality: %s", exc)
                failures.append("STL quality")
            self._stl_quality = None
        self._undo.clear()
        return failures


def format_catalog() -> list[dict[str, Any]]:
    names = {PART: "part", ASSEMBLY: "assembly", DRAWING: "drawing"}
    return [
        {
            "extension": ext,
            "format": label,
            "documents": [names[t] for t in sorted(doc_types)],
            "options": list(options) + ["configuration"],
        }
        for ext, (label, doc_types, options) in sorted(FORMATS.items())
    ]
