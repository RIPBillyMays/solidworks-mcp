# Copyright 2026 JIALE LIU
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
# Modified for SOLIDWORKS 2017 support (fork).

"""Document data tools (fork addition, Phase 5 batch B): configurations, equations
and global variables, custom properties, mass-property overrides and document units.

All of them work on the active part or assembly.  Enum values are pinned to the
2017 type library in ``tests/test_sw2017_batchB_docdata.py``.  Anything that
changes a model rebuilds it, and a rebuild error can raise a modal box that
blocks COM forever, so mutating tools run inside ``dialogs_suppressed``.
"""

from __future__ import annotations

import re
from typing import Any, Final

import pythoncom
import win32com.client

from .sw_core import (
    active_document,
    as_list,
    clear_selection,
    dialogs_suppressed,
    document_type,
    empty_variant,
    exit_active_sketch,
    extension,
    find_feature,
    flag_methods,
    rebuild,
    result,
    safe,
    to_m,
    to_rad,
    tool,
    value,
)

# swInConfigurationOpts_e
CFG_THIS, CFG_ALL, CFG_SPECIFIC = 1, 2, 3
SCOPES = {"this": CFG_THIS, "all": CFG_ALL, "specified": CFG_SPECIFIC}
# swSetValueInConfiguration_e (a different enum from the one above: this = 1, all = 2, specific = 3
# happen to coincide in 2017, but they are separate types)
SET_VALUE_SCOPES = {"this": 1, "all": 2, "specified": 3}
# swConfigurationOptions2_e
CFG_OPT_DONT_ACTIVATE = 128
# swFeatureSuppressionAction_e
SUPPRESS_FEATURE, UNSUPPRESS_FEATURE = 0, 1
# swCustomInfoType_e
# Live 2017: Add3 refuses swCustomInfoNumber (3) with status 1; swCustomInfoDouble (5) is accepted and
# stored (and read back by GetType2) as number (3), so "number" is written as 5.
PROPERTY_TYPES = {"text": 30, "number": 3, "double": 5, "date": 64, "yesno": 11}
PROPERTY_TYPE_NAMES = {v: k for k, v in PROPERTY_TYPES.items()}
ADD_AS_TYPE: Final = {"number": 5}  # type actually passed to Add3 when it differs from the enum
PROP_REPLACE_VALUE = 2  # swCustomPropertyAddOption_e.swCustomPropertyReplaceValue
# swUserPreferenceIntegerValue_e
PREF_UNIT_LINEAR = 47
PREF_UNIT_LINEAR_DECIMALS = 49
PREF_UNIT_ANGULAR = 51
PREF_UNIT_ANGULAR_DECIMALS = 52
PREF_UNIT_SYSTEM = 263
PREF_MASS_LENGTH = 258
PREF_MASS_MASS = 259
PREF_MASS_VOLUME = 260
PREF_MASS_DECIMALS = 261
# swUnitSystem_e
UNIT_SYSTEMS = {"cgs": 1, "mks": 2, "ips": 3, "custom": 4, "mmgs": 5}
# swLengthUnit_e
LENGTH_UNITS = {"mm": 0, "cm": 1, "m": 2, "in": 3, "ft": 4, "ft_in": 5, "um": 8, "mil": 9, "uin": 10}
# swAngleUnit_e
ANGLE_UNITS = {"degrees": 0, "deg_min": 1, "deg_min_sec": 2, "radians": 3}
# swUnitsMassPropMass_e
MASS_UNITS = {"mg": 1, "g": 2, "kg": 3, "lb": 4}
# swUnitsMassPropVolume_e
VOLUME_UNITS = {"mm3": 4, "cm3": 5, "m3": 6, "in3": 9, "ft3": 10, "l": 15}


def _inverse(table: dict[str, int]) -> dict[int, str]:
    return {v: k for k, v in table.items()}


def _model_doc() -> tuple[Any, Any]:
    app, doc = active_document()
    if document_type(doc) not in (1, 2):
        raise RuntimeError("This tool requires an active part or assembly document.")
    return app, doc


def _string_array(names: list[str]) -> Any:
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, tuple(str(n) for n in names))


def _scope_args(args: dict[str, Any], table: dict[str, int], default: str) -> tuple[str, int, list[str], Any]:
    """Resolve scope + configurations into (scope, enum value, names, COM argument)."""
    scope = str(args.get("scope", default)).lower()
    if scope not in table:
        raise ValueError(f"scope must be one of {sorted(table)}.")
    names = [str(n) for n in (args.get("configurations") or [])]
    if scope == "specified":
        if not names:
            raise ValueError("scope 'specified' needs a non-empty configurations list.")
        return scope, table[scope], names, _string_array(names)
    return scope, table[scope], [], empty_variant()


def configuration_names(doc: Any) -> list[str]:
    return [str(n) for n in as_list(value(doc, "GetConfigurationNames"))]


def active_configuration_name(doc: Any) -> str:
    cfg = value(doc, "GetActiveConfiguration")
    return str(safe(cfg, "Name", "") or "") if cfg is not None else ""


def _configuration(doc: Any, name: str) -> Any:
    return flag_methods(doc, "GetConfigurationByName").GetConfigurationByName(name)


def _check_configurations(doc: Any, wanted: list[str]) -> str | None:
    have = configuration_names(doc)
    missing = [n for n in wanted if n not in have]
    return f"No configuration named {missing}. Available: {have}." if missing else None


def _show(doc: Any, name: str) -> bool:
    shown = bool(flag_methods(doc, "ShowConfiguration2").ShowConfiguration2(name))
    # Live 2017: a configuration whose dimension changed while it was inactive shows stale
    # geometry until it is rebuilt (the dimension value is right, the body is not).
    rebuild(doc)
    return shown


def _describe_configuration(doc: Any, name: str, active: str) -> dict[str, Any]:
    cfg = _configuration(doc, name)
    info: dict[str, Any] = {"name": name, "active": name == active}
    if cfg is None:
        return info
    info["description"] = str(safe(cfg, "Description", "") or "")
    info["comment"] = str(safe(cfg, "Comment", "") or "")
    info["alternate_name"] = str(safe(cfg, "AlternateName", "") or "")
    info["derived"] = bool(safe(cfg, "IsDerived", False))
    parent = safe(cfg, "GetParent")
    info["parent"] = str(safe(parent, "Name", "") or "") if parent is not None else None
    return info


# --------------------------------------------------------------------------
# Configurations
# --------------------------------------------------------------------------


@tool(
    "list_configurations",
    "Read-only: list the configurations of the active part or assembly with description, comment, "
    "derived-from parent, and which one is active.",
    {},
)
def list_configurations(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = _model_doc()
    active = active_configuration_name(doc)
    items = [_describe_configuration(doc, n, active) for n in configuration_names(doc)]
    return result(True, f"{len(items)} configuration(s); active is '{active}'.", configurations=items, active=active)


@tool(
    "add_configuration",
    "Add a configuration to the active part or assembly. With parent set it becomes a derived "
    "configuration of that parent. The new configuration is not activated unless activate=true.",
    {
        "name": {"type": "string"},
        "description": {"type": "string", "default": ""},
        "comment": {"type": "string", "default": ""},
        "alternate_name": {"type": "string", "default": ""},
        "parent": {"type": "string", "description": "Parent configuration name; makes this a derived configuration."},
        "activate": {"type": "boolean", "default": False},
    },
    ["name"],
)
def add_configuration(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = _model_doc()
    name = str(args["name"]).strip()
    if not name:
        return result(False, "name must not be empty.")
    have = configuration_names(doc)
    if name in have:
        return result(False, f"Configuration '{name}' already exists.", configurations=have)
    parent = args.get("parent")
    if parent and parent not in have:
        return result(False, f"Parent configuration '{parent}' does not exist. Available: {have}.")
    previous = active_configuration_name(doc)
    activate = bool(args.get("activate", False))
    options = 0 if activate else CFG_OPT_DONT_ACTIVATE
    description = str(args.get("description", ""))
    comment = str(args.get("comment", ""))
    alternate = str(args.get("alternate_name", ""))
    with dialogs_suppressed(app):
        if parent:
            manager = flag_methods(doc.ConfigurationManager, "AddConfiguration")
            cfg = manager.AddConfiguration(name, comment, alternate, options, str(parent), description)
        else:
            cfg = flag_methods(doc, "AddConfiguration3").AddConfiguration3(name, comment, alternate, options)
            if cfg is not None and description:
                try:
                    cfg.Description = description
                except Exception:
                    pass
        after = configuration_names(doc)
        if name not in after:
            return result(False, f"SOLIDWORKS did not create configuration '{name}'.", configurations=after)
        if not activate and active_configuration_name(doc) != previous and previous:
            _show(doc, previous)
    return result(
        True,
        f"Added {'derived ' if parent else ''}configuration '{name}'.",
        name=name,
        parent=parent,
        active=active_configuration_name(doc),
        configurations=after,
    )


@tool(
    "activate_configuration",
    "Make a configuration of the active part or assembly the active one.",
    {"name": {"type": "string"}},
    ["name"],
)
def activate_configuration(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = _model_doc()
    name = str(args["name"])
    problem = _check_configurations(doc, [name])
    if problem:
        return result(False, problem)
    with dialogs_suppressed(app):
        shown = _show(doc, name)
    active = active_configuration_name(doc)
    # ShowConfiguration2 returns False when the configuration is already active (live 2017
    # finding), so the readback decides, not the return value.
    ok = active == name
    return result(ok, f"Activated '{name}'." if ok else f"Could not activate '{name}'; active is '{active}'.", active=active)


@tool(
    "delete_configuration",
    "Delete a configuration. The active configuration cannot be deleted, so when it is the target "
    "another configuration is activated first (switch_to, or the first other one). The last "
    "remaining configuration cannot be deleted.",
    {"name": {"type": "string"}, "switch_to": {"type": "string"}},
    ["name"],
)
def delete_configuration(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = _model_doc()
    name = str(args["name"])
    have = configuration_names(doc)
    problem = _check_configurations(doc, [name])
    if problem:
        return result(False, problem)
    if len(have) < 2:
        return result(False, "A document must keep at least one configuration.")
    others = [n for n in have if n != name]
    switched_to = None
    with dialogs_suppressed(app):
        if active_configuration_name(doc) == name:
            switched_to = str(args.get("switch_to") or others[0])
            if switched_to not in others:
                return result(False, f"switch_to '{switched_to}' is not another configuration. Available: {others}.")
            if not _show(doc, switched_to):
                return result(False, f"Could not activate '{switched_to}' to make '{name}' deletable.")
        deleted = bool(flag_methods(doc, "DeleteConfiguration2").DeleteConfiguration2(name))
    after = configuration_names(doc)
    ok = deleted and name not in after
    return result(
        ok,
        f"Deleted configuration '{name}'." if ok else f"SOLIDWORKS refused to delete '{name}'.",
        configurations=after,
        switched_to=switched_to,
        active=active_configuration_name(doc),
    )


@tool(
    "rename_configuration",
    "Rename a configuration of the active part or assembly.",
    {"name": {"type": "string"}, "new_name": {"type": "string"}},
    ["name", "new_name"],
)
def rename_configuration(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = _model_doc()
    name, new_name = str(args["name"]), str(args["new_name"]).strip()
    problem = _check_configurations(doc, [name])
    if problem:
        return result(False, problem)
    if not new_name or new_name in configuration_names(doc):
        return result(False, f"'{new_name}' is empty or already a configuration name.")
    cfg = _configuration(doc, name)
    try:
        cfg.Name = new_name
    except Exception as exc:
        return result(False, f"SOLIDWORKS rejected the rename: {exc}")
    after = configuration_names(doc)
    ok = new_name in after and name not in after
    return result(ok, f"Renamed '{name}' to '{new_name}'." if ok else "The rename did not take effect.", configurations=after)


@tool(
    "set_config_feature_suppression",
    "Suppress or unsuppress features in one configuration, several, or all (unlike "
    "set_feature_suppression, which only affects the active configuration). scope is "
    "this | all | specified; specified needs configurations[]. Reports the per-configuration state.",
    {
        "feature_names": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "suppressed": {"type": "boolean", "default": True},
        "scope": {"type": "string", "enum": list(SCOPES), "default": "this"},
        "configurations": {"type": "array", "items": {"type": "string"}},
    },
    ["feature_names"],
)
def set_config_feature_suppression(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = _model_doc()
    exit_active_sketch(doc)
    try:
        scope, option, names, names_arg = _scope_args(args, SCOPES, "this")
    except ValueError as exc:
        return result(False, str(exc))
    if names:
        problem = _check_configurations(doc, names)
        if problem:
            return result(False, problem)
    suppressed = bool(args.get("suppressed", True))
    action = SUPPRESS_FEATURE if suppressed else UNSUPPRESS_FEATURE
    changed: list[str] = []
    states: dict[str, Any] = {}
    check_names = names or (configuration_names(doc) if scope == "all" else [active_configuration_name(doc)])
    with dialogs_suppressed(app):
        for fname in args["feature_names"]:
            feature = find_feature(doc, str(fname))
            if feature is None:
                return result(False, f"No feature named '{fname}' exists in this document.", changed=changed)
            if bool(flag_methods(feature, "SetSuppression2").SetSuppression2(action, option, names_arg)):
                changed.append(str(fname))
            try:
                flags = as_list(flag_methods(feature, "IsSuppressed2").IsSuppressed2(CFG_SPECIFIC, _string_array(check_names)))
                states[str(fname)] = {c: bool(f) for c, f in zip(check_names, flags)}
            except Exception:
                states[str(fname)] = None
        rebuild(doc)
    clear_selection(doc)
    return result(
        len(changed) == len(args["feature_names"]),
        f"{'Suppressed' if suppressed else 'Unsuppressed'} {len(changed)} feature(s) ({scope}).",
        changed=changed,
        suppressed_by_configuration=states,
    )


@tool(
    "set_dimension_config",
    "Set a dimension value in this configuration, all configurations, or specific ones "
    "(set_dimension always writes to all). Linear values are millimetres, angular values degrees.",
    {
        "full_name": {"type": "string", "description": "For example 'D1@Sketch1'."},
        "value_mm": {"type": "number"},
        "value_deg": {"type": "number"},
        "scope": {"type": "string", "enum": list(SET_VALUE_SCOPES), "default": "this"},
        "configurations": {"type": "array", "items": {"type": "string"}},
    },
    ["full_name"],
)
def set_dimension_config(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = _model_doc()
    try:
        scope, option, names, names_arg = _scope_args(args, SET_VALUE_SCOPES, "this")
    except ValueError as exc:
        return result(False, str(exc))
    if names:
        problem = _check_configurations(doc, names)
        if problem:
            return result(False, problem)
    if args.get("value_mm") is not None:
        target, unit = to_m(args["value_mm"]), "value_mm"
    elif args.get("value_deg") is not None:
        target, unit = to_rad(args["value_deg"]), "value_deg"
    else:
        return result(False, "Pass value_mm or value_deg.")
    name = str(args["full_name"])
    dimension = flag_methods(doc, "Parameter").Parameter(name)
    if dimension is None:
        return result(False, f"No dimension named '{name}' exists. Call list_dimensions to see valid names.")
    if scope == "all":
        # Live 2017 finding: swSetValue_InAllConfigurations leaves a configuration-specific
        # value (set earlier with scope=specified) untouched, so name every configuration.
        option, names_arg = SET_VALUE_SCOPES["specified"], _string_array(configuration_names(doc))
    with dialogs_suppressed(app):
        code = int(flag_methods(dimension, "SetSystemValue3").SetSystemValue3(target, option, names_arg))
        rebuilt = rebuild(doc)
        if scope == "all":
            # Live 2017: a value set earlier for one configuration can survive the bulk call, so
            # check every configuration by activating it and set the stragglers one at a time.
            home = active_configuration_name(doc)
            for cfg in configuration_names(doc):
                _show(doc, cfg)
                current = flag_methods(doc, "Parameter").Parameter(name)
                if current is not None and abs(float(safe(current, "SystemValue", target) or 0.0) - target) > 1e-9:
                    flag_methods(current, "SetSystemValue3").SetSystemValue3(target, SET_VALUE_SCOPES["this"], empty_variant())
                    rebuild(doc)
            _show(doc, home)
            dimension = flag_methods(doc, "Parameter").Parameter(name)
    actual = float(safe(dimension, "SystemValue", target) or 0.0)
    # The readback is the active configuration's value, which is only meaningful when it was targeted.
    active = active_configuration_name(doc)
    targeted = scope == "all" or scope == "this" or active in names
    ok = code == 0 and (not targeted or abs(actual - target) < 1e-9)
    return result(
        ok,
        f"Set {name} ({scope})." if ok else f"SOLIDWORKS did not accept the value (status {code}).",
        status=code,
        scope=scope,
        configurations=names,
        active_configuration=active,
        rebuilt=rebuilt,
        **{unit: float(args[unit])},
    )


# --------------------------------------------------------------------------
# Equations and global variables
# --------------------------------------------------------------------------

_EQ_NAME = re.compile(r'^\s*"([^"]+)"\s*=')


def _equation_manager(doc: Any) -> Any:
    mgr = value(doc, "GetEquationMgr")
    if mgr is None:
        raise RuntimeError("SOLIDWORKS returned no equation manager for this document.")
    return flag_methods(mgr, "Equation", "Value", "GlobalVariable", "Add3", "Delete", "SetEquationAndConfigurationOption")


def _equation_name(text: str) -> str | None:
    match = _EQ_NAME.match(text or "")
    return match.group(1) if match else None


def _solver_status(mgr: Any) -> int:
    """EquationMgr.Status after a fresh evaluation.

    Live 2017: right after Add3 it reads -1 even for a good equation, and 1 (not 0) once
    everything solved, so only a negative value that survives re-evaluation is an error.
    """
    status = int(safe(mgr, "Status", 0) or 0)
    if status < 0:
        value(mgr, "EvaluateAll")
        status = int(safe(mgr, "Status", 0) or 0)
    return status


def _equation_rows(mgr: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(int(value(mgr, "GetCount"))):
        text = str(mgr.Equation(index) or "")
        try:
            val = float(mgr.Value(index))
        except Exception:
            val = None
        rows.append(
            {
                "index": index,
                "equation": text,
                "name": _equation_name(text),
                "global_variable": bool(safe_call(mgr, "GlobalVariable", index, False)),
                "value": val,
            }
        )
    return rows


def safe_call(obj: Any, member: str, arg: Any, default: Any = None) -> Any:
    try:
        return getattr(obj, member)(arg)
    except Exception:
        return default


def _find_equation(rows: list[dict[str, Any]], args: dict[str, Any]) -> dict[str, Any] | None:
    if args.get("index") is not None:
        return next((r for r in rows if r["index"] == int(args["index"])), None)
    wanted = args.get("name")
    return next((r for r in rows if wanted and r["name"] == str(wanted)), None)


@tool(
    "list_equations",
    "Read-only: list the equations and global variables of the active part or assembly with their "
    "evaluated values and the equation-solver status (0 = all solved). Values are in SOLIDWORKS "
    "system units as the API reports them (metres for lengths).",
    {"evaluate": {"type": "boolean", "default": True, "description": "Re-evaluate all equations first."}},
)
def list_equations(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = _model_doc()
    mgr = _equation_manager(doc)
    if bool(args.get("evaluate", True)):
        value(mgr, "EvaluateAll")
    rows = _equation_rows(mgr)
    status = _solver_status(mgr)
    return result(
        status >= 0,
        f"{len(rows)} equation(s); solver status {status}.",
        equations=rows,
        status=status,
        global_variables=[r["name"] for r in rows if r["global_variable"]],
    )


@tool(
    "add_equation",
    "Add an equation. Give exactly one form: global_variable + expression (creates "
    "'\"name\"= expression'), dimension_name + expression (drives '\"D1@Sketch1\"= expression'), or a "
    "raw equation string. Expressions are in document units unless they quote other variables "
    "(for example '\"width\" * 2'). scope is all (default) | this | specified.",
    {
        "global_variable": {"type": "string"},
        "dimension_name": {"type": "string"},
        "expression": {"type": "string"},
        "equation": {"type": "string", "description": "Raw equation text, used as given."},
        "scope": {"type": "string", "enum": list(SCOPES), "default": "all"},
        "configurations": {"type": "array", "items": {"type": "string"}},
    },
)
def add_equation(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = _model_doc()
    forms = [k for k in ("global_variable", "dimension_name", "equation") if args.get(k)]
    if len(forms) != 1:
        return result(False, "Pass exactly one of global_variable, dimension_name or equation.")
    if forms[0] != "equation" and not str(args.get("expression", "")).strip():
        return result(False, f"{forms[0]} needs an expression.")
    if forms[0] == "global_variable":
        text = f'"{args["global_variable"]}"= {args["expression"]}'
    elif forms[0] == "dimension_name":
        text = f'"{args["dimension_name"]}"= {args["expression"]}'
    else:
        text = str(args["equation"])
    try:
        _, option, names, names_arg = _scope_args(args, SCOPES, "all")
    except ValueError as exc:
        return result(False, str(exc))
    mgr = _equation_manager(doc)
    before = int(value(mgr, "GetCount"))
    with dialogs_suppressed(app):
        index = int(mgr.Add3(before, text, True, option, names_arg))
        value(mgr, "EvaluateAll")
        rebuild(doc)
    after = int(value(mgr, "GetCount"))
    status = _solver_status(mgr)
    if index < 0 or after != before + 1:
        return result(False, f"SOLIDWORKS did not accept the equation {text!r}.", equation=text, status=status)
    row = next((r for r in _equation_rows(mgr) if r["index"] == index), None)
    return result(
        row is not None,
        f"Added equation #{index}." if status >= 0 else f"Added equation #{index} (solver status {status}, row evaluated to {row and row.get('value')}).",
        index=index,
        equation=text,
        row=row,
        status=status,
    )


@tool(
    "edit_equation",
    "Replace the text of an existing equation, found by index or by its quoted left-hand name "
    "(a global variable or driven dimension). Pass the full new equation, or expression to keep the name.",
    {
        "index": {"type": "integer", "minimum": 0},
        "name": {"type": "string"},
        "expression": {"type": "string"},
        "equation": {"type": "string"},
        "scope": {"type": "string", "enum": list(SCOPES), "default": "all"},
        "configurations": {"type": "array", "items": {"type": "string"}},
    },
)
def edit_equation(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = _model_doc()
    mgr = _equation_manager(doc)
    row = _find_equation(_equation_rows(mgr), args)
    if row is None:
        return result(False, "No such equation. Give index or name (see list_equations).")
    if args.get("equation"):
        text = str(args["equation"])
    elif args.get("expression") and row["name"]:
        text = f'"{row["name"]}"= {args["expression"]}'
    else:
        return result(False, "Pass equation, or expression for a named equation.")
    try:
        _, option, names, names_arg = _scope_args(args, SCOPES, "all")
    except ValueError as exc:
        return result(False, str(exc))
    with dialogs_suppressed(app):
        mgr.SetEquationAndConfigurationOption(row["index"], text, option, names_arg)
        value(mgr, "EvaluateAll")
        rebuild(doc)
    now = next((r for r in _equation_rows(mgr) if r["index"] == row["index"]), None)
    status = _solver_status(mgr)
    changed = now is not None and now["equation"].replace(" ", "") == text.replace(" ", "")
    return result(
        changed,
        f"Edited equation #{row['index']}." if changed else "SOLIDWORKS did not apply the new equation text.",
        index=row["index"],
        old=row["equation"],
        row=now,
        status=status,
    )


@tool(
    "delete_equation",
    "Delete an equation or global variable by index or quoted name. A dimension it drove keeps its last value.",
    {
        "index": {"type": "integer", "minimum": 0},
        "name": {"type": "string"},
        "force": {"type": "boolean", "default": False, "description": "Delete a global variable even if other equations use it."},
    },
)
def delete_equation(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = _model_doc()
    mgr = _equation_manager(doc)
    row = _find_equation(_equation_rows(mgr), args)
    if row is None:
        return result(False, "No such equation. Give index or name (see list_equations).")
    if row.get("global_variable") and not args.get("force"):
        users = [r["equation"] for r in _equation_rows(mgr)
                 if r["index"] != row["index"] and f'"{row["name"]}"' in str(r["equation"]).split("=", 1)[-1]]
        if users:
            # A dangling reference leaves the model unsolved and later raises a Rebuild? modal on save.
            return result(False, f"Global variable '{row['name']}' is still used by {users}. Delete those first, or pass force=true.", used_by=users)
    before = int(value(mgr, "GetCount"))
    with dialogs_suppressed(app):
        mgr.Delete(row["index"])
        value(mgr, "EvaluateAll")
        rebuild(doc)
    after = int(value(mgr, "GetCount"))
    ok = after == before - 1
    return result(ok, f"Deleted equation '{row['equation']}'." if ok else "SOLIDWORKS did not delete the equation.", deleted=row, count=after)


# --------------------------------------------------------------------------
# Custom properties
# --------------------------------------------------------------------------


def _property_manager(doc: Any, configuration: str | None) -> Any:
    if configuration:
        problem = _check_configurations(doc, [configuration])
        if problem:
            raise ValueError(problem)
    mgr = flag_methods(extension(doc), "CustomPropertyManager").CustomPropertyManager(configuration or "")
    if mgr is None:
        raise RuntimeError("SOLIDWORKS returned no custom property manager.")
    return flag_methods(mgr, "Get4", "Add3", "Delete2", "Set2", "GetType2")


def _read_property(mgr: Any, name: str) -> dict[str, Any]:
    raw = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
    resolved = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, "")
    mgr.Get4(name, False, raw, resolved)
    type_code = safe_call(mgr, "GetType2", name)
    return {
        "name": name,
        "value": str(raw.value or ""),
        "resolved_value": str(resolved.value or ""),
        "type": PROPERTY_TYPE_NAMES.get(type_code, f"unknown ({type_code})"),
    }


@tool(
    "list_custom_properties",
    "Read-only: list custom properties with raw value, resolved value (links such as $PRP are "
    "expanded) and type. Without configuration it reads the file-level properties; with one it "
    "reads that configuration's properties.",
    {"configuration": {"type": "string", "description": "Configuration-specific properties; omit for file level."}},
)
def list_custom_properties(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = _model_doc()
    try:
        mgr = _property_manager(doc, args.get("configuration"))
    except ValueError as exc:
        return result(False, str(exc))
    items = [_read_property(mgr, str(n)) for n in as_list(value(mgr, "GetNames"))]
    return result(True, f"{len(items)} propert(ies).", properties=items, configuration=args.get("configuration") or None)


@tool(
    "set_custom_property",
    "Add or change a custom property. type is text (default) | number | double | date | yesno; "
    "yesno takes 'Yes'/'No'. Without configuration it writes the file-level property.",
    {
        "name": {"type": "string"},
        "value": {"type": "string"},
        "type": {"type": "string", "enum": list(PROPERTY_TYPES), "default": "text"},
        "configuration": {"type": "string"},
    },
    ["name", "value"],
)
def set_custom_property(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = _model_doc()
    kind = str(args.get("type", "text")).lower()
    if kind not in PROPERTY_TYPES:
        return result(False, f"type must be one of {sorted(PROPERTY_TYPES)}.")
    try:
        mgr = _property_manager(doc, args.get("configuration"))
    except ValueError as exc:
        return result(False, str(exc))
    name, text = str(args["name"]), str(args["value"])
    code = int(mgr.Add3(name, ADD_AS_TYPE.get(kind, PROPERTY_TYPES[kind]), text, PROP_REPLACE_VALUE))
    row = _read_property(mgr, name)
    ok = code == 0
    return result(
        ok,
        f"Set {name}." if ok else f"SOLIDWORKS refused the property (swCustomInfoAddResult {code}).",
        status=code,
        property=row,
        configuration=args.get("configuration") or None,
    )


@tool(
    "delete_custom_property",
    "Delete a custom property (file level, or configuration-specific when configuration is given).",
    {"name": {"type": "string"}, "configuration": {"type": "string"}},
    ["name"],
)
def delete_custom_property(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = _model_doc()
    try:
        mgr = _property_manager(doc, args.get("configuration"))
    except ValueError as exc:
        return result(False, str(exc))
    name = str(args["name"])
    code = int(mgr.Delete2(name))
    still = name in [str(n) for n in as_list(value(mgr, "GetNames"))]
    ok = code == 0 and not still
    message = f"Deleted {name}." if ok else (f"No property named '{name}'." if code == 1 else f"Could not delete '{name}'.")
    return result(ok, message, status=code)


# --------------------------------------------------------------------------
# Mass properties
# --------------------------------------------------------------------------


def _mass_snapshot(doc: Any) -> dict[str, Any]:
    prop = value(extension(doc), "CreateMassProperty")
    if prop is None:
        return {"error": "No mass properties (does the configuration contain a solid body?)."}
    mass_kg, volume_m3 = float(value(prop, "Mass")), float(value(prop, "Volume"))
    centre = [round(float(c) * 1000.0, 6) for c in (value(prop, "CenterOfMass") or [])]
    return {
        "mass_g": round(mass_kg * 1000.0, 6),
        "volume_mm3": round(volume_m3 * 1e9, 4),
        "surface_area_mm2": round(float(value(prop, "SurfaceArea")) * 1e6, 4),
        "density_g_per_cm3": round(mass_kg / volume_m3 / 1000.0, 6) if volume_m3 else None,
        "center_of_mass_mm": centre,
        "user_assigned": bool(safe(prop, "UserAssigned", False)),
    }


@tool(
    "get_configuration_mass_properties",
    "Read-only: mass, volume, surface area, density and centre of mass for each requested "
    "configuration (default all), in mm / g units. The active configuration is restored afterwards.",
    {"configurations": {"type": "array", "items": {"type": "string"}}},
)
def get_configuration_mass_properties(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = _model_doc()
    wanted = [str(n) for n in (args.get("configurations") or configuration_names(doc))]
    problem = _check_configurations(doc, wanted)
    if problem:
        return result(False, problem)
    original = active_configuration_name(doc)
    rows: dict[str, Any] = {}
    try:
        with dialogs_suppressed(app):
            for name in wanted:
                if name != active_configuration_name(doc) and not _show(doc, name):
                    rows[name] = {"error": "Could not activate this configuration."}
                    continue
                rows[name] = _mass_snapshot(doc)
    finally:
        if original and active_configuration_name(doc) != original:
            with dialogs_suppressed(app):
                _show(doc, original)
    ok = all("error" not in r for r in rows.values())
    return result(ok, f"Read mass properties for {len(rows)} configuration(s).", configurations=rows, active=active_configuration_name(doc))


@tool(
    "set_mass_override",
    "Assign a mass to the active configuration (override_mass_g), or clear an assigned mass "
    "(clear=true). SOLIDWORKS 2017 exposes no setter for density, so density_g_per_cm3 is only a "
    "what-if: the mass it would give for the current volume is returned and nothing is changed "
    "(use set_material to change density for real). The result states whether the override persisted.",
    {
        "override_mass_g": {"type": "number", "minimum": 0},
        "clear": {"type": "boolean", "default": False},
        "density_g_per_cm3": {"type": "number", "exclusiveMinimum": 0},
    },
)
def set_mass_override(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = _model_doc()
    before = _mass_snapshot(doc)
    if "error" in before:
        return result(False, before["error"])
    if args.get("density_g_per_cm3") is not None and args.get("override_mass_g") is None and not args.get("clear"):
        density = float(args["density_g_per_cm3"])
        return result(
            True,
            "What-if only: density cannot be overridden through the 2017 API. Nothing was changed.",
            applied=False,
            what_if_mass_g=round(density * before["volume_mm3"] / 1000.0, 6),
            current=before,
        )
    if args.get("override_mass_g") is None and not args.get("clear"):
        return result(False, "Pass override_mass_g, clear=true, or density_g_per_cm3 for a what-if.")
    prop = value(extension(doc), "CreateMassProperty")
    with dialogs_suppressed(app):
        if args.get("clear"):
            prop.OverrideMass = 0.0
            try:
                prop.UserAssigned = False
            except Exception:
                pass
        else:
            prop.OverrideMass = float(args["override_mass_g"]) / 1000.0
        rebuild(doc)
    after = _mass_snapshot(doc)
    target = 0.0 if args.get("clear") else float(args["override_mass_g"])
    if args.get("clear"):
        persisted = abs(after.get("mass_g", 0) - before["mass_g"]) < 1e-6 or not after.get("user_assigned")
    else:
        persisted = abs(after.get("mass_g", -1.0) - target) < max(1e-6, target * 1e-6)
    return result(
        persisted,
        "Mass override applied." if persisted else "The override did not persist in the document (it only affected the calculation object).",
        persisted=persisted,
        before=before,
        after=after,
    )


# --------------------------------------------------------------------------
# Document units
# --------------------------------------------------------------------------

_UNIT_PREFS = {
    "unit_system": PREF_UNIT_SYSTEM,
    "length_unit": PREF_UNIT_LINEAR,
    "length_decimals": PREF_UNIT_LINEAR_DECIMALS,
    "angle_unit": PREF_UNIT_ANGULAR,
    "angle_decimals": PREF_UNIT_ANGULAR_DECIMALS,
    "mass_length_unit": PREF_MASS_LENGTH,
    "mass_unit": PREF_MASS_MASS,
    "volume_unit": PREF_MASS_VOLUME,
    "mass_decimals": PREF_MASS_DECIMALS,
}


def _read_units(doc: Any) -> dict[str, Any]:
    flag_methods(doc, "GetUserPreferenceIntegerValue")
    raw = {k: doc.GetUserPreferenceIntegerValue(pref) for k, pref in _UNIT_PREFS.items()}
    return {
        "unit_system": _inverse(UNIT_SYSTEMS).get(raw["unit_system"], raw["unit_system"]),
        "length_unit": _inverse(LENGTH_UNITS).get(raw["length_unit"], raw["length_unit"]),
        "length_decimals": raw["length_decimals"],
        "angle_unit": _inverse(ANGLE_UNITS).get(raw["angle_unit"], raw["angle_unit"]),
        "angle_decimals": raw["angle_decimals"],
        "mass_length_unit": _inverse(LENGTH_UNITS).get(raw["mass_length_unit"], raw["mass_length_unit"]),
        "mass_unit": _inverse(MASS_UNITS).get(raw["mass_unit"], raw["mass_unit"]),
        "volume_unit": _inverse(VOLUME_UNITS).get(raw["volume_unit"], raw["volume_unit"]),
        "mass_decimals": raw["mass_decimals"],
    }


@tool(
    "get_document_units",
    "Read-only: the active document's unit system (mmgs, ips, mks, cgs, custom), length and angle "
    "units, decimal places and mass-property units.",
    {},
)
def get_document_units(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = _model_doc()
    return result(True, "Read document units.", units=_read_units(doc))


@tool(
    "set_document_units",
    "Set the active document's units (a document property, not restored afterwards). unit_system "
    "mmgs | ips | mks | cgs | custom; custom takes the individual unit arguments, which are also "
    "applied on top of a named system. Decimal places are 0-8. The result reads everything back.",
    {
        "unit_system": {"type": "string", "enum": list(UNIT_SYSTEMS)},
        "length_unit": {"type": "string", "enum": list(LENGTH_UNITS), "description": "Needs unit_system=custom."},
        "length_decimals": {"type": "integer", "minimum": 0, "maximum": 8},
        "angle_unit": {"type": "string", "enum": list(ANGLE_UNITS)},
        "angle_decimals": {"type": "integer", "minimum": 0, "maximum": 8},
        "mass_unit": {"type": "string", "enum": list(MASS_UNITS)},
        "volume_unit": {"type": "string", "enum": list(VOLUME_UNITS)},
        "mass_decimals": {"type": "integer", "minimum": 0, "maximum": 8},
    },
)
def set_document_units(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = _model_doc()
    plan: list[tuple[str, int]] = []
    tables = {"unit_system": UNIT_SYSTEMS, "length_unit": LENGTH_UNITS, "angle_unit": ANGLE_UNITS,
              "mass_unit": MASS_UNITS, "volume_unit": VOLUME_UNITS}
    for key in ("unit_system", "length_unit", "angle_unit", "mass_unit", "volume_unit"):
        if args.get(key) is not None:
            choice = str(args[key]).lower()
            if choice not in tables[key]:
                return result(False, f"{key} must be one of {sorted(tables[key])}.")
            plan.append((key, tables[key][choice]))
    for key in ("length_decimals", "angle_decimals", "mass_decimals"):
        if args.get(key) is not None:
            places = int(args[key])
            if not 0 <= places <= 8:
                return result(False, f"{key} must be between 0 and 8.")
            plan.append((key, places))
    if not plan:
        return result(False, "Pass at least one unit setting.")
    if args.get("length_unit") is not None and str(args.get("unit_system", "custom")).lower() != "custom":
        return result(False, "length_unit can only be set with unit_system=custom (a named system fixes it).")
    before = _read_units(doc)
    failed: list[str] = []
    flag_methods(doc, "SetUserPreferenceIntegerValue")
    with dialogs_suppressed(app):
        if args.get("length_unit") is not None and args.get("unit_system") is None:
            plan.insert(0, ("unit_system", UNIT_SYSTEMS["custom"]))
        for key, code in plan:
            if not bool(doc.SetUserPreferenceIntegerValue(_UNIT_PREFS[key], code)):
                failed.append(key)
        rebuild(doc)
    after = _read_units(doc)
    return result(
        not failed,
        "Updated document units." if not failed else f"SOLIDWORKS rejected: {failed}.",
        before=before,
        units=after,
        failed=failed,
    )
