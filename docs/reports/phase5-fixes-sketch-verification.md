# Verification: Phase 5 sketch fixes (#7, #11-#15)

Offline review. Suite: 609 tests OK. All new SW members are in `tools/compat/sw2017_api_members.txt` (checked each; `SketchFillet2` is `IModelDoc2`, which is what the code calls).

| Item | Verdict | Notes |
|---|---|---|
| (a) #7 identity | PASS (live-unverified) | `.venv/Lib/site-packages/win32com/client/dynamic.py:276` `CDispatch.__eq__` delegates to `_oleobj_ == other`, which is a PyIUnknown identity compare. `same_com_object` catches exceptions and returns False. Chain is identity, then hint, then newest. Weakness: SW may return a different wrapper object for the same ISketch, so `==` could fail; then the hint takes over. `_OPEN_SKETCH_HINT` is a module global, not per document, so it can go stale after a document switch or a sketch opened in the UI. |
| (b) #11 corners | PASS | Segments are re-read per corner, selection is cleared before and after each, and success is judged by segment count +1. The arc-already-present check uses the tangent intersection. Exactly 2 hits are required. Renumbering is safe because only live objects are used. Minor: `x_mm` is accepted in code but not in the schema. |
| (c) #12 construction | PASS, with a gap | `ConstructionGeometry = True` is set as a property, on the pre-offset source segments, with the chain closure. Gap: `_segment_ends` ignores splines and ellipses, so they are not chained, and a chained spline is silently left as non-construction. |
| (d) #13 Fixed relation | PASS, with a risk | Removal is in `finally`, and the relation is found by a before/after diff. If `==` ever returns False, `added` becomes all relations and the first Fixed relation is deleted. That could be a pre-existing one, and the count check would still read "removed". Suggest guarding that case. Minor: a leak is possible if the code between `AddRelation` and `try` raises. |
| (e) #14 undo | PASS, limited | The in-sketch comparison uses segment and point counts. A step that changes only dimensions or relations reports `ok=False` ("refused"). |
| (f) #15 axes | PASS | The ArrayData layout 3*col+row matches sw_assembly. The columns of the inverse are the sketch axes, and the translation is at 9..11, converted from metres to mm. The expected Front/Top/Right vectors are correct. Test weakness: the mock `Inverse` returns itself, so the inversion step is not tested. |
| (g) Back-compat | PASS | Existing args and result keys are unchanged; `sketch_fillet` now requires only `radius_mm`, and the index mode is kept. |
| (h) Compat list | PASS | All new members are present. |
