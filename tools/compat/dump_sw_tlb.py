"""Dump every Interface.Member from the installed SOLIDWORKS 2017 type libraries.

Usage:  .venv\Scripts\python.exe tools/compat/dump_sw_tlb.py tools/compat/sw2017_api_members.txt
Note: the registry shows the typelib version as "19.0" -- that is HEX (0x19 = 25 = SW2017).
"""
import sys, pythoncom
LIBS = {
    "sldworks": ("{83A33D31-27C5-11CE-BFD4-00400513BB57}", 0x19, 0),
    "swconst":  ("{4687F359-55D0-4CD3-B6CF-2EB42C11F989}", 0x19, 0),
}
out = sys.argv[1]
names = set()
for tag, (guid, ma, mi) in LIBS.items():
    tlb = pythoncom.LoadRegTypeLib(guid, ma, mi, 0)
    for i in range(tlb.GetTypeInfoCount()):
        ti = tlb.GetTypeInfo(i)
        ta = ti.GetTypeAttr()
        iname = tlb.GetDocumentation(i)[0]
        for f in range(ta.cFuncs):
            fd = ti.GetFuncDesc(f)
            names.add(f"{iname}.{ti.GetNames(fd.memid)[0]}")
        for v in range(ta.cVars):
            vd = ti.GetVarDesc(v)
            names.add(f"{iname}.{ti.GetNames(vd.memid)[0]}")
with open(out, "w") as fh:
    fh.write("\n".join(sorted(names)))
print(len(names), "members written to", out)
