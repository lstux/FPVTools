import pytest

from esptracker.__main__ import main


@pytest.mark.parametrize(
    "argv",
    [
        ["--simulate", "--port", "x"],  # two sources
        ["--replay", "/nonexistent.jsonl"],
        ["--simulate", "--mbtiles", "/nonexistent.mbtiles"],
        ["--simulate", "--home", "48.1,-1.6"],  # malformed --home
        ["--port", "/dev/null", "--home", "a,b,c"],
    ],
)
def test_bad_arguments_exit_cleanly(argv, capsys):
    assert main(argv) == 2
    assert capsys.readouterr().err.startswith("error:")


def test_help_and_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "esptracker" in capsys.readouterr().out
