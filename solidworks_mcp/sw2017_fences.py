# Fork addition for SOLIDWORKS 2017 support (see docs/adr/0006-sw2017-tool-fencing.md).
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

"""Fence tools that have no working route on SOLIDWORKS 2017.

A fenced tool stays listed (so a client can read why it is unavailable) but its
handler never touches COM and always answers ``ok: false`` with ``fenced: true``.
The registry lives here, not in the upstream tool modules, so a fence never
causes an upstream merge conflict.  Set ``SW_MCP_DISABLE_FENCES=1`` to skip the
fences, e.g. for a live re-probe.
"""

from __future__ import annotations

import os
from collections.abc import Callable, MutableMapping, MutableSequence
from typing import Any

from .sw_core import result

# tool name -> why it cannot work on 2017.  Keep reasons free of a trailing full stop.
FENCES: dict[str, str] = {
    "auto_dimension_view": (
        "IDrawingDoc.AutoDimension is sketch-level auto-dimension in 2017 and adds no "
        "dimensions to a drawing view; use insert_model_annotations"
    ),
}

PREFIX = "NOT SUPPORTED ON SOLIDWORKS 2017: "


def _fenced_handler(reason: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        return result(False, f"Not supported on SOLIDWORKS 2017: {reason}", fenced=True)

    return handler


def apply_fences(tools: MutableSequence[Any], handlers: MutableMapping[str, Any]) -> None:
    """Rewrite fenced tools in place.  An unknown tool name raises KeyError.

    Failing loudly matters: if upstream renames a fenced tool, a silent skip
    would quietly un-fence it.
    """
    if os.environ.get("SW_MCP_DISABLE_FENCES") == "1":
        return
    by_name = {t.name: t for t in tools}
    for name, reason in FENCES.items():
        if name not in by_name or name not in handlers:
            raise KeyError(f"Fenced tool '{name}' is not registered; update sw2017_fences.FENCES")
        tool = by_name[name]
        if not str(tool.description).startswith(PREFIX):
            tool.description = f"{PREFIX}{reason}. {tool.description}"
        handlers[name] = _fenced_handler(reason)
