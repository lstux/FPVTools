"""Side-by-side line diff between two configuration snapshots, ready for the web UI."""

from __future__ import annotations

import difflib
from typing import Any, Dict, List

from .volatile import mask


def side_by_side(a: str, b: str, context: int = 3, calibration: bool = False) -> Dict[str, Any]:
    """Rows of ``{t, ll, l, rl, r}`` where ``t`` is eq / cal / chg / del / add / skip.

    Unless ``calibration`` is true, values the firmware rewrites by itself (see ``volatile``) are
    compared without their value: a row where only they differ is ``cal`` and counts as unchanged.

    ``ll``/``rl`` are 1-based line numbers on the left (a) and right (b); a ``skip`` row carries the
    number of hidden unchanged lines in ``n``. ``context`` < 0 keeps every line.
    """
    left, right = a.splitlines(), b.splitlines()
    key = (lambda x: x) if calibration else mask
    rows: List[Dict[str, Any]] = []
    matcher = difflib.SequenceMatcher(None, [key(x) for x in left], [key(x) for x in right], autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        for k in range(max(i2 - i1, j2 - j1)):
            li, ri = i1 + k, j1 + k
            has_l, has_r = li < i2, ri < j2
            if tag == "equal":
                kind = "eq" if left[li] == right[ri] else "cal"
            else:
                kind = "chg" if has_l and has_r else ("del" if has_l else "add")
            rows.append(
                {
                    "t": kind,
                    "ll": li + 1 if has_l else None,
                    "l": left[li] if has_l else None,
                    "rl": ri + 1 if has_r else None,
                    "r": right[ri] if has_r else None,
                }
            )

    stats = {k: sum(1 for r in rows if r["t"] == k) for k in ("chg", "add", "del")}
    calibrated = sum(1 for r in rows if r["t"] == "cal")
    if context >= 0:
        keep = [False] * len(rows)
        for i, row in enumerate(rows):
            if row["t"] not in ("eq", "cal"):
                for j in range(max(0, i - context), min(len(rows), i + context + 1)):
                    keep[j] = True
        out: List[Dict[str, Any]] = []
        hidden = 0
        for row, k in zip(rows, keep):
            if k:
                if hidden:
                    out.append({"t": "skip", "n": hidden})
                    hidden = 0
                out.append(row)
            else:
                hidden += 1
        if hidden:
            out.append({"t": "skip", "n": hidden})
        rows = out
    stats["cal"] = calibrated
    return {"rows": rows, "stats": stats, "identical": not any(stats[k] for k in ("chg", "add", "del"))}
