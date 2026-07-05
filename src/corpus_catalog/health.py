from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import subprocess

from corpus_catalog.config import CatalogConfig
from corpus_catalog.corpus import (
    load_corpus,
    load_corpus_ignore_patterns,
    path_is_ignored,
)
from corpus_catalog.identity import (
    CorpusIdentityError,
    extract_current_mount,
    known_mount_for_current_root,
    read_known_mounts,
    user_registry_path,
)
from corpus_catalog.models import (
    CorpusMount,
    CorpusStats,
    DirectoryStat,
    ExtensionStat,
    FileStat,
    HealthIssue,
    HealthReport,
    KnownCorpusMount,
    MountSuggestion,
    SourceCodeDirectoryStat,
)


DEFAULT_LARGE_FILE_WARN_BYTES = 1 * 1024 * 1024
DEFAULT_LARGE_FILE_ERROR_BYTES = 10 * 1024 * 1024
DEFAULT_HEAVY_DIRECTORY_BYTES = 50 * 1024 * 1024
DEFAULT_HEAVY_DIRECTORY_FILES = 500

INTERNAL_EXCLUDE_PARTS = frozenset((".git", ".catalog", ".corpus"))
PACKAGE_MARKERS = frozenset(
    (
        "Cargo.toml",
        "go.mod",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
    )
)
GENERATED_DIRECTORY_NAMES = frozenset(
    (
        ".mypy_cache",
        ".next",
        ".parcel-cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "site",
        "target",
        "vendor",
    )
)


@dataclass(frozen=True)
class CollectedInventory:
    stats: CorpusStats
    files: list[FileStat]
    directories: list[DirectoryStat]
    source_code_directories: list[SourceCodeDirectoryStat]


def build_corpus_stats(config: CatalogConfig, *, top: int = 20) -> CorpusStats:
    """Build read-only local filesystem and search-scope stats."""

    return collect_inventory(config, top=top).stats


def build_health_report(config: CatalogConfig, *, top: int = 20) -> HealthReport:
    """Build a read-only local node/tooling health report."""

    collected = collect_inventory(config, top=top)
    stats = collected.stats
    issues: list[HealthIssue] = []
    warn_bytes = large_file_warn_bytes(stats.registered_mount)
    error_bytes = large_file_error_bytes(stats.registered_mount)

    issues.extend(
        large_file_issues(
            collected.files,
            warn_bytes=warn_bytes,
            error_bytes=error_bytes,
        )
    )
    issues.extend(heavy_directory_issues(collected.directories))
    issues.extend(generated_directory_issues(collected.directories))
    issues.extend(source_code_directory_issues(collected.source_code_directories))

    suggestions = placement_suggestions(config, stats.current_mount)
    issues = [attach_suggestions(issue, suggestions) for issue in issues]
    issues.sort(key=health_issue_sort_key)

    return HealthReport(
        generated_at=utc_now(),
        corpus_root=str(config.corpus_root),
        stats=stats,
        issues=issues,
    )


def collect_inventory(config: CatalogConfig, *, top: int = 20) -> CollectedInventory:
    top = max(1, min(top, 100))
    ignore_patterns = load_corpus_ignore_patterns(config)
    catalog_items = load_corpus(config)
    catalog_visible_paths = {item.source.path for item in catalog_items}
    current_mount = safe_current_mount(catalog_items, config)
    registered_mount = (
        known_mount_for_current_root(current_mount) if current_mount else None
    )
    tracked_paths = git_tracked_paths(config)

    files: list[FileStat] = []
    directories: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "size_bytes": 0,
            "file_count": 0,
            "markdown_file_count": 0,
            "catalog_visible_file_count": 0,
            "ignored_file_count": 0,
            "ignored_bytes": 0,
        }
    )
    extensions: dict[str, dict[str, int]] = defaultdict(
        lambda: {"size_bytes": 0, "file_count": 0}
    )
    source_dirs: dict[str, dict[str, object]] = {}

    for path in iter_scanned_files(config):
        rel_path = relative_path(config, path)
        if rel_path is None:
            continue
        try:
            size_bytes = path.stat().st_size
        except OSError:
            continue

        extension = path.suffix.casefold() or "[none]"
        ignored = path_is_ignored(rel_path, ignore_patterns)
        catalog_visible = rel_path in catalog_visible_paths
        is_markdown = path.suffix.casefold() == ".md"
        tracked_by_git = (
            None if tracked_paths is None else rel_path in tracked_paths
        )
        file_stat = FileStat(
            path=rel_path,
            size_bytes=size_bytes,
            extension=extension,
            is_markdown=is_markdown,
            tracked_by_git=tracked_by_git,
            ignored_by_corpusignore=ignored,
            catalog_visible=catalog_visible,
        )
        files.append(file_stat)

        extensions[extension]["size_bytes"] += size_bytes
        extensions[extension]["file_count"] += 1
        update_directory_stats(directories, file_stat)
        update_source_code_directory(source_dirs, file_stat)

    directory_stats = [
        DirectoryStat(
            path=path,
            size_bytes=values["size_bytes"],
            file_count=values["file_count"],
            markdown_file_count=values["markdown_file_count"],
            catalog_visible_file_count=values["catalog_visible_file_count"],
            ignored_file_count=values["ignored_file_count"],
            ignored_bytes=values["ignored_bytes"],
            ignored_by_corpusignore=directory_is_ignored(path, ignore_patterns),
        )
        for path, values in directories.items()
    ]
    source_code_directories = source_code_stats(source_dirs, ignore_patterns)

    total_file_count = len(files)
    total_bytes = sum(file.size_bytes for file in files)
    markdown_file_count = sum(1 for file in files if file.is_markdown)
    markdown_bytes = sum(file.size_bytes for file in files if file.is_markdown)
    ignored_files = [file for file in files if file.ignored_by_corpusignore]
    tracked_files = [
        file for file in files if file.tracked_by_git is True
    ] if tracked_paths is not None else []

    stats = CorpusStats(
        generated_at=utc_now(),
        corpus_root=str(config.corpus_root),
        current_mount=current_mount,
        registered_mount=registered_mount,
        git_available=tracked_paths is not None,
        corpusignore_patterns=list(ignore_patterns),
        total_file_count=total_file_count,
        total_bytes=total_bytes,
        markdown_file_count=markdown_file_count,
        markdown_bytes=markdown_bytes,
        non_markdown_file_count=total_file_count - markdown_file_count,
        non_markdown_bytes=total_bytes - markdown_bytes,
        catalog_visible_source_count=len(catalog_visible_paths),
        corpusignored_file_count=len(ignored_files),
        corpusignored_bytes=sum(file.size_bytes for file in ignored_files),
        git_tracked_file_count=(
            len(tracked_files) if tracked_paths is not None else None
        ),
        git_tracked_bytes=(
            sum(file.size_bytes for file in tracked_files)
            if tracked_paths is not None
            else None
        ),
        largest_files=sorted(
            files, key=lambda file: (-file.size_bytes, file.path)
        )[:top],
        largest_directories=sorted(
            directory_stats,
            key=lambda directory: (-directory.size_bytes, directory.path),
        )[:top],
        extensions=sorted(
            (
                ExtensionStat(
                    extension=extension,
                    file_count=values["file_count"],
                    size_bytes=values["size_bytes"],
                )
                for extension, values in extensions.items()
            ),
            key=lambda extension: (-extension.size_bytes, extension.extension),
        )[:top],
        source_code_directories=sorted(
            source_code_directories,
            key=lambda directory: (-directory.size_bytes, directory.path),
        )[:top],
    )

    return CollectedInventory(
        stats=stats,
        files=files,
        directories=directory_stats,
        source_code_directories=source_code_directories,
    )


def iter_scanned_files(config: CatalogConfig):
    root = config.corpus_root
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            dirname for dirname in dirnames if dirname not in INTERNAL_EXCLUDE_PARTS
        ]
        current_path = Path(current)
        if has_internal_part(config, current_path):
            dirnames[:] = []
            continue
        for filename in filenames:
            if filename in INTERNAL_EXCLUDE_PARTS:
                continue
            path = current_path / filename
            if has_internal_part(config, path):
                continue
            if path.is_file():
                yield path


def has_internal_part(config: CatalogConfig, path: Path) -> bool:
    try:
        rel_parts = path.relative_to(config.corpus_root).parts
    except ValueError:
        return True
    return any(part in INTERNAL_EXCLUDE_PARTS for part in rel_parts)


def relative_path(config: CatalogConfig, path: Path) -> str | None:
    try:
        return path.relative_to(config.corpus_root).as_posix()
    except ValueError:
        return None


def git_tracked_paths(config: CatalogConfig) -> set[str] | None:
    for args in (
        ("ls-files", "-z", "--recurse-submodules"),
        ("ls-files", "-z"),
    ):
        try:
            result = subprocess.run(
                ("git", "-C", str(config.corpus_root), *args),
                check=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError):
            continue
        return {
            path.decode("utf-8")
            for path in result.stdout.split(b"\0")
            if path
        }
    return None


def update_directory_stats(
    directories: dict[str, dict[str, int]], file_stat: FileStat
) -> None:
    parent = PurePosixPath(file_stat.path).parent
    if str(parent) == ".":
        return
    parts = parent.parts
    for index in range(1, len(parts) + 1):
        directory = "/".join(parts[:index])
        values = directories[directory]
        values["size_bytes"] += file_stat.size_bytes
        values["file_count"] += 1
        if file_stat.is_markdown:
            values["markdown_file_count"] += 1
        if file_stat.catalog_visible:
            values["catalog_visible_file_count"] += 1
        if file_stat.ignored_by_corpusignore:
            values["ignored_file_count"] += 1
            values["ignored_bytes"] += file_stat.size_bytes


def update_source_code_directory(
    source_dirs: dict[str, dict[str, object]], file_stat: FileStat
) -> None:
    root = source_code_root(file_stat.path)
    if root is None or root == "projects/spec/code/corpus-spec":
        return
    values = source_dirs.setdefault(
        root,
        {
            "size_bytes": 0,
            "file_count": 0,
            "markdown_file_count": 0,
            "catalog_visible_file_count": 0,
            "markers": set(),
            "readme_path": None,
        },
    )
    values["size_bytes"] = int(values["size_bytes"]) + file_stat.size_bytes
    values["file_count"] = int(values["file_count"]) + 1
    if file_stat.is_markdown:
        values["markdown_file_count"] = int(values["markdown_file_count"]) + 1
    if file_stat.catalog_visible:
        values["catalog_visible_file_count"] = (
            int(values["catalog_visible_file_count"]) + 1
        )

    name = PurePosixPath(file_stat.path).name
    if name in PACKAGE_MARKERS:
        markers = values["markers"]
        if isinstance(markers, set):
            markers.add(name)
    if name.casefold() == "readme.md" and values["readme_path"] is None:
        values["readme_path"] = file_stat.path


def source_code_root(rel_path: str) -> str | None:
    parts = PurePosixPath(rel_path).parts
    if len(parts) < 4:
        return None
    if parts[0] != "projects" or parts[2] != "code":
        return None
    return "/".join(parts[:4])


def source_code_stats(
    source_dirs: dict[str, dict[str, object]],
    ignore_patterns: tuple[str, ...],
) -> list[SourceCodeDirectoryStat]:
    stats: list[SourceCodeDirectoryStat] = []
    for path, values in source_dirs.items():
        markers = values["markers"]
        stats.append(
            SourceCodeDirectoryStat(
                path=path,
                size_bytes=int(values["size_bytes"]),
                file_count=int(values["file_count"]),
                markdown_file_count=int(values["markdown_file_count"]),
                catalog_visible_file_count=int(values["catalog_visible_file_count"]),
                ignored_by_corpusignore=directory_is_ignored(path, ignore_patterns),
                markers=sorted(markers) if isinstance(markers, set) else [],
                readme_path=(
                    str(values["readme_path"]) if values["readme_path"] else None
                ),
            )
        )
    return stats


def directory_is_ignored(path: str, ignore_patterns: tuple[str, ...]) -> bool:
    return path_is_ignored(path, ignore_patterns) or path_is_ignored(
        f"{path}/README.md", ignore_patterns
    )


def large_file_warn_bytes(mount: KnownCorpusMount | None) -> int:
    if mount and mount.large_file_warn_bytes is not None:
        return mount.large_file_warn_bytes
    return DEFAULT_LARGE_FILE_WARN_BYTES


def large_file_error_bytes(mount: KnownCorpusMount | None) -> int:
    if mount and mount.large_file_error_bytes is not None:
        return mount.large_file_error_bytes
    return DEFAULT_LARGE_FILE_ERROR_BYTES


def large_file_issues(
    files: list[FileStat],
    *,
    warn_bytes: int,
    error_bytes: int,
) -> list[HealthIssue]:
    issues: list[HealthIssue] = []
    for file in files:
        if file.size_bytes < warn_bytes:
            continue
        if file.tracked_by_git is True:
            severity = "error" if file.size_bytes >= error_bytes else "warning"
            issues.append(
                HealthIssue(
                    code="health-large-tracked-file",
                    severity=severity,
                    path=file.path,
                    size_bytes=file.size_bytes,
                    tracked_by_git=True,
                    message="Git-tracked file exceeds the lightweight mount policy.",
                    recommendation=(
                        "Move durable heavyweight content to a heavier registered "
                        "mount, then remove the file from Git in a reviewed change."
                    ),
                )
            )
        elif file.size_bytes >= error_bytes:
            issues.append(
                HealthIssue(
                    code="health-large-local-file",
                    severity="warning",
                    path=file.path,
                    size_bytes=file.size_bytes,
                    tracked_by_git=file.tracked_by_git,
                    message=(
                        "Local file exceeds the large-file threshold; confirm it "
                        "belongs on this node."
                    ),
                    recommendation=(
                        "Keep local-only artifacts out of Git-backed corpus history, "
                        "or migrate durable artifacts to a heavier mount."
                    ),
                )
            )
        else:
            issues.append(
                HealthIssue(
                    code="health-large-local-file",
                    severity="info",
                    path=file.path,
                    size_bytes=file.size_bytes,
                    tracked_by_git=file.tracked_by_git,
                    message=(
                        "Local file is larger than the Git-light warning threshold."
                    ),
                    recommendation=(
                        "Review whether this is expected local tooling output, "
                        "source content, or a migration candidate."
                    ),
                )
            )
    return issues


def heavy_directory_issues(directories: list[DirectoryStat]) -> list[HealthIssue]:
    issues: list[HealthIssue] = []
    for directory in directories:
        effective_bytes = directory.size_bytes - directory.ignored_bytes
        effective_files = directory.file_count - directory.ignored_file_count
        if (
            effective_bytes < DEFAULT_HEAVY_DIRECTORY_BYTES
            and effective_files < DEFAULT_HEAVY_DIRECTORY_FILES
        ):
            continue
        issues.append(
            HealthIssue(
                code="health-heavy-directory",
                severity="warning",
                path=directory.path,
                size_bytes=effective_bytes,
                file_count=effective_files,
                message="Directory is large enough to affect sync or search ergonomics.",
                recommendation=(
                    "Review whether this directory is source corpus material, "
                    "derived output, or a candidate for a heavier mount."
                ),
            )
        )
    return issues


def generated_directory_issues(
    directories: list[DirectoryStat],
) -> list[HealthIssue]:
    issues: list[HealthIssue] = []
    for directory in directories:
        if directory.ignored_by_corpusignore:
            continue
        name = PurePosixPath(directory.path).name
        if name not in GENERATED_DIRECTORY_NAMES:
            continue
        if (
            directory.markdown_file_count == 0
            and directory.size_bytes < DEFAULT_LARGE_FILE_WARN_BYTES
            and directory.file_count < 50
        ):
            continue
        issues.append(
            HealthIssue(
                code="health-corpusignore-generated-dir",
                severity="warning",
                path=directory.path,
                size_bytes=directory.size_bytes,
                file_count=directory.file_count,
                confidence="strong",
                message=(
                    "Generated, dependency, cache, or virtual-environment "
                    "directory is visible to local corpus health scanning."
                ),
                recommendation=(
                    f"Add `{directory.path}/` to .corpusignore if this directory "
                    "should stay local to tooling/build output."
                ),
            )
        )
    return issues


def source_code_directory_issues(
    directories: list[SourceCodeDirectoryStat],
) -> list[HealthIssue]:
    issues: list[HealthIssue] = []
    for directory in directories:
        if directory.ignored_by_corpusignore:
            continue
        if (
            directory.catalog_visible_file_count == 0
            and directory.markdown_file_count == 0
            and not directory.markers
        ):
            continue
        evidence = []
        if directory.markers:
            evidence.append("markers: " + ", ".join(directory.markers))
        if directory.readme_path:
            evidence.append(f"readme: {directory.readme_path}")
        evidence_text = f" ({'; '.join(evidence)})" if evidence else ""
        severity = "warning" if directory.catalog_visible_file_count else "info"
        issues.append(
            HealthIssue(
                code="health-corpusignore-source-code-dir",
                severity=severity,
                path=directory.path,
                size_bytes=directory.size_bytes,
                file_count=directory.file_count,
                confidence="review",
                message=(
                    "Package-like source directory may pollute corpus search"
                    f"{evidence_text}."
                ),
                recommendation=(
                    f"Add `{directory.path}/` to .corpusignore for now, or "
                    "promote a deliberate README/summary interface for corpus use."
                ),
            )
        )
    return issues


def placement_suggestions(
    config: CatalogConfig,
    current_mount: CorpusMount | None,
) -> list[MountSuggestion]:
    current_uri = current_mount.mount_uri if current_mount else None
    suggestions: list[MountSuggestion] = []
    for mount in read_known_mounts(user_registry_path()):
        if mount.mount_uri == current_uri:
            continue
        if mount.storage_role not in {"bulk-media", "cloud-docs"}:
            continue
        suggestions.append(
            MountSuggestion(
                mount_uri=mount.mount_uri,
                root_path=mount.root_path,
                storage_role=mount.storage_role,
                intent=mount.intent,
            )
        )
    suggestions.sort(
        key=lambda mount: (
            0 if mount.storage_role == "bulk-media" else 1,
            mount.mount_uri,
        )
    )
    return suggestions


def attach_suggestions(
    issue: HealthIssue,
    suggestions: list[MountSuggestion],
) -> HealthIssue:
    if issue.code not in {
        "health-large-tracked-file",
        "health-large-local-file",
        "health-heavy-directory",
    }:
        return issue
    return issue.model_copy(update={"suggested_mounts": suggestions[:3]})


def health_issue_sort_key(issue: HealthIssue) -> tuple[int, str, str]:
    severity_rank = {"error": 0, "warning": 1, "info": 2}
    return (
        severity_rank.get(issue.severity, 9),
        issue.code,
        issue.path or "",
    )


def write_health_artifacts(config: CatalogConfig, report: HealthReport) -> None:
    reports_dir = config.catalog_dir / "reports"
    jobs_dir = config.catalog_dir / "jobs"
    reports_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "health.md").write_text(format_health_markdown(report), encoding="utf-8")
    (jobs_dir / "last-health.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def format_health_markdown(report: HealthReport) -> str:
    lines = [
        "# Catalog Health Report",
        "",
        f"Generated: {report.generated_at}",
        f"Corpus root: `{report.corpus_root}`",
        f"Issue count: {len(report.issues)}",
        "",
        "## Stats",
        "",
        f"- Files: `{report.stats.total_file_count}`",
        f"- Bytes: `{report.stats.total_bytes}`",
        f"- Markdown files: `{report.stats.markdown_file_count}`",
        f"- Catalog-visible sources: `{report.stats.catalog_visible_source_count}`",
        "",
    ]
    if not report.issues:
        lines.extend(["No health issues found.", ""])
        return "\n".join(lines)

    lines.extend(["## Issues", ""])
    for issue in report.issues:
        path = f" `{issue.path}`" if issue.path else ""
        lines.append(f"- **{issue.severity}** `{issue.code}`{path}: {issue.message}")
        if issue.recommendation:
            lines.append(f"  Recommendation: {issue.recommendation}")
        if issue.suggested_mounts:
            targets = ", ".join(mount.mount_uri for mount in issue.suggested_mounts)
            lines.append(f"  Suggested mounts: {targets}")
    lines.append("")
    return "\n".join(lines)


def safe_current_mount(
    items,
    config: CatalogConfig,
) -> CorpusMount | None:
    try:
        return extract_current_mount(items, config)
    except CorpusIdentityError:
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
