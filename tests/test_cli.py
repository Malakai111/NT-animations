import json
from pathlib import Path

from ntrack.cli import main


def test_generate_to_stdout(capsys):
    rc = main(["generate", "--seed", "abc", "--lanes", "2"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["seed"] == "abc"
    assert data["lane_count"] == 2


def test_generate_to_file(tmp_path):
    out = tmp_path / "track.json"
    rc = main(["generate", "--seed", "abc", "--out", str(out)])
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["seed"] == "abc"


def test_build(tmp_path):
    rc = main(["build", "--seed", "abc", "--outdir", str(tmp_path / "dist")])
    assert rc == 0
    dist = tmp_path / "dist"
    assert (dist / "nt-track.user.js").exists()
    assert (dist / "preview.html").exists()
    assert (dist / "track.json").exists()
    js = (dist / "nt-track.user.js").read_text(encoding="utf-8")
    assert "==UserScript==" in js