import json
import sys
from pathlib import Path
from shutil import copytree

import pytest

from corpus_catalog.cli import main


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mini_brief"


def copy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "mini_brief"
    copytree(FIXTURE_ROOT, root)
    return root


def test_index_defaults_root_to_current_working_directory(
    tmp_path, monkeypatch, capsys
):
    root = copy_fixture(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["catalog", "index"])

    main()

    output = capsys.readouterr().out
    manifest = json.loads(output)
    assert manifest["corpus_root"] == str(root.resolve())
    assert manifest["catalog_dir"] == str(root.resolve() / ".corpus")
    assert manifest["source_count"] == 14


def test_no_args_defaults_to_status_in_corpus_root(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["catalog"])

    main()

    output = capsys.readouterr().out
    assert "Catalog state: missing" in output
    assert f"Corpus root: {root.resolve()}" in output
    assert f"Generated state dir: {root.resolve() / '.corpus'}" in output


def test_no_args_prints_help_outside_corpus_root(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["catalog"])

    main()

    output = capsys.readouterr().out
    assert "usage: catalog" in output
    assert "Catalog state:" not in output


def test_no_args_ignores_legacy_catalog_directory(tmp_path, monkeypatch, capsys):
    (tmp_path / ".catalog").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["catalog"])

    main()

    output = capsys.readouterr().out
    assert "usage: catalog" in output
    assert "Catalog state:" not in output


def test_version_cli_reports_release_metadata(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["catalog", "version", "--format", "json"])

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "catalog_version": "0.2.0",
        "validated_corpus_spec_version": "v0.20",
    }


def test_search_cli_emits_compact_results(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["catalog", "index"])
    main()
    capsys.readouterr()

    monkeypatch.setattr(
        sys,
        "argv",
        ["catalog", "search", "--query", "demo project", "--limit", "1"],
    )
    main()

    results = json.loads(capsys.readouterr().out)
    assert len(results) == 1
    assert set(results[0]) == {
        "source",
        "title",
        "snippet",
        "metadata",
        "content_hash",
    }
    assert "text" not in results[0]
    assert results[0]["snippet"]
    assert len(results[0]["snippet"]) < 400
    assert "## Active Epics" not in json.dumps(results)


def test_stats_cli_emits_json(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["catalog", "stats", "--format", "json"])

    main()

    stats = json.loads(capsys.readouterr().out)
    assert stats["corpus_root"] == str(root.resolve())
    assert stats["total_file_count"] > 0
    assert stats["catalog_visible_source_count"] == 14


def test_health_cli_emits_json(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    large_file = root / "large.bin"
    large_file.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["catalog", "health", "--format", "json"])

    main()

    report = json.loads(capsys.readouterr().out)
    assert report["corpus_root"] == str(root.resolve())
    assert any(issue["code"] == "health-large-local-file" for issue in report["issues"])


def test_search_cli_sees_epic_local_reference(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["catalog", "index"])
    main()
    capsys.readouterr()

    monkeypatch.setattr(
        sys,
        "argv",
        ["catalog", "search", "--query", "demo candidate detail", "--limit", "1"],
    )
    main()

    results = json.loads(capsys.readouterr().out)
    assert len(results) == 1
    assert (
        results[0]["source"]["path"]
        == "projects/demo/assets/epics/001-DEMO/reference/demo-candidate.md"
    )


def test_mounts_cli_reports_and_registers_current_mount(
    tmp_path,
    monkeypatch,
    capsys,
):
    root = copy_fixture(tmp_path)
    registry_home = tmp_path / "corpus-home"
    monkeypatch.setenv("CORPUS_HOME", str(registry_home))
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["catalog", "mounts", "--format", "json"])

    main()

    inventory = json.loads(capsys.readouterr().out)
    assert inventory["registry_path"] == str(registry_home / "mounts.json")
    assert inventory["registry_updated"] is True
    assert inventory["current_mount"]["mount_uri"] == "corpus://cmikeb/work/brief@bilby"
    assert inventory["known_mounts"][0]["mount_uri"] == (
        "corpus://cmikeb/work/brief@bilby"
    )


def test_validate_warns_when_current_mount_is_not_registered(
    tmp_path,
    monkeypatch,
    capsys,
):
    root = copy_fixture(tmp_path)
    registry_home = tmp_path / "corpus-home"
    monkeypatch.setenv("CORPUS_HOME", str(registry_home))
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["catalog", "validate", "--format", "json"])

    main()

    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert "warning: Current mount corpus://cmikeb/work/brief@bilby" in captured.err
    assert f"run catalog mounts --root {root.resolve()}" in captured.err


def test_validate_does_not_warn_when_current_mount_is_registered(
    tmp_path,
    monkeypatch,
    capsys,
):
    root = copy_fixture(tmp_path)
    registry_home = tmp_path / "corpus-home"
    monkeypatch.setenv("CORPUS_HOME", str(registry_home))
    monkeypatch.chdir(root)

    monkeypatch.setattr(sys, "argv", ["catalog", "mounts"])
    main()
    capsys.readouterr()

    monkeypatch.setattr(sys, "argv", ["catalog", "validate", "--format", "json"])
    main()

    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert captured.err == ""


def test_search_cli_accepts_declared_corpus_alias(tmp_path, monkeypatch, capsys):
    root = copy_fixture(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(sys, "argv", ["catalog", "index"])
    main()
    capsys.readouterr()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "catalog",
            "search",
            "--corpus",
            "work/brief",
            "--query",
            "demo project",
            "--limit",
            "1",
        ],
    )
    main()

    results = json.loads(capsys.readouterr().out)
    assert len(results) == 1


def test_context_cli_rejects_other_declared_corpus(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "catalog",
            "context",
            "--corpus",
            "icloud/brief",
            "--goal",
            "demo project",
        ],
    )

    with pytest.raises(SystemExit):
        main()
