from fleetmanager.diffview import side_by_side

A = "\n".join("line%d" % i for i in range(1, 21))


def test_identical():
    d = side_by_side(A, A)
    assert d["identical"] and d["rows"] == [{"t": "skip", "n": 20}]


def test_change_add_delete_with_context_and_numbers():
    b = A.replace("line10", "LINE10") + "\nextra"
    b = "\n".join(ln for ln in b.split("\n") if ln != "line3")
    d = side_by_side(A, b, context=1)
    assert d["stats"] == {"chg": 1, "add": 1, "del": 1}
    rows = d["rows"]
    chg = next(r for r in rows if r["t"] == "chg")
    assert (chg["l"], chg["r"], chg["ll"]) == ("line10", "LINE10", 10)
    deleted = next(r for r in rows if r["t"] == "del")
    assert deleted["l"] == "line3" and deleted["r"] is None and deleted["rl"] is None
    added = next(r for r in rows if r["t"] == "add")
    assert added["r"] == "extra" and added["l"] is None
    assert any(r["t"] == "skip" for r in rows)
    assert sum(r.get("n", 0) for r in rows if r["t"] == "skip") + sum(1 for r in rows if r["t"] != "skip") >= 20


def test_negative_context_keeps_everything():
    d = side_by_side(A, A.replace("line5", "x"), context=-1)
    assert len(d["rows"]) == 20 and not any(r["t"] == "skip" for r in d["rows"])
