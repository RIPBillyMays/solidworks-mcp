r"""Dump every Interface.Member from the installed SOLIDWORKS 2017 type libraries.

Usage:  .venv\Scripts\python.exe tools/compat/dump_sw_tlb.py tools/compat/sw2017_api_members.txt [tools/compat/sw2017_enums.txt]
The optional second path receives enum values as ``enumName.memberName=value``
(default: sw2017_enums.txt beside the members file), so offline tests can check
the numeric constants in the code against what the 2017 type library says.
Note: the registry shows the typelib version as "19.0" -- that is HEX (0x19 = 25 = SW2017).
"""
import sys, pythoncom
LIBS = {
    "sldworks": ("{83A33D31-27C5-11CE-BFD4-00400513BB57}", 0x19, 0),
    "swconst":  ("{4687F359-55D0-4CD3-B6CF-2EB42C11F989}", 0x19, 0),
}
import os
out = sys.argv[1]
enum_out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(out)), "sw2017_enums.txt")
names = set()
enums = set()
for tag, (guid, ma, mi) in LIBS.items():
    tlb = pythoncom.LoadRegTypeLib(guid, ma, mi, 0)
    for i in range(tlb.GetTypeInfoCount()):
        ti = tlb.GetTypeInfo(i)
        ta = ti.GetTypeAttr()
        iname = tlb.GetDocumentation(i)[0]
        is_enum = ta.typekind == pythoncom.TKIND_ENUM
        for f in range(ta.cFuncs):
            fd = ti.GetFuncDesc(f)
            names.add(f"{iname}.{ti.GetNames(fd.memid)[0]}")
        for v in range(ta.cVars):
            vd = ti.GetVarDesc(v)
            vname = ti.GetNames(vd.memid)[0]
            names.add(f"{iname}.{vname}")
            if is_enum:
                enums.add(f"{iname}.{vname}={vd.value}")
with open(out, "w") as fh:
    fh.write("\n".join(sorted(names)))
with open(enum_out, "w") as fh:
    fh.write("\n".join(sorted(enums)))
print(len(names), "members written to", out)
print(len(enums), "enum values written to", enum_out)
