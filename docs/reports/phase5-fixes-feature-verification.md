# Verification: phase5 fixes, sw_feature (#5, #8, #9, #17)

Offline review only. Full suite: 609 tests OK.

| Item | Result | Notes |
|---|---|---|
| (a) #5 direction | PASS with one minor defect | Flag table matches the field observation (cut default -Z, so +normal needs Dir=True; boss default +Z). Mid-plane and through_all_both report symmetric. direction_vector math is sound: inverse of ModelToSketchTransform applied to the origin and (0,0,1), normalised, so units cancel. Minor: when the part had no body, `_volume_mm3` returns None, so `volume_delta_mm3` is None for the first boss even though `volume_after_mm3` is known (sw_feature.py:413-417; `before` should be treated as 0 when after is valid and the document had no solid body). |
| (b) #8 delete_feature | PASS | ClearSelection2(True) first, then Select2(False) for the first pick and Select2(True) for the rest, so nothing is appended to a stale selection. Names match exact first, then a unique case-insensitive match; ambiguous or unknown names are errors. The before/after check uses names plus count, and fails if a requested feature remains. |
| (c) #9 IsSuppressed2 | PASS | IsSuppressed2 is flagged via flag_methods. Args are (3 = swSpecifyConfiguration, a BSTR array of the active configuration), so it reads the active configuration only. Falls back to the IsSuppressed property. IFeature.IsSuppressed2 is in the compat list. |
| (d) #17 fillets | PASS | Chains and vertex_radii are refused with clear messages, before and after the selection. The options bits are UNIFORM (2) and PROPAGATE (1) and are reported back. |
| (e) Compat | PASS | `reverse` still works alone. Giving both direction and reverse is an error. The schema default on `reverse` was removed, and no other caller or test relies on it: sw_edit uses only `_ExtrudePlan`, and live scripts pass reverse explicitly. |
| (f) Compat list | PASS | Every new member is in `tools/compat/sw2017_api_members.txt`: IsSuppressed2, MultiplyTransform, Inverse, CreatePoint, GetMathUtility, ModelToSketchTransform, ArrayData, GetSpecificFeature2, ClearSelection2, DeleteSelection2, GetActiveConfiguration, Name. |
