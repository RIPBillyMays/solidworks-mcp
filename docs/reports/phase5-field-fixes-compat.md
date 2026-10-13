# Phase 5 field fixes: SW2017 compat check

Source: tools/compat/sw2017_api_members.txt (typelib dump), sw2017_enums.txt. compat_allowlist.txt holds no real members (comments only).

## Members
| Requested | Status in 2017 list |
|---|---|
| ISketchManager.AddToDB | present |
| ISketchManager.DisplayWhenAdded | present |
| ISketchSegment.GetStartPoint2/GetEndPoint2 | MISSING on ISketchSegment. Use ISketchLine.GetStartPoint2/GetEndPoint2 (also GetStartPoint/GetEndPoint) and ISketchArc.GetStartPoint2/GetEndPoint2 |
| ISketchArc.GetCenterPoint2 | present (also GetCenterPoint) |
| IBody2.GetExtremePoint | present |
| ISketch.ModelToSketchTransform | present |
| IFeature.IsSuppressed2 | present (also IsSuppressed) |
| IFeature.GetSuppression2 / GetSuppression | MISSING (no IFeature.GetSuppression*). Use IFeature.IsSuppressed2 (needs swInConfigurationOpts + config names args) or IFeature.IsSuppressed |
| IModelDoc2.ClearSelection2 | present (also ClearSelection) |
| ISketchSegment.ConstructionGeometry | present (property) |
| IModelDocExtension.SelectByID2 | present |
| IFeature.GetErrorCode2 | present (also GetErrorCode) |
| IFeature.GetSpecificFeature2 | present (also GetSpecificFeature) |
| ISldWorks.ActivateDoc3 | present (also ActivateDoc, ActivateDoc2) |
| ISldWorks.Get/SetUserPreferenceToggle | present |
| IModelDocExtension.Get/SetUserPreferenceToggle | present |
| IBody2.GetFaceCount | present |
| ISketchRelationManager.AddRelation | present (also IAddRelation) |

## Enums (swUserPreferenceToggle_e)
- swSketchInference=249
- swInputDimValOnCreate=10
- swSketchAutomaticRelations=9
- swSnapToPoints=60, swSnapToAngle=61
- swSketchSnapsPoints=266, CenterPoints=267, MidPoints=268, QuadrantPoints=269, Intersections=270, Nearest=271, Tangent=272, Perpendicular=273, Parallel=274, HVLines=275, HVPoints=276, Length=277, Grid=278, ToGridIfDisplayed=279, Angle=280
- swScaleSketchOnFirstDimension=642

## swFeatureFilletOptions_e (all)
Propagate=1, UniformRadius=2, VarRadiusType=4, UseHelpPoint=8, UseTangentHoldLine=16, CornerType=32, AttachEdges=64, KeepFeatures=128, CurvatureContinuous=256, ConstantWidth=512, NoTrimNoAttached=1024, ReverseFace1Dir=2048, ReverseFace2Dir=4096, PropagateFeatToParts=8192, Asymmetric=16384.
No separate tangent-propagation bit: swFeatureFilletPropagate (1) is the only one.

## Current code
- Endpoint reads: solidworks_mcp/sw_core.py:1233-1234 (GetStartPoint2/GetEndPoint2 on line segments, via value()), arc centre at :1238 (GetCenterPoint2). Only place in the package.
- whats_wrong defined sw_core.py:1610; used sw_core.py:1636,1645 (feature_result), sw_edit.py:280,353, sw_feature.py:1110, sw_file.py:705 (rebuild_document), sw_inspect.py:337. It does not filter is_warning.
- ClearSelection2 already used: sw_core.py:676 and listed in flag_methods at :377.
