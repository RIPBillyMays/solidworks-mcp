# Phase 5 Batch B: document data tools (offline implementation)

New module `solidworks_mcp/sw_docdata.py` (registered by one import line in `server.py`), tests in `tests/test_sw2017_batchB_docdata.py` (31 tests). Full suite: 258 tests OK. Smoke lists 134 tools including the 18 new ones. Nothing run live, nothing committed.

Also touched: `tests/test_sw2017_enums.py` (18 `VERIFIED_ELSEWHERE` entries for the new constant tables, required by its coverage test).

## Tools (18)
| Area | Tool | Main 2017 members |
|---|---|---|
| Configs | `list_configurations`, `add_configuration` (plain or derived via `parent`), `activate_configuration`, `delete_configuration` (auto-switches if active), `rename_configuration` | GetConfigurationNames, GetConfigurationByName, AddConfiguration3, ConfigurationManager.AddConfiguration (6 args, parent), ShowConfiguration2, DeleteConfiguration2, IConfiguration.Name/Description/Comment/IsDerived/GetParent |
| Per-config | `set_config_feature_suppression` (this/all/specified, per-config readback), `set_dimension_config` (this/all/specified) | IFeature.SetSuppression2/IsSuppressed2, IDimension.SetSystemValue3 |
| Equations | `list_equations` (evaluates, solver status), `add_equation` (global variable, dimension equation, raw), `edit_equation`, `delete_equation` | GetEquationMgr, GetCount, Equation, Value, GlobalVariable, Status, Add3, SetEquationAndConfigurationOption, Delete, EvaluateAll |
| Properties | `list_custom_properties`, `set_custom_property` (text/number/double/date/yesno), `delete_custom_property`; file level or per configuration | Extension.CustomPropertyManager(cfg), Get4 (by-ref strings), GetType2, Add3, Delete2, GetNames |
| Mass | `get_configuration_mass_properties`, `set_mass_override` | Extension.CreateMassProperty, IMassProperty.Mass/Volume/SurfaceArea/CenterOfMass/OverrideMass/UserAssigned |
| Units | `get_document_units`, `set_document_units` | IModelDoc2.Get/SetUserPreferenceIntegerValue (swUnitSystem 263, swUnitsLinear 47, decimals 49/52, mass-prop 258-261) |

## 2017 findings from the snapshot
- `ICustomPropertyManager.Get5` is ABSENT (the gap analysis said OK); `Get4` is used. `Add3`, `Delete2`, `GetType2` present.
- `IMassProperty` has no density setter. A real density override is not possible through the API; `set_mass_override(density_g_per_cm3=...)` is a what-if that changes nothing and says so. Mass override uses `OverrideMass` and the result states honestly whether it persisted in the document.
- `swSetValueInConfiguration_e` (1 this, 2 all, 3 specified) and `swInConfigurationOpts_e` (1/2/3) are separate enums with the same numbers; each is pinned in the tests.
- `set_dimension` (sw_sketch.py) was left alone; the scoped variant is the new `set_dimension_config`.

## FORK_CHANGES lines (orchestrator to add; I did not edit the file)
- `solidworks_mcp/sw_docdata.py` (new): configurations, per-configuration suppression and dimension values, equations/global variables, custom properties, configuration mass properties and mass override, document units (18 tools).
- `solidworks_mcp/server.py`: one import line for `sw_docdata`.
- `tests/test_sw2017_enums.py`: `VERIFIED_ELSEWHERE` entries for `sw_docdata` tables.
- `tests/test_sw2017_batchB_docdata.py` (new).

## Live verification checklist (serial, sandbox part with a sketch dimension and a boss feature)
1. `add_configuration` Short (plain) and Kid (derived from Default): names list grows, `derived`/`parent` correct, active configuration unchanged (DontActivate=128 honoured). With `activate=true` the new one is active.
2. `delete_configuration` of the active one: switches and deletes; last configuration refused.
3. `rename_configuration`: name changes, active retained.
4. `set_config_feature_suppression` specified=[Short]: volume differs only in Short (use `get_configuration_mass_properties`); `suppressed_by_configuration` readback matches; also `all` and `this`. Confirm `IsSuppressed2(3, names)` returns one bool per configuration (array shape).
5. `set_dimension_config` specified=[Short]: Default value unchanged, Short changed (activate each and `list_dimensions`); `this` and `all` likewise.
6. Equations: add global variable `"w"= 40` (check units: bare number is read in document units); add `"D1@Sketch1"= "w" * 2`; change `w` with `edit_equation` and confirm bbox follows; `delete_equation`; confirm `Equation(i)` / `Value(i)` / `GlobalVariable(i)` flag-and-call works (PROPGET with args) and what unit `Value` is returned in (metres vs document units); try a deliberately bad equation and check `Status` != 0 with no modal dialog. Confirm `Add3` argument order (index, text, solve, option, names) and that index = count appends.
7. Custom properties: file level text with `$PRP` link (resolved value differs), configuration-specific number, date and yesno; check the by-ref `Get4` VARIANT pattern returns both strings; save/reopen and read back; confirm which of `number` (3) or `double` (5) shows as "Number" in the UI; date string format SOLIDWORKS accepts; delete returns status 1 when absent.
8. `get_configuration_mass_properties`: masses per configuration, original configuration restored; compare with `get_mass_properties`. Assembly case too.
9. `set_mass_override`: does `OverrideMass = x` persist (fresh `CreateMassProperty` shows x, `UserAssigned` true)? If not, the tool reports `persisted=false`; then fence or drop the mass branch. Check `clear=true` restores the computed mass. Density what-if must change nothing.
10. Units: `set_document_units` to ips, custom with length_unit in, decimals; read back via `get_document_units`; verify `IModelDoc2.SetUserPreferenceIntegerValue` takes 263 directly (else switch to `Extension.SetUserPreferenceInteger`); angle unit and mass-prop units. Restore the document afterwards (not automatic).
11. Confirm no modal dialogs appear during any step, and that `dialogs_suppressed` toggles are restored.
