from pathlib import Path
from shutil import copytree
import json
import subprocess

from corpus_catalog.config import CatalogConfig
from corpus_catalog.health import build_corpus_stats, build_health_report
from corpus_catalog.identity import build_mount_inventory, read_known_mounts
from corpus_catalog.corpus import load_corpus


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "mini_brief"


def copy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "mini_brief"
    copytree(FIXTURE_ROOT, root)
    return root


def test_stats_surfaces_source_code_identity_without_corpusignore(tmp_path):
    root = copy_fixture(tmp_path)
    package = root / "projects" / "demo" / "code" / "widget"
    package.mkdir(parents=True)
    (package / "README.md").write_text("# Widget\n", encoding="utf-8")
    (package / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    config = CatalogConfig(corpus_root=root)

    stats = build_corpus_stats(config)

    source_dir = next(
        directory
        for directory in stats.source_code_directories
        if directory.path == "projects/demo/code/widget"
    )
    assert source_dir.markers == ["pyproject.toml"]
    assert source_dir.readme_path == "projects/demo/code/widget/README.md"
    assert source_dir.ignored_by_corpusignore is False


def test_health_recommends_corpusignore_for_source_code_dir(tmp_path):
    root = copy_fixture(tmp_path)
    package = root / "projects" / "demo" / "code" / "widget"
    package.mkdir(parents=True)
    (package / "README.md").write_text("# Widget\n", encoding="utf-8")
    (package / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    config = CatalogConfig(corpus_root=root)

    report = build_health_report(config)

    issue = next(
        issue
        for issue in report.issues
        if issue.code == "health-corpusignore-source-code-dir"
    )
    assert issue.path == "projects/demo/code/widget"
    assert "pyproject.toml" in issue.message
    assert "README.md" in issue.message


def test_health_respects_corpusignore_for_source_code_dir(tmp_path):
    root = copy_fixture(tmp_path)
    package = root / "projects" / "demo" / "code" / "widget"
    package.mkdir(parents=True)
    (package / "README.md").write_text("# Widget\n", encoding="utf-8")
    (package / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (root / ".corpusignore").write_text(
        "projects/demo/code/widget/\n", encoding="utf-8"
    )
    config = CatalogConfig(corpus_root=root)

    report = build_health_report(config)

    assert not any(
        issue.code == "health-corpusignore-source-code-dir"
        for issue in report.issues
    )


def test_health_flags_large_tracked_file(tmp_path):
    root = copy_fixture(tmp_path)
    large_file = root / "assets.bin"
    large_file.write_bytes(b"x" * (1024 * 1024 + 1))
    subprocess.run(("git", "init"), cwd=root, check=True, capture_output=True)
    subprocess.run(("git", "add", "assets.bin"), cwd=root, check=True)
    config = CatalogConfig(corpus_root=root)

    report = build_health_report(config)

    issue = next(
        issue
        for issue in report.issues
        if issue.code == "health-large-tracked-file"
    )
    assert issue.path == "assets.bin"
    assert issue.severity == "warning"
    assert issue.tracked_by_git is True


def test_health_suggests_heavier_registered_mounts(tmp_path, monkeypatch):
    root = copy_fixture(tmp_path)
    registry_home = tmp_path / "corpus-home"
    registry_home.mkdir()
    registry_path = registry_home / "mounts.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mounts": [
                    {
                        "corpus_uri": "corpus://cmikeb/work/brief",
                        "mount_uri": "corpus://cmikeb/work/brief@bilby",
                        "owner_id": "cmikeb",
                        "realm": "work",
                        "tier": "BRIEF",
                        "node_id": "bilby",
                        "sync_transport": "git",
                        "root_path": str(root.resolve()),
                        "aliases": ["work/brief", "work/brief@bilby"],
                        "storage_role": "git-light",
                    },
                    {
                        "corpus_uri": "corpus://cmikeb/nas/brief",
                        "mount_uri": "corpus://cmikeb/nas/brief@bilby",
                        "owner_id": "cmikeb",
                        "realm": "nas",
                        "tier": "BRIEF",
                        "node_id": "bilby",
                        "sync_transport": "local",
                        "root_path": str((tmp_path / "nas").resolve()),
                        "aliases": ["nas/brief", "nas/brief@bilby"],
                        "storage_role": "bulk-media",
                        "intent": "Heavy local artifact storage.",
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CORPUS_HOME", str(registry_home))
    large_file = root / "assets.bin"
    large_file.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    config = CatalogConfig(corpus_root=root)

    report = build_health_report(config)

    issue = next(
        issue for issue in report.issues if issue.code == "health-large-local-file"
    )
    assert [mount.mount_uri for mount in issue.suggested_mounts] == [
        "corpus://cmikeb/nas/brief@bilby"
    ]


def test_mount_registration_preserves_manual_placement_metadata(
    tmp_path,
    monkeypatch,
):
    root = copy_fixture(tmp_path)
    registry_home = tmp_path / "corpus-home"
    registry_home.mkdir()
    registry_path = registry_home / "mounts.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "mounts": [
                    {
                        "corpus_uri": "corpus://cmikeb/work/brief",
                        "mount_uri": "corpus://cmikeb/work/brief@bilby",
                        "owner_id": "cmikeb",
                        "realm": "work",
                        "tier": "BRIEF",
                        "node_id": "bilby",
                        "sync_transport": "git",
                        "root_path": str(root.resolve()),
                        "aliases": ["work/brief", "work/brief@bilby"],
                        "storage_role": "git-light",
                        "intent": "Portable Markdown-first corpus.",
                        "preferred_for": ["markdown"],
                        "avoid_for": ["large-binaries"],
                        "large_file_warn_bytes": 1048576,
                        "large_file_error_bytes": 10485760,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CORPUS_HOME", str(registry_home))
    config = CatalogConfig(corpus_root=root)

    build_mount_inventory(load_corpus(config), config)

    [known] = read_known_mounts(registry_path)
    assert known.storage_role == "git-light"
    assert known.intent == "Portable Markdown-first corpus."
    assert known.preferred_for == ["markdown"]
    assert known.avoid_for == ["large-binaries"]
    assert known.large_file_warn_bytes == 1048576
    assert known.large_file_error_bytes == 10485760
