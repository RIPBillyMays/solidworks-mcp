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

"""Session status, document lifecycle, saving, exporting, and appearance."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pythoncom
import win32com.client

from . import sw_export
from .sw_core import (
    as_list,
    active_document,
    byref_long,
    clear_selection,
    document_info,
    document_type,
    dialogs_suppressed,
    double_array,
    EXPORT_EXTENSIONS,
    extension,
    flag_methods,
    get_bodies,
    iter_components,
    invoke_no_arg,
    logger,
    stamp_active_document,
    nothing,
    OUTPUT_ROOT,
    rebuild,
    require_part,
    select_by_id,
    result,
    running_app,
    safe,
    discover_template,
    tool,
    value,
    whats_wrong,
)


# User-preference string ids for the default templates (swUserPreferenceStringValue_e).
# These are 8/9/10 in the 2017 type library; ids 1/2/3 are swFileLocationsDocuments /
# PaletteFeatures / PaletteParts, which never yield a template and silently forced
# every new document onto disk-discovered templates.
SW_DEFAULT_TEMPLATE_PART = 8
SW_DEFAULT_TEMPLATE_ASSEMBLY = 9
SW_DEFAULT_TEMPLATE_DRAWING = 10


def validated_output_path(path: str, allowed_extensions: set[str], allow_overwrite: bool = False) -> Path:
    candidate = Path(path).expanduser()
    # A relative path means "inside the output root", which is where everything
    # has to land anyway; the server has no meaningful working directory.
    if not candidate.is_absolute():
        candidate = OUTPUT_ROOT / candidate
    output = candidate.resolve()
    if output.suffix.lower() not in allowed_extensions:
        extensions = ", ".join(sorted(allowed_extensions))
        raise RuntimeError(f"Unsupported output extension. Allowed: {extensions}.")
    try:
        output.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise RuntimeError(f"For safety, output path must be under {OUTPUT_ROOT}.") from exc
    if output.exists() and not allow_overwrite:
        raise RuntimeError(f"Refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def _file_stamp(path: Path) -> tuple[int, int] | None:
    """(mtime_ns, size) of a file, or None when it does not exist."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


# swFileSaveError_e.swGenericSaveError.  2017 SP5 returns it on every .3mf
# export (with or without swSaveAsOptions_Silent) while writing a valid file.
_SW_GENERIC_SAVE_ERROR = 1


def _benign_3mf_error(path: Path, errors: int) -> bool:
    """True when ``errors`` is 2017's spurious generic error on a valid .3mf.

    Narrow on purpose: only that exact code, only .3mf, and only when the file
    is a zip archive (3MF is an OPC zip), so a truncated or empty write still
    counts as a failure.
    """
    if errors != _SW_GENERIC_SAVE_ERROR or path.suffix.lower() != ".3mf":
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"PK"
    except OSError:
        return False


_BMP_WIDTH, _BMP_HEIGHT = 1280, 720  # SaveBMP needs explicit pixel size


def prepare_for_save(doc: Any) -> str | None:
    """Rebuild a stale model and refuse to save one with unsolved equations.

    Saving a model that needs a rebuild (or whose equations are unsolved) makes SOLIDWORKS
    show a "Rebuild?" modal that blocks COM forever, so rebuild first (live 2017 finding).
    Returns an error message, or None when the save may proceed.
    """
    try:
        with dialogs_suppressed():
            if int(safe(doc, "GetType", 0) or 0) in (1, 2):
                flag_methods(doc, "ForceRebuild3").ForceRebuild3(False)
        mgr = safe(doc, "GetEquationMgr")
        if mgr is not None and int(value(mgr, "GetCount") or 0) > 0:
            status = int(safe(mgr, "Status", 0) or 0)
            if status < 0:
                return "The document has unsolved equations (a deleted variable still referenced?); fix them before saving."
    except Exception:
        logger.info("prepare_for_save could not verify the document state")
    return None


def _save_as(doc: Any, path: str, report: dict[str, Any] | None = None) -> bool:
    """Save/export ``doc`` to ``path``; ``report`` (if given) receives errors/warnings codes."""
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    errors, warnings = byref_long(0), byref_long(0)
    before = _file_stamp(output)
    problem = prepare_for_save(doc)
    if problem:
        if report is not None:
            report["blocked"] = problem
        logger.warning(problem)
        return False

    # SOLIDWORKS refuses SaveAs onto a path that is already open — including
    # this very document's own path — so that case is a plain Save.
    current = str(value(doc, "GetPathName") or "")
    if current and Path(current).resolve() == output:
        try:
            saved = bool(doc.Save3(1, errors, warnings))
            if report is not None:
                report.update(errors=int(errors.value), warnings=int(warnings.value))
            if saved and int(errors.value) == 0:
                return True
        except Exception:
            logger.info("Save3 on the document's own path failed; trying SaveAs")

    if output.suffix.lower() == ".bmp":
        # Extension.SaveAs rejects .bmp on 2017 (error 256, invalid extension); SaveBMP is the route.
        try:
            returned = bool(flag_methods(doc, "SaveBMP").SaveBMP(str(output), _BMP_WIDTH, _BMP_HEIGHT))
        except Exception:
            returned = False
        after = _file_stamp(output)
        return bool(after is not None and after[1] > 0 and (returned or after != before))

    try:
        returned = bool(extension(doc).SaveAs(str(output), 0, 0, nothing(), errors, warnings))
        if report is not None:
            report.update(errors=int(errors.value), warnings=int(warnings.value))
        # 2017 writes a valid .3mf yet returns False with a non-zero *warnings*
        # code, so the return value and warnings are not proof of failure.  What
        # counts is no error code plus a non-empty file that this call wrote
        # (new, or changed since before the call when overwriting).
        after = _file_stamp(output)
        written = after is not None and after[1] > 0 and (returned or after != before)
        if written and (int(errors.value) == 0 or _benign_3mf_error(output, int(errors.value))):
            return True
    except Exception:
        logger.info("Extension.SaveAs failed; falling back to ModelDoc2.SaveAs")
    try:
        return bool(doc.SaveAs(str(output)))
    except Exception:
        return False


@tool(
    "solidworks_status",
    "Read-only: verify attachment to the running SOLIDWORKS instance and report active-document status.",
    {},
)
def solidworks_status(args: dict[str, Any]) -> dict[str, Any]:
    app = running_app()
    active = app.ActiveDoc
    payload = result(
        True,
        "Attached to the running SOLIDWORKS session.",
        version=str(value(app, "RevisionNumber")),
        document_count=int(value(app, "GetDocumentCount")),
        output_root=str(OUTPUT_ROOT),
    )
    if active is not None:
        payload["data"]["active_document"] = document_info(active)
    return payload


@tool(
    "get_active_document_info",
    "Read-only: return the active SOLIDWORKS document title, path, type, and unsaved state.",
    {},
)
def get_active_document_info(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    return result(True, "Read active document.", document=document_info(doc))


@tool(
    "create_new_document",
    "Create a new SOLIDWORKS part, assembly, or drawing from the configured default template.",
    {"kind": {"type": "string", "enum": ["part", "assembly", "drawing"]}},
    ["kind"],
)
def create_new_document(args: dict[str, Any]) -> dict[str, Any]:
    return new_document(str(args["kind"]))


def new_document(kind: str) -> dict[str, Any]:
    app = running_app()
    preference = {
        "part": SW_DEFAULT_TEMPLATE_PART,
        "assembly": SW_DEFAULT_TEMPLATE_ASSEMBLY,
        "drawing": SW_DEFAULT_TEMPLATE_DRAWING,
    }.get(kind)
    if preference is None:
        return result(False, "kind must be part, assembly, or drawing.")
    template = app.GetUserPreferenceStringValue(preference)
    if not template or not Path(str(template)).is_file():
        fallback = discover_template(kind)
        if fallback is None:
            return result(
                False,
                f"No default {kind} template is configured in SOLIDWORKS and none could be found on disk. "
                "Set one under Tools > Options > File Locations, or point SW_MCP_TEMPLATE_DIR at your templates.",
            )
        template = str(fallback)
    doc = app.NewDocument(template, 0, 0.0, 0.0)
    if doc is None:
        return result(False, f"SOLIDWORKS did not create a {kind} document.")
    stamp_active_document(app)
    return result(True, f"Created new {kind} document.", document=document_info(doc))


@tool(
    "open_document",
    "Open an existing .sldprt, .sldasm, or .slddrw file and make it the active document.",
    {"path": {"type": "string"}},
    ["path"],
)
def open_document(args: dict[str, Any]) -> dict[str, Any]:
    app = running_app()
    path = Path(str(args["path"])).expanduser().resolve()
    if not path.is_file():
        return result(False, f"No such file: {path}")
    doc_type = {".sldprt": 1, ".sldasm": 2, ".slddrw": 3}.get(path.suffix.lower())
    if doc_type is None:
        return result(False, "Only .sldprt, .sldasm, and .slddrw files can be opened.")
    errors, warnings = byref_long(0), byref_long(0)
    doc = app.OpenDoc6(str(path), doc_type, 0, "", errors, warnings)
    if doc is None:
        return result(False, f"SOLIDWORKS could not open {path}.", error_code=int(errors.value))
    # OpenDoc6 returns an already-open document without activating it.  That
    # left the next tool operating on whichever drawing or part happened to be
    # active, despite this tool promising otherwise.
    activation_errors = byref_long(0)
    activated = bool(app.ActivateDoc3(str(path), False, 0, activation_errors))
    stamp_active_document(app)
    if not activated:
        return result(
            False,
            f"Opened {path}, but SOLIDWORKS could not make it active.",
            error_code=int(activation_errors.value),
            document=document_info(doc),
        )
    return result(True, f"Opened and activated {path}.", document=document_info(app.ActiveDoc))


@tool(
    "save_document",
    "Save the active document as a new .sldprt, .sldasm, or .slddrw file under the designated "
    "outputs folder. Existing files are never overwritten unless overwrite is true.",
    {"path": {"type": "string"}, "overwrite": {"type": "boolean", "default": False}},
    ["path"],
)
def save_document(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    output = validated_output_path(
        str(args["path"]), {".sldprt", ".sldasm", ".slddrw"}, bool(args.get("overwrite", False))
    )
    clear_selection(doc)
    report: dict[str, Any] = {}
    saved = _save_as(doc, str(output), report)
    if report.get("blocked"):
        return result(False, str(report["blocked"]), path=str(output))
    if saved:
        return result(True, f"Saved document to {output}.", path=str(output))
    return result(False, _save_failure_reason(doc, output), path=str(output))


def _save_failure_reason(doc: Any, output: Path) -> str:
    """SOLIDWORKS refuses a save-as onto a file it already has open elsewhere."""
    try:
        for other in as_list(value(running_app(), "GetDocuments")):
            if other is doc:
                continue
            existing = str(value(other, "GetPathName") or "")
            if existing and Path(existing).resolve() == output:
                title = str(value(other, "GetTitle"))
                return (
                    f"SOLIDWORKS already has '{title}' open from {output}, and will not save over "
                    "a document that is open. Close that document first, or save to another name."
                )
    except Exception:
        pass
    return "SOLIDWORKS failed to save the document."


@tool(
    "save_active_document",
    "Save changes to the active document's existing file path. This cannot choose another path.",
    {},
)
def save_active_document(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    path = str(value(doc, "GetPathName") or "")
    if not path:
        return result(False, "The active document has no saved path; use save_document first.")
    errors, warnings = byref_long(0), byref_long(0)
    saved = bool(doc.Save3(1, errors, warnings)) and int(errors.value) == 0
    return result(
        saved,
        f"Saved active document to {path}." if saved else "SOLIDWORKS failed to save the active document.",
        path=path,
    )


# --------------------------------------------------------------------------
# Export (formats, options, per-body and per-component)
# --------------------------------------------------------------------------

_OPTION_SCHEMA: dict[str, Any] = {
    "configuration": {"type": "string", "description": "Configuration to export (restored afterwards). Not for export_components."},
    "step_version": {"type": "string", "enum": ["AP203", "AP214"], "description": ".step/.stp only."},
    "stl_format": {"type": "string", "enum": ["binary", "ascii"]},
    "stl_quality": {"type": "string", "enum": ["coarse", "fine", "custom"]},
    "deviation_mm": {"type": "number", "description": "STL custom-quality chord deviation (implies custom)."},
    "angle_deg": {"type": "number", "description": "STL custom-quality angle tolerance (implies custom)."},
    "units": {"type": "string", "enum": ["mm", "cm", "m", "in"], "description": "Output units, .stl and .wrl only."},
    "single_file": {"type": "boolean", "description": "Assembly STL/VRML: all components in one file."},
    "translate_to_positive": {"type": "boolean", "description": "STL: move the model into the positive octant."},
    "vrml_version": {"type": "string", "enum": ["97", "01"], "description": "97 = VRML 2.0 (VRML97); 01 = VRML 1.0."},
    "pdf_3d": {"type": "boolean", "default": True, "description": ".pdf of a part/assembly: embed 3D (else plain view save)."},
}


def _output_extensions() -> set[str]:
    return set(EXPORT_EXTENSIONS) | sw_export.EXPORT_FILE_EXTENSIONS


def _doc_type_of(doc: Any) -> int:
    try:
        return int(safe(doc, "GetType", 0) or 0)
    except (TypeError, ValueError):
        return 0


@contextmanager
def _shown_configuration(doc: Any, name: str | None) -> Iterator[None]:
    """Activate configuration ``name`` for the duration, then put the previous one back."""
    if not name:
        yield
        return
    names = [str(n) for n in as_list(value(doc, "GetConfigurationNames"))]
    match = next((n for n in names if n.lower() == str(name).lower()), None)
    if match is None:
        raise RuntimeError(f"No configuration named '{name}'. Available: {names}.")
    previous = str(safe(safe(doc, "GetActiveConfiguration"), "Name", "") or "")
    flag_methods(doc, "ShowConfiguration2")
    if not bool(doc.ShowConfiguration2(match)):
        raise RuntimeError(f"SOLIDWORKS could not activate configuration '{match}'.")
    try:
        yield
    finally:
        if previous and previous != match:
            try:
                doc.ShowConfiguration2(previous)
            except Exception:
                logger.warning("Could not re-activate configuration '%s' after export", previous)


def _save_pdf_3d(app: Any, doc: Any, output: Path, report: dict[str, Any]) -> bool:
    """Write a 3D PDF via IExportPdfData; needs the optional 3D PDF components."""
    data = flag_methods(app, "GetExportFileData").GetExportFileData(1)  # swExportPdfData
    if data is None:
        report["detail"] = "SOLIDWORKS returned no PDF export data object."
        return False
    data.ExportAs3D = True
    data.ViewPdfAfterSaving = False
    before = _file_stamp(output)
    errors, warnings = byref_long(0), byref_long(0)
    returned = bool(extension(doc).SaveAs(str(output), 0, 1, data, errors, warnings))
    report.update(errors=int(errors.value), warnings=int(warnings.value))
    after = _file_stamp(output)
    return bool(after is not None and after[1] > 0 and (returned or after != before) and int(errors.value) == 0)


def _save_planned(app: Any, doc: Any, output: Path, plan: sw_export.ExportPlan, codes: dict[str, Any]) -> bool:
    if plan.pdf_3d:
        return _save_pdf_3d(app, doc, output, codes)
    return _save_as(doc, str(output), codes)


def _run_with_preferences(app: Any, plan: sw_export.ExportPlan, action: Any) -> tuple[Any, dict[str, Any]]:
    """Run ``action()`` with the plan's preferences applied, always restoring them."""
    info: dict[str, Any] = {}
    scope = sw_export.PreferenceScope(app) if plan.has_preferences else None
    try:
        if scope is not None:
            scope.apply(plan)
            info["preferences_applied"] = scope.applied
        return action(), info
    finally:
        if scope is not None:
            failed = scope.restore()
            info["preferences_restored"] = not failed
            if failed:
                info["preferences_restore_failed"] = failed


@tool(
    "export_document",
    "Export the active part/assembly/drawing under the designated outputs folder. The extension picks the "
    "format: step/stp (AP203 or AP214), iges/igs, x_t, x_b, sat, stl (ascii/binary, quality, units), 3mf, "
    "wrl, eprt/easm (eDrawings), pdf (3D for models), png, jpg, tif, bmp. Options are applied through "
    "user preferences and restored afterwards. See list_export_formats.",
    {"path": {"type": "string"}, "overwrite": {"type": "boolean", "default": False}, **_OPTION_SCHEMA},
    ["path"],
)
def export_document(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = active_document()
    output = validated_output_path(str(args["path"]), _output_extensions(), bool(args.get("overwrite", False)))
    try:
        plan = sw_export.plan_export(output.suffix, args, _doc_type_of(doc))
    except ValueError as exc:
        return result(False, str(exc))
    clear_selection(doc)
    codes: dict[str, Any] = {}

    def action() -> bool:
        with _shown_configuration(doc, plan.configuration):
            return _save_planned(app, doc, output, plan, codes)

    exported, info = _run_with_preferences(app, plan, action)
    payload = result(
        exported,
        f"Exported document to {output}." if exported else "SOLIDWORKS failed to export the document.",
        path=str(output),
        **codes,
        **info,
    )
    if exported and codes.get("warnings"):
        payload["message"] += f" SOLIDWORKS reported warning code {codes['warnings']} (file was written)."
    if not exported and plan.pdf_3d:
        payload["message"] += " 3D PDF needs the optional 3D PDF components; retry with pdf_3d false for a plain save."
    return payload


@tool(
    "list_export_formats",
    "Read-only: list the export formats export_document supports, per document type, with their options, "
    "plus formats known to be unavailable on SOLIDWORKS 2017.",
    {},
)
def list_export_formats(args: dict[str, Any]) -> dict[str, Any]:
    return result(
        True,
        "Export formats for SOLIDWORKS 2017.",
        formats=sw_export.format_catalog(),
        per_body_formats=sorted(sw_export.BODY_FORMATS),
        unsupported=sw_export.UNSUPPORTED,
    )


def _safe_stem(name: str, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_. ()" else "_" for ch in name).strip(" .")
    return cleaned or fallback


def _unique_stem(stem: str, used: set[str]) -> str:
    candidate, index = stem, 2
    while candidate.lower() in used:
        candidate, index = f"{stem}_{index}", index + 1
    used.add(candidate.lower())
    return candidate


def _normalise_ext(raw: Any, default: str) -> str:
    ext = str(raw or default).strip().lower()
    return ext if ext.startswith(".") else f".{ext}"


@tool(
    "export_bodies",
    "Export each solid body of the active multi-body part to its own file in a folder under the outputs "
    "folder: x_t, x_b, step, sat, iges or stl. Each body is selected and saved with Extension.SaveAs, "
    "which exports only the selection. Optionally restrict to body_names; STEP/STL options as in "
    "export_document.",
    {
        "directory": {"type": "string", "description": "Folder under the outputs folder."},
        "format": {"type": "string", "enum": ["x_t", "x_b", "step", "sat", "iges", "stl"], "default": "x_t"},
        "body_names": {"type": "array", "items": {"type": "string"}},
        "overwrite": {"type": "boolean", "default": False},
        **{k: v for k, v in _OPTION_SCHEMA.items() if k in ("step_version", "stl_format", "stl_quality", "deviation_mm", "angle_deg", "units", "translate_to_positive")},
    },
    ["directory"],
)
def export_bodies(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = require_part()
    ext = _normalise_ext(args.get("format"), "x_t")
    if ext not in sw_export.BODY_FORMATS:
        return result(False, f"Per-body export supports {sorted(sw_export.BODY_FORMATS)} only; use export_document for others.")
    try:
        plan = sw_export.plan_export(ext, args, 1)
    except ValueError as exc:
        return result(False, str(exc))
    wanted = {str(n).lower() for n in (args.get("body_names") or [])}
    names = [str(safe(b, "Name", "") or "") for b in get_bodies(doc)]
    if wanted:
        missing = wanted - {n.lower() for n in names}
        if missing:
            return result(False, f"No such body: {sorted(missing)}. Available: {names}.")
        names = [n for n in names if n.lower() in wanted]
    if not names:
        return result(False, "The active part has no solid bodies to export.")
    directory = str(args["directory"]).rstrip("/\\")
    used: set[str] = set()
    overwrite = bool(args.get("overwrite", False))
    paths = [
        validated_output_path(f"{directory}/{_unique_stem(_safe_stem(n, f'body{i}'), used)}{ext}", _output_extensions(), overwrite)
        for i, n in enumerate(names, 1)
    ]
    exported: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    def action() -> None:
        for name, output in zip(names, paths):
            clear_selection(doc)
            if not select_by_id(doc, name, "SOLIDBODY", 0, False):
                failed.append({"body": name, "path": str(output), "error": "Could not select the body."})
                continue
            codes: dict[str, Any] = {}
            try:
                ok = _save_as(doc, str(output), codes)
            except Exception as exc:
                failed.append({"body": name, "path": str(output), "error": str(exc)})
                continue
            stamp = _file_stamp(output)
            entry = {"body": name, "path": str(output), "bytes": stamp[1] if stamp else 0, **codes}
            (exported if ok else failed).append(entry)
        clear_selection(doc)

    _, info = _run_with_preferences(app, plan, action)
    return result(
        not failed,
        f"Exported {len(exported)} of {len(names)} bodies.",
        exported=exported,
        failed=failed,
        **info,
    )


@tool(
    "export_components",
    "Export each distinct component of the active assembly to its own file in a folder under the outputs "
    "folder, in any export_document format valid for parts/assemblies. Suppressed and lightweight "
    "(unloaded) components are skipped and reported.",
    {
        "directory": {"type": "string", "description": "Folder under the outputs folder."},
        "format": {"type": "string", "default": "step", "description": "Extension, e.g. step, stl, x_t, 3mf."},
        "top_level_only": {"type": "boolean", "default": True},
        "overwrite": {"type": "boolean", "default": False},
        **{k: v for k, v in _OPTION_SCHEMA.items() if k != "configuration"},
    },
    ["directory"],
)
def export_components(args: dict[str, Any]) -> dict[str, Any]:
    app, doc = active_document()
    if _doc_type_of(doc) != 2:
        return result(False, "This tool requires an active assembly document.")
    if args.get("configuration"):
        return result(False, "Components export in their referenced configuration; 'configuration' is not supported here.")
    ext = _normalise_ext(args.get("format"), "step")
    try:
        plan = sw_export.plan_export(ext, args, 0)
    except ValueError as exc:
        return result(False, str(exc))
    if ext == ".pdf" or ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
        return result(False, "PDF and image formats are not supported for per-component export; use export_document.")
    allowed_types = sw_export.FORMATS[ext][1]

    directory = str(args["directory"]).rstrip("/\\")
    overwrite = bool(args.get("overwrite", False))
    seen: set[str] = set()
    used: set[str] = set()
    targets: list[tuple[str, Any, Path]] = []
    skipped: list[dict[str, Any]] = []
    for component in iter_components(doc, bool(args.get("top_level_only", True))):
        label = str(safe(component, "Name2", "") or "")
        source = str(safe(component, "GetPathName", "") or "")
        # swComponentSuppressionState_e: 0 suppressed, 1/4 lightweight, 2/3 resolved.  IsSuppressed
        # is also true for lightweight components, so the real state decides.
        state = safe(component, "GetSuppression")
        lightweight = state in (1, 4)
        if bool(safe(component, "IsSuppressed", False)) and not lightweight:
            skipped.append({"component": label, "reason": "suppressed"})
            continue
        key = (source or label).lower()
        if key in seen:
            continue  # another instance of the same part/sub-assembly
        seen.add(key)
        if lightweight:
            try:
                component.SetSuppression2(2)  # resolve so the model can be exported
            except Exception:
                logger.info("Could not resolve lightweight component %s.", label)
        model = safe(component, "GetModelDoc2")
        if model is None:
            skipped.append({"component": label, "reason": "model could not be loaded; resolve the component first"})
            continue
        if _doc_type_of(model) not in allowed_types:
            skipped.append({"component": label, "reason": f"{ext} is not valid for this component type"})
            continue
        stem = _unique_stem(_safe_stem(Path(source).stem if source else label, "component"), used)
        targets.append((label, model, validated_output_path(f"{directory}/{stem}{ext}", _output_extensions(), overwrite)))
    if not targets:
        return result(False, "No exportable components found.", skipped=skipped)

    exported: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    def activate(target: Any) -> None:
        # STL (and other multi-file exports) written from a component's model while the
        # assembly is active export the whole assembly, so each part is made active first.
        try:
            flag_methods(app, "ActivateDoc3").ActivateDoc3(str(safe(target, "GetTitle", "") or ""), True, 0, byref_long(0))
        except Exception:
            logger.info("Could not activate %s before exporting it.", safe(target, "GetTitle", ""))

    def action() -> None:
        try:
            for label, model, output in targets:
                activate(model)
                codes: dict[str, Any] = {}
                try:
                    ok = _save_as(model, str(output), codes)
                except Exception as exc:
                    failed.append({"component": label, "path": str(output), "error": str(exc)})
                    continue
                (exported if ok else failed).append({"component": label, "path": str(output), **codes})
        finally:
            activate(doc)

    _, info = _run_with_preferences(app, plan, action)
    stamp_active_document(app)  # the call switches documents; report the one active at the end
    return result(
        bool(exported) and not failed,
        f"Exported {len(exported)} of {len(targets)} components.",
        exported=exported,
        failed=failed,
        skipped=skipped,
        **info,
    )


@tool(
    "rebuild_document",
    "Force a rebuild of the active document and report any feature that fails.",
    {"force_all": {"type": "boolean", "default": False, "description": "Rebuild every feature, not just the stale ones."}},
)
def rebuild_document(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = active_document()
    if bool(args.get("force_all", False)):
        try:
            rebuilt = bool(extension(doc).ForceRebuildAll())
        except Exception:
            rebuilt = rebuild(doc)
    else:
        rebuilt = rebuild(doc)
    problems = whats_wrong(doc)
    return result(
        rebuilt and not problems,
        "Rebuilt the active document." if rebuilt and not problems else "The rebuild reported problems.",
        problems=problems,
    )


@tool(
    "set_appearance",
    "Set the display colour of the active part, or of the selected faces or features. "
    "RGB components are 0-255.",
    {
        "red": {"type": "integer", "minimum": 0, "maximum": 255},
        "green": {"type": "integer", "minimum": 0, "maximum": 255},
        "blue": {"type": "integer", "minimum": 0, "maximum": 255},
        "transparency": {"type": "number", "minimum": 0, "maximum": 1, "default": 0},
        "selection": {
            "type": "object",
            "description": "Optional: colour only these faces. Omit to colour the whole model.",
            "properties": {"faces": {"type": "array", "items": {"type": "integer"}}},
        },
    },
    ["red", "green", "blue"],
)
def set_appearance(args: dict[str, Any]) -> dict[str, Any]:
    from .sw_core import as_list, enumerate_faces, get_bodies, safe

    _, doc = require_part()
    values = (
        int(args["red"]) / 255.0, int(args["green"]) / 255.0, int(args["blue"]) / 255.0,
        1.0, 1.0, 0.4, 0.3, float(args.get("transparency", 0)), 0.0,
    )
    face_indices = (args.get("selection") or {}).get("faces")
    if face_indices:
        faces = [f for body in get_bodies(doc) for f in as_list(safe(body, "GetFaces"))]
        for raw_index in face_indices:
            index = int(raw_index)
            if not 0 <= index < len(faces):
                return result(False, f"Face index {index} is out of range (0..{len(faces) - 1}).")
            faces[index].MaterialPropertyValues = double_array(values)
        target = f"{len(face_indices)} faces"
    else:
        doc.MaterialPropertyValues = double_array(values)
        target = "the whole model"
    try:
        invoke_no_arg(doc, "GraphicsRedraw2")
    except Exception:
        pass
    return result(True, f"Applied the colour to {target}.", rgb=[args["red"], args["green"], args["blue"]])


def _material_readback(doc: Any, database: str) -> str:
    """Read the assigned material name back, across the API's several shapes.

    GetMaterialPropertyName2 takes the database as an [in, out] string.  Given
    a plain Python string, SOLIDWORKS 2016 returns nothing even though the
    material was applied (the mass changes), so the typed by-reference form is
    tried first.  MaterialIdName, stable since 2008, reports "database|name"
    and is the last resort.
    """
    for database_arg in (
        win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_BSTR, database),
        database,
    ):
        try:
            raw = doc.GetMaterialPropertyName2("", database_arg)
        except Exception:
            continue
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else ""
        name = str(raw or "")
        if name:
            return name
    ident = str(safe(doc, "MaterialIdName", "") or "")
    return ident.split("|", 1)[1] if "|" in ident else ident


@tool(
    "set_material",
    "Assign a SOLIDWORKS material to the active part, which is what makes get_mass_properties "
    "report a real mass. Example: database 'SOLIDWORKS Materials', name 'AISI 1020'.",
    {
        "name": {"type": "string", "description": "Material name exactly as it appears in the material library."},
        "database": {"type": "string", "default": "SOLIDWORKS Materials"},
    },
    ["name"],
)
def set_material(args: dict[str, Any]) -> dict[str, Any]:
    _, doc = require_part()
    name = str(args["name"])
    database = str(args.get("database", "SOLIDWORKS Materials"))
    try:
        doc.SetMaterialPropertyName2("", database, name)
    except Exception as exc:
        return result(False, f"SOLIDWORKS rejected that material: {exc}")
    applied = _material_readback(doc, database)
    rebuild(doc)
    # An unknown material name is accepted silently and leaves the part
    # unassigned, so treat anything but an exact read-back as a failure.
    if applied != name:
        return result(
            False,
            f"SOLIDWORKS did not apply '{name}'; the part reports "
            f"'{applied or '<unspecified>'}'. Check the exact name in the material library.",
            material=applied,
        )
    return result(True, f"Applied material '{name}'.", material=applied)


def _open_documents(app: Any) -> list[Any]:
    return [d for d in as_list(value(app, "GetDocuments")) if d is not None]


@tool(
    "list_open_documents",
    "Read-only: list every document open in SOLIDWORKS with title, path, type, and unsaved-changes flag.",
    {},
)
def list_open_documents(args: dict[str, Any]) -> dict[str, Any]:
    app = running_app()
    documents = [document_info(doc) for doc in _open_documents(app)]
    return result(True, f"{len(documents)} documents are open.", documents=documents)


@tool(
    "close_document",
    "Close an open document by title (default: the active document). A document with unsaved changes "
    "is refused unless save is true (only for files already saved under the outputs folder) or force "
    "is true (discards changes).",
    {
        "title": {"type": "string", "description": "Title as shown by list_open_documents."},
        "save": {"type": "boolean", "default": False},
        "force": {"type": "boolean", "default": False},
    },
)
def close_document(args: dict[str, Any]) -> dict[str, Any]:
    app = running_app()
    save, force = bool(args.get("save", False)), bool(args.get("force", False))
    wanted = args.get("title")
    if wanted:
        target = None
        for doc in _open_documents(app):
            if str(value(doc, "GetTitle")).lower() == str(wanted).lower():
                target = doc
                break
        if target is None:
            return result(False, f"No open document is titled '{wanted}'. Call list_open_documents.")
    else:
        target = app.ActiveDoc
        if target is None:
            return result(False, "SOLIDWORKS has no active document to close.")
    info = document_info(target)
    title, path = info["title"], info["path"]

    if save:
        if not path:
            return result(
                False,
                f"'{title}' has never been saved; use save_document first, then close it.",
                document=info,
            )
        try:
            Path(path).resolve().relative_to(OUTPUT_ROOT)
        except ValueError:
            return result(
                False,
                f"For safety, save-on-close is only allowed for files under {OUTPUT_ROOT}; '{title}' is elsewhere.",
                document=info,
            )
        errors, warnings = byref_long(0), byref_long(0)
        problem = prepare_for_save(target)
        if problem:
            return result(False, problem, document=info)
        if not (bool(target.Save3(1, errors, warnings)) and int(errors.value) == 0):
            return result(False, f"SOLIDWORKS failed to save '{title}', so it was not closed.", document=info)
    elif info["dirty"] and not force:
        return result(
            False,
            f"'{title}' has unsaved changes. Save it first, pass save=true (outputs folder only), "
            "or pass force=true to discard them.",
            document=info,
        )

    app.CloseDoc(title)
    remaining = len(_open_documents(app))
    return result(True, f"Closed '{title}'.", closed=title, remaining_documents=remaining)


@tool(
    "activate_document",
    "Make an open document the active one, by title (case-insensitive; see list_open_documents). "
    "Every document tool acts on the active document and reports it as active_document, so call this "
    "before working on a different open document. Verified by reading the active title back.",
    {"title": {"type": "string", "description": "Title as shown by list_open_documents."}},
    ["title"],
)
def activate_document(args: dict[str, Any]) -> dict[str, Any]:
    app = running_app()
    wanted = str(args["title"])
    target = None
    for doc in _open_documents(app):
        if str(value(doc, "GetTitle")).lower() == wanted.lower():
            target = doc
            break
    if target is None:
        return result(False, f"No open document is titled '{wanted}'. Call list_open_documents.")
    title = str(value(target, "GetTitle"))
    try:
        flag_methods(app, "ActivateDoc3").ActivateDoc3(title, True, 0, byref_long(0))
    except Exception as exc:
        return result(False, f"SOLIDWORKS could not activate '{title}': {exc}")
    # ActivateDoc3 can report success yet leave another document active, so
    # trust only the active title read back.
    current = app.ActiveDoc
    actual = str(value(current, "GetTitle")) if current is not None else ""
    stamp_active_document(app)  # whichever document is active now, switched or not
    if actual.lower() != title.lower():
        return result(
            False,
            f"Activation did not take effect: the active document is '{actual or '<none>'}', not '{title}'.",
            requested=title,
            actual=actual,
        )
    return result(True, f"Activated '{actual}'.", document=document_info(current))
