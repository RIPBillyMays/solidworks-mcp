# Tool catalog: solidworks-mcp (for the SOLIDWORKS 2017 live smoke test)

Generated 2026-10-08 from the source in `solidworks_mcp/` (read only). SOLIDWORKS was not started and the server was not run.

**How this was derived.** Tool names, arguments, call sequences and line numbers come from the code. Section 5 additionally cross-checks the code against the SOLIDWORKS 2017 SP5 (25.5.0.0083) type libraries and API help installed on this machine (`C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\sldworks.tlb`, `swconst.tlb`, `api\sldworksapi.chm`). Those files were only parsed from disk, never loaded into a running SOLIDWORKS. Anything in section 5 not backed by that evidence is labelled "unverified".

**Counts.** 92 tools are always registered; 2 more (`demo_*`) register only when `SW_MCP_DEMO_TOOLS` is set. 6 are rated high risk.

| Module | Tools | High risk |
| --- | --- | --- |
| `sw_file` | 10 | 4 (`open_document`, `save_document`, `save_active_document`, `export_document`) |
| `sw_refgeom` | 3 | 0 |
| `sw_sketch` | 28 | 1 (`add_dimension`) |
| `sw_feature` | 17 | 0 |
| `sw_inspect` | 11 | 1 (`capture_screenshot`) |
| `sw_assembly` | 5 | 0 |
| `sw_drawing` | 18 | 0 |
| `sw_demo` (opt-in) | 2 | 0 |
| **Total** | **92 (+2)** | **6** |

---

## 1. How tools are registered and how a call flows

**Registration.** `sw_core.py` owns two module-level containers, `TOOLS: list[Tool]` and `HANDLERS: dict[str, Callable]` (`sw_core.py:182-183`). The `@tool(name, description, properties, required)` decorator (`sw_core.py:186-209`) appends an `mcp.types.Tool` with a JSON `inputSchema` built from `properties`/`required`, and stores the function in `HANDLERS[name]`. Nothing is registered until a module is imported: `solidworks_mcp/server.py:53-61` imports `sw_file`, `sw_refgeom`, `sw_sketch`, `sw_feature`, `sw_inspect`, `sw_assembly`, `sw_drawing`, `sw_demo`. `sw_demo` calls `tool(...)` only inside `if DEMO_ENABLED:` (`sw_demo.py:305-323`), where `DEMO_ENABLED` is true when `SW_MCP_DEMO_TOOLS` is `1/true/yes/on` (`sw_demo.py:52`). `sw_core` itself registers no tools.

**Entry points.** The repo-root `server.py` puts the repo root on `sys.path` and calls `solidworks_mcp.server.run`. The package console script `solidworks-mcp` points at the same function (`pyproject.toml`). `run()` starts `asyncio.run(main())`, which serves a low-level `mcp.server.Server("solidworks-mcp")` over stdio (`server.py:101-113`).

**A call, step by step** (`solidworks_mcp/server.py:76-98`):

1. `list_tools` returns `TOOLS` as is (`server.py:71-73`).
2. `call_tool(name, arguments)` looks up `HANDLERS[name]`. Unknown name returns `{"ok": false, "message": "Unknown tool: ..."}`.
3. It takes the global `COM_LOCK` (an `asyncio.Lock`, so calls are serialized) and invokes `handler(arguments or {})` as a plain synchronous call on the event-loop thread (`server.py:82-84`). There is no timeout: a handler blocked by a modal SOLIDWORKS dialog stalls the whole server, not just that call.
4. Exceptions: `RuntimeError` becomes `result(False, str(exc))` (this is how precondition failures such as "requires an active part document" surface); `KeyError` becomes `"Missing required argument: <key>"`; any other exception goes through `com_error`, which logs a traceback and returns `"SOLIDWORKS COM error: ..."` (`sw_core.py:224-226`).
5. Handlers return the envelope `{"ok": bool, "message": str, "data": {...}}` built by `result()` (`sw_core.py:217-221`). A handler may also put `_image_png_base64` in the payload; `call_tool` pops it (`server.py:92`).
6. The reply is a list of MCP content items: first a `TextContent` holding the JSON-dumped payload (`indent=2`, `ensure_ascii=False`, `default=str`), then, if an image was popped, an `ImageContent(mimeType="image/png")`. Only `capture_screenshot` produces an image (`sw_inspect.py:451`).

**COM attachment.** Every handler reaches SOLIDWORKS through `running_app()` (`sw_core.py:442-451`): `pythoncom.CoInitialize()` then `win32com.client.GetActiveObject("SldWorks.Application")`. It never launches SOLIDWORKS; with none running it raises `RuntimeError("No running SOLIDWORKS session is available...")`. Late binding is made safe by `flag_methods` (`sw_core.py:303-339`), which calls `_FlagAsMethod` per member so argument-taking members are not evaluated as properties; `value()` (`sw_core.py:259-273`) invokes zero-argument members.

**Units.** MCP boundary is millimetres and degrees (`*_mm`, `*_deg`); the COM layer is metres and radians (`to_m`, `to_rad`, ...).

**Files.** Anything the server writes must resolve under `OUTPUT_ROOT`, default `~/Documents/solidworks-mcp`, override with `SW_MCP_OUTPUT_ROOT` (`sw_core.py:138-140`; enforced for saves and exports by `validated_output_path`, `sw_file.py:50-67`). Relative paths are placed under it, parent directories are created, and existing files are refused unless `overwrite` is true. Log file: `solidworks_mcp/server.log` (rotating, `sw_core.py:42-53`).

**Environment variables:** `SW_MCP_OUTPUT_ROOT`, `SW_MCP_TEMPLATE_DIR` (template fallback search root, `sw_core.py:159`), `SW_MCP_DEMO_TOOLS`.

---

## 2. Conventions used in the tables

Columns: `tool (source line of the @tool decorator)` | what it does | key SOLIDWORKS API members called | side effects | live-test risk.

**Side effects** is one of `read-only`, `modifies active doc`, `creates new doc`, `writes file to disk`, `changes SW settings`; a parenthesis adds a secondary effect. "Selection state" (what is currently selected in SOLIDWORKS) is changed by many tools and not counted as a side effect.

**Risk:** `low` = read-only; `med` = changes a document in memory; `high` = writes or overwrites files, changes user preferences, or could pop a modal dialog / hang COM (reason given).

Shared helpers, abbreviated in the tables to keep rows short:

| Tag | Helper | API members it calls |
| --- | --- | --- |
| `[AD]` | `active_document()` | `ISldWorks.ActiveDoc`, `IModelDoc2.GetType`; type checks in `require_part/assembly` (`sw_core.py:480-503`) |
| `[SEL]` | declarative `selection` (`apply_selection`, `sw_core.py:1258-1403`) | `ModelDocExtension.SelectByID2` (planes, axes, sketches, features, components, raw points); `.Select4` then `.Select2` fallback on `IFeature/IBody2/ISketchSegment/ISketchPoint/IComponent2` via `ISelectionMgr.CreateSelectData` + `ISelectData.Mark`; topology: `IPartDoc.GetBodies2` or `IComponent2.GetBodies3` then `IBody2.GetFaces/GetEdges`, `IFace2.GetBox/GetClosestPointOn`, `IEdge.GetCurve/GetCurveParams3`, `ICurve.Evaluate`; `IComponent2.GetSelectByIDString`. Face/edge/vertex picks usually end up as point-based `SelectByID2("", "FACE"/"EDGE"/"VERTEX", x,y,z)` (see section 5, item 15) |
| `[FR]` | `feature_result()` (`sw_core.py:1480-1502`) | `IFeature.Name`, `IModelDoc2.EditRebuild3`, `ModelDocExtension.GetWhatsWrong`, `IModelDoc2.ClearSelection2` |
| `[ES]` | `exit_active_sketch()` (`sw_core.py:613-621`) | `ISketchManager.ActiveSketch`, `ISketchManager.InsertSketch(True)` |
| `[SK]` | `select_sketch_for_feature()` (`sw_core.py:624-631`) | `[ES]`, feature-tree walk (`IModelDoc2.FirstFeature`, `IFeature.GetNextFeature/Name/GetTypeName2`), `IFeature.Select2(False, 0)` |
| `[WALK]` | feature-tree walk | `IModelDoc2.FirstFeature`, `IFeature.GetNextFeature`, `.Name`, `.GetTypeName2` |

---

## 3. Tools by module

### 3.1 `sw_file.py` (10 tools): session, documents, save/export, appearance

| Tool | What it does | Key API members | Side effects | Risk |
| --- | --- | --- | --- | --- |
| `solidworks_status` (`:96`) | Confirms attachment; returns SW revision, open-doc count, output root, active doc info. | `GetActiveObject`, `ISldWorks.RevisionNumber/GetDocumentCount/ActiveDoc`; `IModelDoc2.GetType/GetTitle/GetPathName/GetSaveFlag` | read-only | low |
| `get_active_document_info` (`:116`) | Title, path, type, dirty flag of the active doc. | `[AD]`, same four doc members | read-only | low |
| `create_new_document` (`:126`, impl `new_document :136`) | New part/assembly/drawing from the default template, falling back to a template found on disk. | `ISldWorks.GetUserPreferenceStringValue(1/2/3)`, `ISldWorks.NewDocument(template,0,0,0)`; fallback `discover_template` scans `ProgramData\SOLIDWORKS\SOLIDWORKS *` | creates new doc | med. Note: the preference ids 1/2/3 are not the default-template ids (section 5, item 1), so the fallback scan is always what picks the template |
| `open_document` (`:157`) | Opens `.sldprt/.sldasm/.slddrw` and activates it. | `ISldWorks.OpenDoc6(path,type,0,"",err,warn)`, `ISldWorks.ActivateDoc3(path,False,0,err)` | creates new doc (loads an existing file; no disk write) | **high**: `OpenDoc6` options 0 is not Silent, and `ActivateDoc3` Option 0 is `swUserDecision`, which shows a rebuild prompt if the doc needs a rebuild (section 5, item 13). Files saved by a newer release are refused by 2017 (`swFutureVersion` load error; the tool returns `error_code`) |
| `save_document` (`:190`) | Save-as a native file under `OUTPUT_ROOT`; refuses to overwrite unless `overwrite`. | `validated_output_path`; `_save_as`: `GetPathName`, `Save3(1,err,warn)` when path equals current, else `ModelDocExtension.SaveAs(path,0,0,null,err,warn)`, fallback `IModelDoc2.SaveAs`; `ISldWorks.GetDocuments` for the failure message | writes file to disk (the active doc is renamed to the new path) | **high**: writes a file; save-as retargets the open document; saving a doc whose references are unsaved can raise a prompt (pref `swWarnSavingReferencedDoc`) |
| `save_active_document` (`:227`) | Saves to the doc's existing path. | `GetPathName`, `IModelDoc2.Save3(1,err,warn)` | writes file to disk (overwrites in place) | **high**: overwrites the existing file; error if the doc was never saved |
| `export_document` (`:246`) | Exports active doc to `.step/.stp/.iges/.igs/.stl/.x_t/.x_b/.3mf/.png/.jpg/.bmp` under `OUTPUT_ROOT`. | same `_save_as` path: `ModelDocExtension.SaveAs` (format chosen by extension), `ClearSelection2` | writes file to disk | **high**: writes a file; STL and 3MF have "show info on save" preferences that may raise a dialog (section 5, item 14) |
| `rebuild_document` (`:265`) | Rebuilds and reports failing features; `force_all` for a full rebuild. | `ModelDocExtension.ForceRebuildAll` (else `IModelDoc2.EditRebuild3`), `GetWhatsWrong` | modifies active doc (rebuild; also exits an open sketch) | med |
| `set_appearance` (`:287`) | Sets RGB and transparency on the whole part or on listed face indices. | `[AD]`+part check, `IModelDoc.MaterialPropertyValues` (put, VT_R8 array) or `IFace2.MaterialPropertyValues`, `IPartDoc.GetBodies2`, `IBody2.GetFaces`, `GraphicsRedraw2` | modifies active doc | med. Contains a local `from sw_core import ...` at `:305` that will not resolve (section 5, item 16) |
| `set_material` (`:331`) | Assigns a library material (default database "SOLIDWORKS Materials"). | `IPartDoc.SetMaterialPropertyName2("",db,name)`, `GetMaterialPropertyName2("",db)`, `EditRebuild3` | modifies active doc | med. A wrong name is silently accepted by SW; the tool treats a non-exact read-back as failure |

### 3.2 `sw_refgeom.py` (3 tools): reference planes and axes

| Tool | What it does | Key API members | Side effects | Risk |
| --- | --- | --- | --- | --- |
| `list_reference_planes` (`:52`) | Lists plane and axis names of the active part. | `[AD]`+part, `[WALK]` filtered on type `RefPlane` / `RefAxis` | read-only | low |
| `create_plane` (`:63`) | Reference plane: offset / angle / midplane / three_points / parallel_through_point. | part check, `[ES]`, `select_in_order` (each reference selected with mark 0,1,2 via `[SEL]`), `IFeatureManager.InsertRefPlane(6 args)`, `[FR]` | modifies active doc | med |
| `create_axis` (`:120`) | Reference axis from cylindrical face, edge, two planes or two points. | part check, `[ES]`, `[SEL]`, `IModelDoc2.InsertAxis2(True)`, feature-tree diff to find the new axis | modifies active doc | med. Local `from sw_core import ...` at `:136` runs first and will not resolve (section 5, item 16) |

### 3.3 `sw_sketch.py` (28 tools): sketches, geometry, editing, relations, dimensions

"Open sketch" below means `ISketchManager.ActiveSketch` is not null (`_require_open_sketch`, `sw_sketch.py:116-119`); those tools accept any document type.

| Tool | What it does | Key API members | Side effects | Risk |
| --- | --- | --- | --- | --- |
| `create_sketch` (`:127`) | Opens a sketch on a plane (`front/top/right` or exact name) or a model face index; optional rename. | part check, `SelectByID2(name,"PLANE")` or `[SEL]` face, `ISketchManager.InsertSketch(True)`, `ActiveSketch`, `IFeature.Name` | modifies active doc (leaves sketch open) | med |
| `edit_sketch` (`:169`) | Reopens an existing sketch by name. | part check, `SelectByID2(name,"SKETCH")`, `InsertSketch(True)` | modifies active doc (leaves sketch open) | med |
| `close_sketch` (`:185`) | Exits the open sketch. | `ActiveSketch`, `InsertSketch(True)` | modifies active doc | med |
| `list_sketches` (`:199`) | Names of all `ProfileFeature`s and whether a sketch is open. | `[WALK]`, `ActiveSketch` | read-only | low |
| `list_sketch_segments` (`:206`) | Segments of the open or named sketch with indices. | `ISketch.GetSketchSegments`, `ISketchSegment.GetType/GetID/GetLength/ConstructionGeometry`, `ISketchLine.GetStartPoint2/GetEndPoint2`, `ISketchArc.GetCenterPoint2/GetRadius`; named sketch via `IFeature.GetSpecificFeature2` | read-only | low |
| `draw_line` (`:225`) | Line (optionally construction). | `ISketchManager.CreateLine(6)`, `ISketchSegment.ConstructionGeometry` (put); success judged by segment count | modifies active doc | med |
| `draw_centerline` (`:247`) | Construction centerline. | `CreateCenterLine(6)` | modifies active doc | med |
| `draw_circle` (`:266`) | Circle by centre and radius. | `CreateCircleByRadius(4)` | modifies active doc | med |
| `draw_rectangle` (`:287`) | Corner rectangle. | `CreateCornerRectangle(6)` | modifies active doc | med |
| `draw_arc` (`:306`) | Arc from centre, start, end, direction. | `CreateArc(10)` | modifies active doc | med |
| `draw_3point_arc` (`:330`) | Arc through three points. | `Create3PointArc(9)` | modifies active doc | med |
| `draw_ellipse` (`:351`) | Ellipse from centre, major, minor points. | `CreateEllipse(9)` | modifies active doc | med |
| `draw_polygon` (`:372`) | Regular polygon, 3-100 sides. | `CreatePolygon(8)` | modifies active doc | med |
| `draw_slot` (`:394`) | Straight slot (centre-centre or full length). | `CreateSketchSlot(14)` | modifies active doc | med |
| `draw_point` (`:424`) | Sketch point. | `CreatePoint(3)` | modifies active doc | med |
| `draw_spline` (`:436`) | Spline through points. | `double_array`, `CreateSpline(1)` | modifies active doc | med. Local `from sw_core import double_array` at `:457` will not resolve (section 5, item 16) |
| `sketch_fillet` (`:469`) | Fillet between selected segments. | `[SEL]`, `IModelDoc2.SketchFillet2(r, keep)` | modifies active doc | med |
| `sketch_chamfer` (`:488`) | Chamfer between selected segments (three modes). | `[SEL]`, `IModelDoc2.SketchChamfer(3)` | modifies active doc | med. Always reports `ok` (return value not checked) |
| `sketch_trim` (`:532`) | Trim at a point; success judged by segment count/length change. | `[SEL]`, `ISketchManager.SketchTrim(4)` | modifies active doc | med |
| `sketch_offset` (`:576`) | Offset selected entities. | `[SEL]`, `IModelDoc2.SketchOffset2(3)` | modifies active doc | med |
| `sketch_mirror` (`:601`) | Mirror selection about a centerline segment index. | `[SEL]`, `select_object` on the centerline, `IModelDoc2.SketchMirror()` | modifies active doc | med. Local `from sw_core import select_object` at `:618` will not resolve (section 5, item 16) |
| `convert_entities` (`:627`) | Convert Entities (project model edges/face loops). | `[SEL]`, `ISketchManager.SketchUseEdge3(2)` | modifies active doc | med |
| `set_construction_geometry` (`:644`) | Toggle construction flag on segment indices. | `ISketchSegment.ConstructionGeometry` (put) | modifies active doc | med |
| `add_relation` (`:693`) | Adds a geometric relation (horizontal, vertical, tangent, coincident, ... 14 kinds); verifies via relation count; reports sketch status. | `ISketch.RelationManager`, `ISketchRelationManager.AddRelation/GetRelationsCount/GetAllowedRelations`, `ISketch.GetConstrainedStatus` | modifies active doc | med |
| `add_dimension` (`:793`) | Adds a driving dimension (auto/horizontal/vertical/radius/diameter) and sets its value. | `[SEL]`, `IModelDoc2.AddDimension2/AddHorizontalDimension2/AddVerticalDimension2/AddRadialDimension2/AddDiameterDimension2(x,y,z)`, `IDisplayDimension.GetDimension2(0)`, `IDimension.SetSystemValue3(v,2,empty)/SystemValue/Name/FullName`, `ISldWorks.GetUserPreferenceToggle(10)` / `SetUserPreferenceToggle(10, ...)`, `EditRebuild3` only if no sketch is open | modifies active doc; changes SW settings (temporarily switches off `swInputDimValOnCreate`, restored in `finally`, `sw_core.py:461-477`) | **high**: changes a user preference and a modal dialog hangs COM. Only preference 10 is handled; the over-defining prompt preference (100) is not (section 5, item 14) |
| `set_dimension` (`:874`) | Sets an existing dimension by full name. | `IModelDoc2.Parameter(name)`, `IDimension.SetSystemValue3(v,2,empty)/SystemValue`, `EditRebuild3` when no sketch is open | modifies active doc | med |
| `list_dimensions` (`:914`) | Lists driving dimensions, optionally of one feature. | `IFeature.GetFirstDisplayDimension/GetNextDisplayDimension`, `IDisplayDimension.GetDimension2(0)`, `IDimension.FullName/Name/SystemValue/DrivenState/GetType` | read-only | low |
| `get_sketch_status` (`:967`) | Under/fully/over-defined status of the open sketch. | `ISketch.GetConstrainedStatus` | read-only | low |

### 3.4 `sw_feature.py` (17 tools): solid features

All except `delete_feature`, `rename_feature` and `set_feature_suppression` require an active **part**. Features close any open sketch first. Rebuild errors are reported through `[FR]`.

| Tool | What it does | Key API members | Side effects | Risk |
| --- | --- | --- | --- | --- |
| `boss_extrude` (`:113`) | Extrudes a sketch; `through_all_both` is translated to two-direction through-all. | `[SK]`, `IFeatureManager.FeatureExtrusion3(23 args)`, `[FR]` | modifies active doc | med |
| `cut_extrude` (`:149`) | Cuts with a sketch; retries the opposite direction if nothing was removed. | `[SK]`, `FeatureCut4(27 args)` (up to twice), `[FR]` | modifies active doc | med |
| `revolve` (`:205`) | Revolves a sketch (boss or cut), optional axis selection (mark 4) and mid-plane. | `[SK]`, `[SEL]` (axis, mark 4), `FeatureRevolve2(20 args)`, `[FR]` | modifies active doc | med. The mid-plane value passed looks wrong (section 5, item 8) |
| `fillet` (`:252`) | Constant-radius fillet on edges/faces. | `[ES]`, `[SEL]`, `FeatureFillet3(14 args)`, `[FR]` | modifies active doc | med |
| `chamfer` (`:283`) | Chamfer (equal, angle-distance, distance-distance). | `[SEL]`, `InsertFeatureChamfer(8)`, `[FR]` | modifies active doc | med |
| `shell` (`:327`) | Hollows the part; selected faces are removed. | `[SEL]` (optional), `IModelDoc2.InsertFeatureShell(thickness, outward)`, feature-tree diff, `[FR]` | modifies active doc | med |
| `draft` (`:355`) | Draft on faces about a neutral plane/face (marks 1 and 2). | `[SEL]` x2, `InsertMultiFaceDraft(6)`, `[FR]` | modifies active doc | med |
| `rib` (`:388`) | Rib from an open profile sketch; retries the other extrusion direction. | `[SK]`, `InsertRib(10)` (void; new feature found by tree diff), `[FR]` | modifies active doc | med |
| `simple_hole` (`:448`) | Straight hole at a picked face point. | `[SEL]`, `SimpleHole2(23)`, `[FR]` | modifies active doc | med |
| `sweep` (`:485`) | Sweeps a profile sketch (mark 1) along a path sketch (mark 4), boss or cut. | `[SEL]` x2 (`SelectByID2 "SKETCH"`), `InsertProtrusionSwept4(20)` / `InsertCutSwept5(22)`, `[FR]` | modifies active doc | med |
| `loft` (`:532`) | Lofts through two or more sketches (mark 1), boss or cut. | `[SEL]` per sketch, `InsertProtrusionBlend2(18)` / `InsertCutBlend(12)`, `[FR]` | modifies active doc | med |
| `linear_pattern` (`:583`) | Linear pattern in 1 or 2 directions (direction marks 1/2, features mark 4). | `[SEL]` x2-3, `FeatureLinearPattern5(22)`, `[FR]` | modifies active doc | med |
| `circular_pattern` (`:626`) | Circular pattern about an axis (axis mark 1, features mark 4). | `[SEL]` x2, `FeatureCircularPattern5(14)`, `[FR]` | modifies active doc | med |
| `mirror_feature` (`:663`) | Mirrors features or bodies about a plane (plane mark 2, features mark 1). | `[SEL]` x2, `InsertMirrorFeature2(5)`, `[FR]` | modifies active doc | med |
| `delete_feature` (`:699`) | Deletes named features. Any document type. | `[ES]`, `IFeature.Select2(True,0)`, `ModelDocExtension.DeleteSelection2(0)`, `EditRebuild3` | modifies active doc | med: destructive in memory. Option `0` does not include children, despite the tool description (section 5, item 11) |
| `rename_feature` (`:729`) | Renames a feature. Any document type. | `[WALK]` lookup, `IFeature.Name` (put) | modifies active doc | med |
| `set_feature_suppression` (`:744`) | Suppresses/unsuppresses named features. | `IFeature.Select2(False,0)`, `IModelDoc2.EditSuppress2/EditUnsuppress2`, `EditRebuild3`, `GetWhatsWrong` | modifies active doc | med |

### 3.5 `sw_inspect.py` (11 tools): topology, measurement, views, screenshots

| Tool | What it does | Key API members | Side effects | Risk |
| --- | --- | --- | --- | --- |
| `list_faces` (`:85`) | Faces with index, point, area, normal, surface type; filters by type/area/normal. Part or assembly (assembly bodies are mapped through the component transform). | `IPartDoc.GetBodies2(…,False)` / `IComponent2.GetBodies3`, `IBody2.GetFaces`, `IFace2.GetBox/GetClosestPointOn/GetArea/Normal/GetSurface`, `ISurface.Identity/CylinderParams/...`, `IComponent2.Transform2` | read-only | low |
| `list_edges` (`:135`) | Edges with index, curve type, length, endpoints; filters. | `IBody2.GetEdges`, `IEdge.GetCurve/GetCurveParams3/GetStartVertex/GetEndVertex`, `ICurve.Evaluate/GetLength2/Identity/CircleParams/LineParams`, `IVertex.GetPoint` | read-only | low |
| `list_vertices` (`:165`) | Unique vertices (derived from edge endpoints). | `IBody2.GetEdges`, `IEdge.GetStart/EndVertex`, `IVertex.GetPoint` | read-only | low |
| `list_bodies` (`:176`) | Solid bodies with bounding boxes. | `GetBodies2` / `GetBodies3`, `IBody2.GetBodyBox`, `IBody2.Name` | read-only | low |
| `list_features` (`:190`) | Feature tree names and type strings. | `[WALK]` | read-only | low |
| `get_bounding_box` (`:201`) | Overall bounding box in mm. | `IPartDoc.GetPartBox(True)` for a part, `IAssemblyDoc.GetBox(0)` otherwise | read-only | low |
| `get_mass_properties` (`:227`) | Mass, volume, area, centre of mass (and inertia if present). | `ModelDocExtension.GetMassProperties2(2, status, False)` | read-only | low. Inertia output likely absent on 2017 (section 5, item 9) |
| `measure` (`:259`) | Measures the selected entities (area, length, distance, angle, ...). | `[SEL]`, `ModelDocExtension.CreateMeasure`, `IMeasure.ArcOption` (put), `IMeasure.Calculate`, `IMeasure.Length/Area/Distance/...` | read-only (selection only) | low. Expected to fail on 2017: `Calculate` is called with no arguments (section 5, item 3) |
| `check_errors` (`:324`) | Rebuilds (by default) and lists flagged features. | `EditRebuild3`, `ModelDocExtension.GetWhatsWrong` | modifies active doc (rebuild; exits any open sketch) | med |
| `set_view` (`:347`) | Named view, shaded-with-edges, zoom to fit. | `IModelDoc2.ShowNamedView2("", id)`, `ViewDisplayShadedwithedges`, `ViewZoomtofit2` | modifies active doc (view only; no geometry change) | low. The shaded-with-edges call does not exist in the 2017 type library and is silently swallowed (section 5, item 2) |
| `capture_screenshot` (`:415`) | Returns the view as a PNG image (resized by Pillow to `width_px`). | `ClearSelection2`, `ShowNamedView2`, `ViewZoomtofit2`, `GraphicsRedraw2`, `ModelDocExtension.SaveAs(png,0,0,null,err,warn)` (fallback `IModelDoc2.SaveAs`); sleeps 0.35 s | writes file to disk (a PNG under `OUTPUT_ROOT\screenshots`, read back, then deleted); changes the view orientation | **high** by the rubric (it writes a file via SaveAs), though the file is transient. This is the only tool that returns an `ImageContent` item |

### 3.6 `sw_assembly.py` (5 tools): components and mates

All require an active **assembly**.

| Tool | What it does | Key API members | Side effects | Risk |
| --- | --- | --- | --- | --- |
| `list_components` (`:64`) | Components with path, suppressed/fixed flags, origin. | `IAssemblyDoc.GetComponents(top_only)`, `IComponent2.Name2/GetPathName/IsSuppressed/IsFixed/Transform2` | read-only | low |
| `insert_component` (`:86`) | Inserts a `.sldprt/.sldasm` at x/y/z (mm), optional configuration. | `ISldWorks.OpenDoc6(path,type,1 (Silent),config,err,warn)`, `IAssemblyDoc.AddComponent5(8 args)`, `EditRebuild3` | modifies active doc (also loads the source file into the session) | med |
| `add_mate` (`:131`) | Adds a mate (coincident, concentric, distance, angle, ...) between two selected entities. | `[SEL]`, `IAssemblyDoc.AddMate5(15 args)` with a status out-param, `EditRebuild3` | modifies active doc | med. An over-defining mate is reported as success with a warning |
| `list_mates` (`:190`) | Lists mates in the `MateGroup`. | `[WALK]` (`MateGroup`), `IFeature.GetFirstSubFeature/GetNextSubFeature/GetSpecificFeature2`, `IMate2.Type` | read-only | low. Distance/angle are probably omitted on 2017 (section 5, item 12). Local `from sw_core import ...` at `:196` runs first and will not resolve (section 5, item 16) |
| `set_component_fixed` (`:223`) | Fixes or floats named components. | `[SEL]` (`SelectByID2` with `GetSelectByIDString`, type `COMPONENT`), `IAssemblyDoc.FixComponent/UnfixComponent`, `EditRebuild3` | modifies active doc | med |

### 3.7 `sw_drawing.py` (18 tools): sheets, views, annotation

All require an active **drawing**, except `create_drawing`. Drawing-only members are flagged by `require_drawing` (`sw_drawing.py:108-122`).

| Tool | What it does | Key API members | Side effects | Risk |
| --- | --- | --- | --- | --- |
| `create_drawing` (`:232`) | New drawing from the default template, optionally resized/rescaled. | `new_document("drawing")` (see `create_new_document`), `IDrawingDoc.GetCurrentSheet`, `ISheet.GetName/GetSize`, `IDrawingDoc.SetupSheet5(11 args)`, `GetSheetNames` | creates new doc | med. Whenever any of `paper_size`/`first_angle`/`scale_numerator` is given, `first_angle` defaults to true (changes the projection standard); `GetSize` is called without arguments (section 5, item 10) |
| `list_sheets` (`:268`) | Sheets, active one, scale, first-angle flag, size. | `GetSheetNames`, `GetCurrentSheet`, `ISheet.GetName/GetProperties2` | read-only | low |
| `add_sheet` (`:287`) | Adds a sheet. | `IDrawingDoc.NewSheet3(10 args)`, `GetSheetNames` | modifies active doc | med |
| `activate_sheet` (`:312`) | Activates a sheet by name. | `IDrawingDoc.ActivateSheet` | modifies active doc (active-sheet state) | med |
| `insert_standard_views` (`:330`) | Front/top/side/iso set in one call. | `_open_model_path` / `_ensure_model_open` (`ISldWorks.GetDocuments`, `OpenDoc6(...,1,...)`, `ActivateDoc3`), `Create1stAngleViews2` or `Create3rdAngleViews2`, `GetFirstView/GetNextView` | modifies active doc (may load the model into the session) | med. `first_angle` defaults to true |
| `insert_model_view` (`:355`) | One named view at x/y; optional scale and display mode. | `IModelDoc2.GetModelViewNames` (localized names), `IDrawingDoc.CreateDrawViewFromModelView3(5 args)`, `IView.ScaleDecimal` (put), `IView.SetDisplayMode3` | modifies active doc | med. Display-mode values look mismatched (section 5, item 4) |
| `insert_projected_view` (`:443`) | Projected view off a parent view. | `GetFirstView/GetNextView`, `IView.Position`, `ActivateView`, `CreateUnfoldedViewAt3(4)` | modifies active doc | med. README: only the first projection per parent works |
| `insert_section_view` (`:539`) | Draws a cutting line in the parent view, then creates the section view. | `_draw_in_view` (`ActivateView`, `ISketchManager.CreateLine`, `select_object`), `IDrawingDoc.CreateSectionViewAt5(7 args)` | modifies active doc | med. Options value looks mismatched (section 5, item 6). Local imports at `:532` and `:560` will not resolve (item 16) |
| `insert_detail_view` (`:597`) | Draws a detail circle, then creates the detail view. | `_draw_in_view` (`CreateCircleByRadius`), `IDrawingDoc.CreateDetailViewAt4(12 args)` | modifies active doc | med. Style/show-type values look mismatched (section 5, item 7). Local import at `:532` (item 16) |
| `list_drawing_views` (`:659`) | Views with name, type, position, scale, dimension count. | `GetFirstView/GetNextView`, `IView.GetName2/Type/Position/ScaleDecimal/GetDimensionCount4/GetReferencedModelName` | read-only | low |
| `activate_drawing_view` (`:671`) | Activates a view by name. | `IDrawingDoc.ActivateView` | modifies active doc (active-view state) | med |
| `create_drawing_sketch` (`:685`) | Activates a view and opens a sketch in it. | `ActivateView`, `ActiveDrawingView`, `ClearSelection2`, `ISketchManager.InsertSketch(True)` | modifies active doc (leaves sketch open) | med |
| `set_drawing_view` (`:705`) | Moves/rescales/restyles a view. | `IView.Position` (put), `ScaleDecimal` (put), `SetDisplayMode3`, `TangentEdgeDisplay` (put), `EditRebuild3` | modifies active doc | med. The tangent-edge property is absent in 2017 (section 5, item 5). Local import at `:724` (item 16) |
| `insert_model_annotations` (`:750`) | Imports model dimensions/annotations (Insert > Model Items). | `ActiveDrawingView`, `ModelDocExtension.SelectByID2(view,"DRAWINGVIEW")`, `ActivateView`, `IDrawingDoc.InsertModelAnnotations3(6 args)`, `IView.GetDimensionCount4` | modifies active doc | med |
| `auto_dimension_view` (`:833`) | DimXpert-style auto dimensioning of a view. | `ActivateView`, `IDrawingDoc.AutoDimension(5 args)` | modifies active doc | med |
| `insert_center_marks` (`:959`) | Center marks on a view (all circles, or the current selection). | default: `IView.AutoInsertCenterMarks2(10 args)`, `GetCenterMarkCount2`; `selected_only`: `IView.GetVisibleEntities2`, `IView.SelectEntity`, `IDrawingDoc.InsertCenterMark3(3)` | modifies active doc | med. `selected_only` path uses a local import at `:907` (item 16) |
| `insert_centerlines` (`:1014`) | Centerlines/hole axes on a view. | default: `IView.AutoInsertCenterMarks2`; `selected_only`: `IDrawingDoc.InsertCenterLine2` | modifies active doc | med |
| `add_note` (`:1061`) | Text note at x/y with optional height. | `IModelDoc2.InsertNote`, `INote.GetAnnotation`, `IAnnotation.SetPosition/GetTextFormat/SetTextFormat`, `ITextFormat.CharHeight` | modifies active doc | med |

### 3.8 `sw_demo.py` (2 tools, only with `SW_MCP_DEMO_TOOLS=1`)

| Tool | What it does | Key API members | Side effects | Risk |
| --- | --- | --- | --- | --- |
| `demo_create_basketball` (`:306`, handler `:172`) | Creates a new part with a sphere (revolved semicircle, `Basketball_Base`) and orange appearance. | `new_document("part")`, `CreateArc/CreateLine`, `FeatureRevolve2(20)`, `MaterialPropertyValues`, `Select4`/`Select2` | creates new doc | med |
| `demo_upgrade_basketball` (`:315`, handler `:244`) | Adds four toroidal groove cuts and seam colours to the active `Basketball_Base` part. | feature revolves (cut), `IFeature.GetFaces`, `ISurface.IsTorus`, `BlankSketch`, `EditRebuild3` | modifies active doc | med |

---

## 4. Preconditions and sequencing

### 4.1 What each tool needs

| Precondition | Tools |
| --- | --- |
| SOLIDWORKS running, no document needed | `solidworks_status`, `create_new_document`, `open_document`, `create_drawing`, `demo_create_basketball` |
| Any active document (`active_document`) | `get_active_document_info`, `save_document`, `save_active_document`, `export_document`, `rebuild_document`, `list_sketches`, `list_sketch_segments`, `get_sketch_status`, `add_dimension`, `set_dimension`, `list_dimensions`, `delete_feature`, `rename_feature`, `set_feature_suppression`, `list_faces`, `list_edges`, `list_vertices`, `list_bodies`, `list_features`, `get_bounding_box`, `get_mass_properties`, `measure`, `check_errors`, `set_view`, `capture_screenshot`, `close_sketch` |
| Active **part** (`require_part`) | `set_appearance`, `set_material`, `list_reference_planes`, `create_plane`, `create_axis`, `create_sketch`, `edit_sketch`, `boss_extrude`, `cut_extrude`, `revolve`, `fillet`, `chamfer`, `shell`, `draft`, `rib`, `simple_hole`, `sweep`, `loft`, `linear_pattern`, `circular_pattern`, `mirror_feature`, `demo_upgrade_basketball` |
| Active **assembly** (`require_assembly`) | `list_components`, `insert_component`, `add_mate`, `list_mates`, `set_component_fixed` |
| Active **drawing** (`require_drawing`) | `list_sheets`, `add_sheet`, `activate_sheet`, `insert_standard_views`, `insert_model_view`, `insert_projected_view`, `insert_section_view`, `insert_detail_view`, `list_drawing_views`, `activate_drawing_view`, `create_drawing_sketch`, `set_drawing_view`, `insert_model_annotations`, `auto_dimension_view`, `insert_center_marks`, `insert_centerlines`, `add_note` |
| **Open sketch** (`ActiveSketch` not null) | `draw_line`, `draw_centerline`, `draw_circle`, `draw_rectangle`, `draw_arc`, `draw_3point_arc`, `draw_ellipse`, `draw_polygon`, `draw_slot`, `draw_point`, `draw_spline`, `sketch_fillet`, `sketch_chamfer`, `sketch_trim`, `sketch_offset`, `sketch_mirror`, `convert_entities`, `set_construction_geometry`, `add_relation`. Also usable inside a drawing view after `create_drawing_sketch` |
| **Selection spec** (indices from a `list_*` call) | `sketch_fillet`, `sketch_chamfer`, `sketch_trim` (required), `sketch_offset`, `sketch_mirror` (+ `mirror_segment`), `convert_entities`, `add_relation`, `add_dimension`, `measure`, `create_plane`, `create_axis`, `fillet`, `chamfer`, `draft` (+ `neutral_selection`), `simple_hole`, `linear_pattern` (+ `direction1_selection`), `circular_pattern` (+ `axis_selection`), `mirror_feature` (+ `plane_selection`), `add_mate`, `set_component_fixed` (component names). Optional: `shell` (omit to hollow with no opening), `revolve` (`axis_selection`, needed unless the sketch has exactly one centerline), `set_appearance` (face indices) |
| Sketch names, not selection | `boss_extrude`, `cut_extrude`, `rib`, `revolve` (default newest sketch), `sweep`, `loft`, `edit_sketch` |
| A saved model on disk | `insert_standard_views`, `insert_model_view`, `insert_projected_view` (needs an existing view) and the other view tools need `model_path` or exactly one saved part/assembly open (`_open_model_path`, `sw_drawing.py:159-185`); `insert_component` needs a file path; `save_active_document` needs an already-saved doc |
| An existing drawing view | `insert_projected_view`, `insert_section_view`, `insert_detail_view`, `set_drawing_view`, `insert_model_annotations`, `auto_dimension_view`, `insert_center_marks`, `insert_centerlines`, `create_drawing_sketch`, `activate_drawing_view` |

`get_bounding_box`, `get_mass_properties` and the topology listings are meaningful only for parts and assemblies: on a drawing `get_bounding_box` returns `ok:false` and the listings come back empty.

**State that goes stale.** Face/edge/vertex/segment indices describe the current model state. Re-list after every geometry change (`SELECTION_SCHEMA` description, `sw_core.py:1130-1136`). Feature tools that take a sketch default to the newest `ProfileFeature` in the tree.

**Things that change what later tools see.** Features, `check_errors`, `rebuild_document` and `add_dimension` call `EditRebuild3`, which exits sketch edit mode (code comment, `sw_sketch.py:866-867`). `insert_standard_views` and friends may activate another document and re-activate the previous one (`sw_drawing.py:125-156`). `save_document` makes the active doc point at the new file.

### 4.2 Suggested live smoke-test order

Prep (not a tool call): set `SW_MCP_OUTPUT_ROOT` to a scratch folder, start SOLIDWORKS 2017 with no documents open and no modal dialogs showing, keep an eye on `solidworks_mcp/server.log`. Because a hung call blocks the whole server, have someone ready to dismiss dialogs. Use only files authored in 2017 (a newer release's files will not open).

| Step | Tools | What to assert |
| --- | --- | --- |
| 0. Preflight and negatives | `solidworks_status` (expect revision 25.x), `get_active_document_info` and `list_features` with no document (expect `ok:false`, message "no active document"), `list_reference_planes` with no document | attach works; precondition errors come back as `ok:false` rather than crashing |
| 1. New part | `create_new_document {kind:"part"}`, `get_active_document_info`, `list_reference_planes`, `list_features` | which template was picked (section 5, item 1); plane names (English "Front Plane" etc.) |
| 2. Sketch | `create_sketch {plane:"front", name:"S_Base"}`, `draw_rectangle`, `draw_circle`, `draw_line`, `draw_centerline`, `draw_arc`, `draw_3point_arc`, `draw_ellipse`, `draw_polygon`, `draw_slot`, `draw_point`, `draw_spline`, `list_sketch_segments`, `list_sketches`; edit tools `sketch_fillet`, `sketch_chamfer`, `sketch_offset`, `sketch_trim`, `sketch_mirror`, `set_construction_geometry`; `add_relation` then `get_sketch_status`; then `add_dimension` (see caution below), `list_dimensions`, `set_dimension`; `close_sketch`, `edit_sketch`, `close_sketch` | each draw tool reports segments added; no dialog appears at the dimension step |
| 3. Features | `boss_extrude` (name it), `list_features`, `rename_feature`, `list_faces`/`list_edges`, `fillet`, `chamfer`, `create_sketch {face_index}` + `draw_circle` + `close_sketch` + `cut_extrude` (also `through_all_both`), `simple_hole`, `shell`, `create_plane {mode:"offset"}`, `create_axis`, `linear_pattern`, `circular_pattern`, `mirror_feature`, `draft`, `rib`, `set_feature_suppression` (twice), `delete_feature` last. Separate small parts for `revolve`, `sweep`, `loft` | `[FR]` reports no `problems`; re-list indices after each change |
| 4. Inspect and appearance | `list_vertices`, `list_bodies`, `get_bounding_box`, `set_material {name:"AISI 1020"}`, `get_mass_properties`, `measure` (expect it to fail on 2017, item 3), `check_errors`, `set_appearance`, `set_view` (all views), `rebuild_document {force_all:true}`, `capture_screenshot` | image returned as a second content item; numbers match the sketch dimensions |
| 5. Save and export | `save_document` (new name under the scratch root, `.sldprt`), `save_active_document`, `export_document` for `.step`, `.stl`, `.x_t`, `.igs`, `.png`, then `.3mf` last | files exist; for STL/3MF watch for an info dialog (item 14); overwrite refusal without `overwrite` |
| 6. Assembly | save the part first, then `create_new_document {kind:"assembly"}`, `insert_component` (the saved part twice, offset), `list_components`, `list_bodies`, `list_faces`, `add_mate` (e.g. coincident on two planar faces), `list_mates`, `set_component_fixed`, `get_bounding_box`, `save_document` (`.sldasm`) | face picks across components work; `list_mates` content (item 12) |
| 7. Drawing | `create_drawing {paper_size:"A3" (or "A"), first_angle:false}` (set both explicitly, items 10 and 19), `list_sheets`, `add_sheet`, `activate_sheet`, `insert_standard_views {model_path:<saved part>, first_angle:false}`, `list_drawing_views`, `insert_model_view`, `insert_projected_view`, `set_drawing_view`, `insert_section_view`, `insert_detail_view`, `insert_model_annotations`, `auto_dimension_view`, `insert_center_marks`, `insert_centerlines`, `add_note`, `save_document` (`.slddrw`) | pass `model_path` because two models are open by now (`sw_drawing.py:183-184` otherwise errors); check by eye the items flagged 4 to 7 |
| 8. Optional | set `SW_MCP_DEMO_TOOLS=1`, restart the server, run `demo_create_basketball`, `demo_upgrade_basketball` | extra revolve/cut coverage |

**Cautions for the order above.**
- `add_dimension`: do not over-define the sketch. Only the "Input dimension value" preference is suppressed; an over-defining dimension may raise the prompt controlled by preference 100 (item 14). Add relations or dimensions that leave the sketch under-defined, or turn that prompt off in SOLIDWORKS options before the run.
- `use_selection: true` on `insert_section_view` / `insert_detail_view` relies on a pre-selected line/circle, but `draw_line`/`draw_circle` do not select what they create. Use the default path (the tool draws the line/circle itself).
- Before `create_drawing`, check the preference `swInsertViewForNewDrawing` (225, "start command when creating new drawing") manually. If it is on, a PropertyManager could remain open (not handled in code; unverified).
- `open_document` is best saved for after step 5 (reopening a file you saved), and only with no unsaved edits in the file being reopened.

---

## 5. Things that could differ on SOLIDWORKS 2017

Evidence legend: **[TLB]** = the 2017 SP5 `sldworks.tlb`/`swconst.tlb`; **[HELP]** = the 2017 `sldworksapi.chm` text; **[code]** = code only (unverified against SOLIDWORKS).

The good news first: every COM member the server calls by name exists in the 2017 type library (this matches the orchestrator's earlier static scan in `docs/PLAN.md`), and for the argument-passing calls I compared by hand the argument counts match what the code sends. The two exceptions are calls made with no arguments that need some (items 3 and 10 below). Counts compared: `FeatureExtrusion3` 23, `FeatureCut4` 27, `FeatureRevolve2` 20, `FeatureFillet3` 14, `InsertFeatureChamfer` 8, `InsertRib` 10, `SimpleHole2` 23, `InsertProtrusionSwept4` 20, `InsertCutSwept5` 22, `InsertProtrusionBlend2` 18, `InsertCutBlend` 12, `FeatureLinearPattern5` 22, `FeatureCircularPattern5` 14, `InsertMirrorFeature2` 5, `InsertRefPlane` 6, `AddMate5` 15, `AddComponent5` 8, `CreateSketchSlot` 14, `SetupSheet5` 11, `NewSheet3` 10, `CreateSectionViewAt5` 7, `CreateDetailViewAt4` 12, `InsertModelAnnotations3` 6, `AutoInsertCenterMarks2` 10. Several of these are marked "SOLIDWORKS 2017 FCS" in the help (`FeatureCut4`, `FeatureLinearPattern5`, `FeatureCircularPattern5`, `InsertCutSwept5`, `InsertProtrusionSwept4`, `CreateDetailViewAt4`, `ForceRebuildAll`), so 2017 is about the oldest release this code could target. The one flag-list entry that is not a member of its interface is `SaveAs3` in `_EXTENSION_METHODS` (`sw_core.py:356`); it exists only on `IModelDoc2`, so `extension()` logs one warning the first time (harmless, it is never called on the extension).

### 5.1 Confirmed mismatches between the code and the 2017 type library / help

| # | Where | Finding | Evidence | Likely effect on the smoke test |
| --- | --- | --- | --- | --- |
| 1 | `sw_file.py:138,141-143`; `sw_core.py:147-174` | `new_document` reads the default template with `GetUserPreferenceStringValue(1/2/3)`. In the 2017 enum, 1/2/3 are `swFileLocationsDocuments`, `swFileLocationsPaletteFeatures`, `swFileLocationsPaletteParts`; the default-template ids are `swDefaultTemplatePart=8`, `swDefaultTemplateAssembly=9`, `swDefaultTemplateDrawing=10`. | [TLB] `swUserPreferenceStringValue_e` | The preference never yields a template file, so `discover_template` always decides. Its search order is `SW_MCP_TEMPLATE_DIR`, then `C:\ProgramData\SOLIDWORKS\SOLIDWORKS *` newest-first, then `~\Documents\SOLIDWORKS Templates`, taking the alphabetically first `*.prtdot/.asmdot/.drwdot` found recursively. On this machine `ProgramData\SOLIDWORKS\SOLIDWORKS 2017\templates` holds `Part.prtdot`, `Part_Metric_MM.prtdot`, `Assembly.asmdot`, `Assembly_Metric_MM.asmdot`, `Drawing.drwdot`, so the plain `Part.prtdot`, `Assembly.asmdot`, `Drawing.drwdot` would be picked, not the user's configured default and not the metric ones. Check the units of the created doc. `SW_MCP_TEMPLATE_DIR` can steer it |
| 2 | `sw_inspect.py:360-365` | `doc.ViewDisplayShadedwithedges()` is not a member of any 2017 interface (only `ViewDisplayShaded` exists). | [TLB] | The `shaded_with_edges` option of `set_view` is a silent no-op (bare `except: pass`); the tool still returns `ok:true` |
| 3 | `sw_inspect.py:283-286` | `IMeasure.Calculate` takes one required argument `Entities` ("if NULL, measures the selected entities"). The code comment says "takes no arguments in this type library" and calls it with none. | [TLB] `IMeasure.Calculate(Entities)`; [HELP] | `measure` is expected to fail with a COM error on 2017 (pywin32 behaviour with a missing required argument not observed). The fix would be to pass a null/empty variant |
| 4 | `sw_drawing.py:73-77,436-437` | `DISPLAY_MODES` (wireframe 1, hidden_lines_removed 2, hidden_lines_grey 3, shaded 4, shaded_with_edges 5) uses `swViewDisplayMode_e` numbering, but `IView.SetDisplayMode3` documents its `Mode` as `swDisplayMode_e` (wireframe 0, hidden greyed 1, hidden 2, shaded 3, ...). Per the help, shaded-with-edges is Mode=`swSHADED` with the `Edges` argument true (and the `swDrawingsDefaultDisplayTypeHLREdgesWhenShaded` option); the code always passes `Edges=False`. | [HELP] `IView.SetDisplayMode3`; [TLB] both enums | `display_mode` on `insert_model_view`/`set_drawing_view` is likely off by one. Failures are swallowed (try/except, logged at INFO). Verify by eye |
| 5 | `sw_drawing.py:735-740` | `target.TangentEdgeDisplay = mode` assigns a property that does not exist on `IView` in 2017 (the members are `SetDisplayTangentEdges2` / `GetDisplayTangentEdges2`). The map visible/hidden/phantom = 1/2/3 also does not match `swEdgesTangentEdgeDisplay_e` (Visible 1, Phantom 2, Removed 3). | [TLB] | `tangent_edges` in `set_drawing_view` is a silent no-op; the tool still returns ok |
| 6 | `sw_drawing.py:576-582` | `options = 1 \| (2 if exclude_fasteners)` is commented as "1 = section, 2 = exclude fasteners". In 2017 `swCreateSectionViewAtOptions_e`: NotAligned 1, OffsetSection 2, ChangeDirection 4, ScaleWithModel 8, Partial 16, DisplaySurfaceCut 32, ExcludeFasteners 64, CutSurfaceBodies 128. | [TLB] | Every section view is created with NotAligned (1); `exclude_fasteners=true` would set OffsetSection (2) instead of 64; `depth_mm` partial depth has no Partial flag (16). Check the result visually |
| 7 | `sw_drawing.py:635-644` | In `CreateDetailViewAt4` the 4th argument `Style` is `swDetViewStyle_e` and the 8th, `Showtype`, is `swDetCircleShowType_e`. The code passes 1 and 2 with comments naming a different enum (`swDetailCircleStyle_e`, which does not exist in the 2017 swconst) and `swDetViewStyle_e`. Read literally, 1 = Broken view style and 2 = Don't show the detail circle. | [HELP] `CreateDetailViewAt4`; [TLB] `swDetViewStyle_e`, `swDetCircleShowType_e` | Detail view may come out with an unexpected style or no visible circle. The parameter-to-enum mapping rests on the help text; verify by eye |
| 8 | `sw_feature.py:231-233` | `revolve` passes `direction_type = 4` for `mid_plane`, commented "swRevolveType_e: 4 = mid plane". `FeatureRevolve2`'s `Dir1Type` is documented as `swEndConditions_e`, where mid plane is 6 (4 = up to surface). | [HELP] `FeatureRevolve2`; [TLB] `swEndConditions_e` | `revolve {mid_plane:true}` probably fails or builds the wrong thing; the default (one direction, 0 = blind) is fine |
| 9 | `sw_inspect.py:254-255` | Inertia is only returned when the result has 15 values; 2017 documents `GetMassProperties2` as a 12-element array (centre of mass 3, volume, surface area, mass, then six moments). | [HELP] `GetMassProperties2` | `get_mass_properties` should work for centre of mass/volume/area/mass/density, but `moments_of_inertia_kg_m2` is not emitted |
| 10 | `sw_drawing.py:252,257` | `ISheet.GetSize(Width, Height)` has two parameters and returns the paper-size enum; the code calls it with none via `safe(...)`, which returns the default 8 (A3) on any exception. Then `SetupSheet5` is applied with that size. `first_angle` also defaults to true. | [TLB], [HELP] `ISheet.GetSize` | `create_drawing` with only `first_angle`/`scale_*` set may silently resize the sheet to A3 and flip to first-angle projection. Pass `paper_size` and `first_angle` explicitly |
| 11 | `sw_feature.py:699-726` (`:719`) | `DeleteSelection2(0)`: `swDeleteSelectionOptions_e` has Children 1, Absorbed 2, Advanced 4. The tool description promises deleting "anything that depends on them", but no flag is passed. | [TLB], [HELP] (the call does not prompt) | Deleting a sketch with a dependent feature may leave the feature in error, or do nothing; verify |
| 12 | `sw_assembly.py:206-217` | `IMate2` in 2017 has `Type` but no `Distance` or `Angle` member (distance lives on the mate's display dimension). | [TLB] | `list_mates` returns names and `mate_type` only |
| 13 | `sw_file.py:179`; `sw_drawing.py:154` | `ActivateDoc3(..., UseUserPreferences=False, Option=0)`: 0 is `swUserDecision` in `swRebuildOnActivation_e`; the help says a dialog asks whether to rebuild if the doc needs it. (The drawing helper passes `True`, which defers to the system option.) | [TLB] `swRebuildOnActivation_e`; [HELP] `ActivateDoc3` | `open_document` can block on a rebuild prompt |
| 14 | `sw_core.py:458-477` | Only `swInputDimValOnCreate` (10) is switched off. Other 2017 toggles that can raise dialogs exist and their state is unknown: `swSketchOverdefiningDimsPromptToSetState` (100), `swSketchPromptToCloseSketch` (96), `swSTLShowInfoOnSave` (70), `sw3MFShowInfoOnSave` (643), `swWarnSavingReferencedDoc` (334), `swWarnSaveUpdateErrors` (329), `swInsertViewForNewDrawing` (225). | [TLB] `swUserPreferenceToggle_e` (names exist; effects not verified) | Possible hangs on over-defining dimensions, STL/3MF export, saving assemblies/drawings with unsaved references, and new drawings. Read the toggles before the run, either in Tools > Options or with a one-off COM script (`ISldWorks.GetUserPreferenceToggle`); no tool exposes them |
| 15 | `sw_core.py:680-693`, `sw_core.py:286-295` | `select_object` tries `Select4(append, selectData)` then `Select2(append, mark)`. In 2017 `Select4` exists on `IEntity`, `ISketchSegment`, `ISketchPoint`, `ISketchHatch` and `IComponent2` (3 args there); `IFeature` and `IBody2` have only `Select2`. `IFace2/IEdge/IVertex` expose neither directly. | [TLB] | The fallback chain is by design. Expect `Select4` to fail for features and bodies, and both calls to fail on late-bound faces/edges/vertices, so those are selected by point (`SelectByID2("", "FACE"/"EDGE"/"VERTEX", x, y, z)`, `sw_core.py:660-677`). Point selection is the path most face/edge-based features will exercise, so watch it first (`fillet`, `chamfer`, `shell`, `draft`, `simple_hole`, `add_mate`) |

### 5.2 Defect that is not version-specific but will fail the smoke test

| # | Where | Finding | Evidence |
| --- | --- | --- | --- |
| 16 | `sw_file.py:305`; `sw_refgeom.py:136`; `sw_sketch.py:457,618`; `sw_assembly.py:196`; `sw_drawing.py:532,560,724,907` | Function-local `from sw_core import ...` (absolute) inside a package whose modules otherwise use `from .sw_core import ...`. `sw_core` is not a top-level module under either supported launch (repo-root `server.py`, console script), so these raise `ModuleNotFoundError`, which `call_tool` turns into `"SOLIDWORKS COM error: No module named 'sw_core'"`. Affected tools: `set_appearance`, `create_axis`, `draw_spline`, `sketch_mirror`, `list_mates`, `insert_section_view` (also via `_draw_in_view`), `insert_detail_view` (via `_draw_in_view`), `set_drawing_view`, `insert_center_marks` with `selected_only`. | Checked offline: `importlib.util.find_spec("sw_core")` is `None` with the repo root on `sys.path`, while `solidworks_mcp.sw_core` resolves. The README says all tools were exercised on SW 2026 SP3.2, so this may only break in some launch layouts; treat as a likely failure to confirm in step 2-4 |

### 5.3 Other version- and environment-sensitive items (code only, unverified)

| # | Where | Note |
| --- | --- | --- |
| 17 | `sw_sketch.py:818-820` | Comment: `ModelDocExtension.AddDimension` "reproducibly crashes SOLIDWORKS 2026 on a sketch selection". The code avoids it by using `ModelDoc2.AddDimension2`. In 2017 `IModelDocExtension.AddDimension` exists (4 args), but it is not used. The README and `flag_methods` (`sw_core.py:303-339`) also warn that argument-taking members called without `_FlagAsMethod` can crash the app; the flagged-member lists are `sw_core.py:342-376`. |
| 18 | `sw_feature.py:93-105`; README "Known limitations" | `through_all_both` is translated to a two-direction through-all because "FeatureExtrusion3 and FeatureCut4 do not honour swEndCondThroughAllBoth" (README: "in SOLIDWORKS 2026"). Behaviour on 2017 untested. The 2017 enum does contain `swEndCondThroughAllBoth = 9`. Test both `boss_extrude`/`cut_extrude` with `end_condition: through_all_both` and compare volumes with `get_mass_properties`. |
| 19 | `sw_drawing.py:339-343`, `:249-258` | `first_angle` defaults to true for `insert_standard_views`, `create_drawing` and `add_sheet` (ISO/GB convention). A US 2017 install normally uses third-angle; pass `first_angle:false` explicitly. |
| 20 | `sw_core.py:162-166` | Comment "so a 2026 install wins over a leftover 2023 one": the discovery sorts `SOLIDWORKS *` folders by name, newest first. No year is hard-coded. `C:\ProgramData\SOLIDWORKS` also contains `SOLIDWORKS Visualize 2017`, which matches the glob and sorts first, but it holds no `.prtdot/.asmdot/.drwdot` files on this machine, so it is skipped. `~\Documents\SOLIDWORKS Templates` does not exist here. |
| 21 | `sw_core.py:575-577,696-711`; `sw_sketch.py:876`; `sw_drawing.py:403-424,1063` | Localization. The code was tested on a Simplified Chinese install. `front/top/right` resolve to reference planes 0/1/2 in tree order, which holds for the default templates; exact names on an English 2017 install should be "Front Plane", "Top Plane", "Right Plane". The `set_dimension` description uses the example `D1@草图1` (English: `D1@Sketch1`). View names come from `GetModelViewNames` (index order normal-to, front, back, left, right, top, bottom, isometric, trimetric, dimetric), with English `*Front` etc. as fallback. `add_note` text mentions `技术要求`, only as an example. |
| 22 | `sw_core.py:60-145`; `sw_sketch.py:68-86,776`; `sw_inspect.py:65-68` | Enum tables confirmed against the 2017 swconst: `swConstrainedStatus_e` (1-based, 1 unknown to 7 autosolve off), `swConstraintType_e` codes used in `RELATIONS`, `swEndConditions_e`, `swMateType_e`, `swMateAlign_e`, `swAddMateError_e`, `swSketchTrimChoice_e`, `swDwgPaperSizes_e`, `swStandardViews_e`, `swRefPlaneReferenceConstraints_e`, `swFeatureFilletOptions_e`, `swChamferType_e`, `swFeatureChamferOption_e`, `swInsertAnnotation_e` bits, `swAutodim*`, `swCenterMarkStyle_e`, `swSketchSlot*`, `swSketchSegments_e`, `swSurfaceTypes_e`, `swCurveTypes_e`, `swBodyType_e`, `swDrawingViewTypes_e`, `swDimensionType_e`, `swOpenDocOptions_e`. Feature-type strings the code matches (`RefPlane`, `RefAxis`, `ProfileFeature`, `MateGroup`) and `SelectByID2` type strings (`PLANE`, `AXIS`, `SKETCH`, `BODYFEATURE`, `COMPONENT`, `DRAWINGVIEW`, `FACE`, `EDGE`, `VERTEX`) are long-standing; confirm with the first `list_features` output rather than assuming. |
| 23 | `sw_file.py:86`; `sw_inspect.py:382` | `ModelDocExtension.SaveAs(path, 0, 0, nothing, err, warn)` is used for every format with Version 0 and Options 0 (not Silent). `Save3` is called with options 1 (Silent). Exports to `.3mf` rely on 2017 supporting that format through `SaveAs` (user-preference toggles for 3MF exist in the 2017 swconst, so the format is known to it), but this was not exercised. |
| 24 | `sw_sketch.py:853,899` | `SetSystemValue3(value, 2, empty)`: 2 is `swSetValue_InAllConfigurations` (confirmed in the 2017 enum). |
| 25 | `pyproject.toml`; `sw_inspect.py:394-406` | Dependencies are `mcp>=1.29,<2`, `pywin32>=306`, `pillow>=10`, Python 3.10+. `capture_screenshot` falls back to returning the raw SOLIDWORKS PNG if Pillow fails to resize it. |

---

## Appendix: how the 2017 evidence was gathered

Read-only scripts parsed `sldworks.tlb` and `swconst.tlb` with `pythoncom.LoadTypeLib` (no SOLIDWORKS instance, no `GetActiveObject`) to enumerate members, argument counts and enums, and `7z` extracted `sldworksapi.chm` into a scratch directory to read parameter descriptions and "Availability" lines. Nothing was written into the repository other than this file. The repo's own `tools/tlb_probe.py` does the same job (`python tools/tlb_probe.py methods '^IMeasure$' '^Calculate$'`, `... enums '^swCreateSectionViewAtOptions_e$'`), but its path discovery tries `GetActiveObject`, so set `SW_MCP_INSTALL_DIR` and keep SOLIDWORKS closed if you use it.
