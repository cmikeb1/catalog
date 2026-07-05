from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from corpus_catalog.config import CatalogConfig
from corpus_catalog.context import build_context_packet
from corpus_catalog.corpus import load_corpus, search_corpus
from corpus_catalog.health import (
    build_corpus_stats,
    build_health_report,
    write_health_artifacts,
)
from corpus_catalog.identity import (
    CorpusIdentityError,
    build_mount_inventory,
    extract_current_mount,
    mount_registration_warning,
    resolve_current_mount_selector,
)
from corpus_catalog.models import CatalogStatus, MountInventory
from corpus_catalog.naming import entry_paths, field_value
from corpus_catalog.projects import build_project_creation_plan
from corpus_catalog.release import release_metadata
from corpus_catalog.storage import (
    catalog_status,
    gitignore_warning,
    index_catalog,
    init_catalog,
    load_index_or_corpus,
)
from corpus_catalog.validators import validate_corpus


def main() -> None:
    parser = argparse.ArgumentParser(prog="catalog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    add_root_argument(init_parser)

    index_parser = subparsers.add_parser("index")
    add_root_argument(index_parser)

    status_parser = subparsers.add_parser("status")
    add_root_argument(status_parser)
    status_parser.add_argument("--format", choices=("text", "json"), default="text")

    stats_parser = subparsers.add_parser("stats")
    add_root_argument(stats_parser)
    stats_parser.add_argument("--format", choices=("text", "json"), default="text")
    stats_parser.add_argument("--top", type=int, default=20)

    health_parser = subparsers.add_parser("health")
    add_root_argument(health_parser)
    health_parser.add_argument("--format", choices=("text", "json"), default="text")
    health_parser.add_argument("--top", type=int, default=20)
    health_parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write .corpus/reports/health.md and .corpus/jobs/last-health.json.",
    )
    health_parser.add_argument(
        "--fail-on",
        choices=("error", "warning", "never"),
        default="never",
        help="Exit nonzero when health findings meet this severity.",
    )

    context_parser = subparsers.add_parser("context")
    add_root_argument(context_parser)
    add_identity_selector_arguments(context_parser)
    context_parser.add_argument("--cwd")
    context_parser.add_argument("--goal", required=True)

    search_parser = subparsers.add_parser("search")
    add_root_argument(search_parser)
    add_identity_selector_arguments(search_parser)
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--limit", type=int, default=10)

    validate_parser = subparsers.add_parser("validate")
    add_root_argument(validate_parser)
    add_identity_selector_arguments(validate_parser)
    validate_parser.add_argument("--format", choices=("json", "markdown"), default="json")

    mounts_parser = subparsers.add_parser("mounts")
    add_root_argument(mounts_parser)
    mounts_parser.add_argument("--format", choices=("text", "json"), default="text")
    mounts_parser.add_argument(
        "--no-register",
        action="store_true",
        help="Report mounts without updating the per-user registry.",
    )

    project_parser = subparsers.add_parser("project")
    project_subparsers = project_parser.add_subparsers(
        dest="project_command", required=True
    )
    project_new_parser = project_subparsers.add_parser("new")
    add_root_argument(project_new_parser)
    project_new_parser.add_argument("--name", required=True)
    project_new_parser.add_argument("--slug")
    project_new_parser.add_argument("--tag")
    project_new_parser.add_argument("--tier")
    project_new_parser.add_argument("--lifecycle", default="DRAFT")

    version_parser = subparsers.add_parser("version")
    version_parser.add_argument("--format", choices=("text", "json"), default="text")

    argv = sys.argv[1:]
    if not argv:
        if looks_like_corpus_root(Path.cwd()):
            argv = ["status"]
        else:
            parser.print_help()
            return

    args = parser.parse_args(argv)
    if args.command == "version":
        metadata = release_metadata()
        if args.format == "json":
            print(json.dumps(metadata, indent=2))
        else:
            print(f"Catalog version: {metadata['catalog_version']}")
            print(
                "Validated corpus-spec: "
                f"{metadata['validated_corpus_spec_version']}"
            )
        return

    config = CatalogConfig(corpus_root=Path(args.root))

    if args.command == "init":
        manifest = init_catalog(config)
        warning = gitignore_warning(config)
        if warning:
            print(f"warning: {warning}", file=sys.stderr)
        print(manifest.model_dump_json(indent=2))
    elif args.command == "index":
        manifest = index_catalog(config)
        print(manifest.model_dump_json(indent=2))
    elif args.command == "status":
        status = catalog_status(config)
        if args.format == "json":
            print(status.model_dump_json(indent=2))
        else:
            print(format_status(status))
    elif args.command == "stats":
        stats = build_corpus_stats(config, top=args.top)
        if args.format == "json":
            print(stats.model_dump_json(indent=2))
        else:
            print(format_stats(stats))
    elif args.command == "health":
        report = build_health_report(config, top=args.top)
        if args.write_report:
            write_health_artifacts(config, report)
        if args.format == "json":
            print(report.model_dump_json(indent=2))
        else:
            print(format_health(report))
        if health_should_fail(report, args.fail_on):
            raise SystemExit(1)
    elif args.command == "context":
        ensure_identity_selection(config, args.corpus, args.mount, parser)
        packet = build_context_packet(goal=args.goal, cwd=args.cwd, config=config)
        print(packet.model_dump_json(indent=2))
    elif args.command == "search":
        ensure_identity_selection(config, args.corpus, args.mount, parser)
        items = search_corpus(args.query, load_index_or_corpus(config), limit=args.limit)
        print(json.dumps(format_search_results(args.query, items), indent=2))
    elif args.command == "validate":
        ensure_identity_selection(config, args.corpus, args.mount, parser)
        manifest = index_catalog(config)
        issues = validate_corpus(load_index_or_corpus(config), config)
        warning = mount_registration_warning(config, manifest.current_mount)
        if warning:
            print(f"warning: {warning}", file=sys.stderr)
        if args.format == "markdown":
            report_path = config.catalog_dir / "reports" / "validation.md"
            print(report_path.read_text(encoding="utf-8"))
        else:
            print(json.dumps([issue.model_dump(mode="json") for issue in issues], indent=2))
    elif args.command == "mounts":
        try:
            inventory = build_mount_inventory(
                load_corpus(config),
                config,
                register=not args.no_register,
            )
        except CorpusIdentityError as error:
            parser.error(str(error))
        if args.format == "json":
            print(inventory.model_dump_json(indent=2))
        else:
            print(format_mount_inventory(inventory))
    elif args.command == "project" and args.project_command == "new":
        plan = build_project_creation_plan(
            name=args.name,
            config=config,
            slug=args.slug,
            tag=args.tag,
            tier=args.tier,
            lifecycle=args.lifecycle,
        )
        print(plan.model_dump_json(indent=2))


def add_root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        default=".",
        help="Corpus root directory. Defaults to the current working directory.",
    )


def add_identity_selector_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--corpus",
        help="Declared corpus URI or short alias such as work/brief.",
    )
    parser.add_argument(
        "--mount",
        help="Declared mount URI or short alias such as work/brief@bilby.",
    )


def ensure_identity_selection(
    config: CatalogConfig,
    corpus_selector: str | None,
    mount_selector: str | None,
    parser: argparse.ArgumentParser,
) -> None:
    try:
        mount = extract_current_mount(load_corpus(config), config)
        resolve_current_mount_selector(
            mount,
            corpus_selector=corpus_selector,
            mount_selector=mount_selector,
        )
    except CorpusIdentityError as error:
        parser.error(str(error))


def looks_like_corpus_root(path: Path) -> bool:
    if (path / ".corpus").is_dir():
        return True
    if not any((path / entry).is_file() for entry in entry_paths()):
        return False
    return any(
        (path / name).exists()
        for name in ("projects", "reference", "corpus-spec", "corpus-spec")
    )


def format_search_results(query: str, items) -> list[dict[str, object]]:
    return [
        {
            "source": item.source.model_dump(mode="json"),
            "title": item.title,
            "snippet": search_snippet(query, item.text) or item.source.excerpt,
            "metadata": search_metadata(item.front_matter),
            "content_hash": item.content_hash,
        }
        for item in items
    ]


def search_metadata(front_matter: dict[str, object]) -> dict[str, object]:
    keys = (
        "doc_type",
        "corpus_spec_version",
        "corpus_spec_profile",
        "corpus_spec_adoption",
        "corpus_spec_reviewed",
        "corpus_spec_betas",
    )
    metadata = {}
    for key in keys:
        if key == "doc_type" and key in front_matter:
            metadata[key] = front_matter[key]
        elif key != "doc_type" and (value := field_value(front_matter, key)) is not None:
            metadata[key] = value
    return metadata


def search_snippet(query: str, text: str, context_chars: int = 140) -> str | None:
    terms = [term.casefold() for term in query.split() if term.strip()]
    if not terms:
        return None

    folded = text.casefold()
    matches = [
        (index, term)
        for term in terms
        if (index := folded.find(term)) >= 0
    ]
    if not matches:
        return None

    index, term = min(matches, key=lambda match: match[0])
    start = max(0, index - context_chars)
    end = min(len(text), index + len(term) + context_chars)
    snippet = " ".join(text[start:end].split())
    if start > 0:
        snippet = f"...{snippet}"
    if end < len(text):
        snippet = f"{snippet}..."
    return snippet


def format_status(status: CatalogStatus) -> str:
    lines = [
        f"Catalog state: {status.state}",
        f"Corpus root: {status.corpus_root}",
        f"Generated state dir: {status.catalog_dir}",
    ]
    if status.manifest and status.manifest.generated_at:
        lines.append(f"Generated: {status.manifest.generated_at}")
    if status.manifest:
        lines.append(f"Catalog version: {status.manifest.catalog_version}")
        lines.append(
            "Validated corpus-spec: "
            f"{status.manifest.validated_corpus_spec_version or 'unknown'}"
        )
    if status.manifest and status.manifest.corpus_spec_baseline:
        lines.append(f"CORPUS-SPEC baseline: {status.manifest.corpus_spec_baseline}")
    if status.current_mount:
        lines.extend(
            [
                f"Corpus URI: {status.current_mount.corpus_uri}",
                f"Mount URI: {status.current_mount.mount_uri}",
                f"Realm: {status.current_mount.realm}",
                f"Node: {status.current_mount.node_id}",
                f"Sync transport: {status.current_mount.sync_transport or 'unknown'}",
            ]
        )
        if status.mount_registry_path:
            lines.append(f"Mount registry: {status.mount_registry_path}")
            registered = "yes" if status.mount_registered else "no"
            lines.append(f"Mount registered: {registered}")
    if status.mount_sync_status:
        lines.append(
            "Mount sync: "
            f"{status.mount_sync_status.state} "
            f"({status.mount_sync_status.confidence}) - "
            f"{status.mount_sync_status.detail}"
        )
    if status.missing_artifacts:
        lines.append("Missing artifacts:")
        lines.extend(f"- {artifact}" for artifact in status.missing_artifacts)
    if status.stale_reasons:
        lines.append("Reasons:")
        lines.extend(f"- {reason}" for reason in status.stale_reasons)
    if status.next_commands:
        lines.append("Next commands:")
        lines.extend(f"- {command}" for command in status.next_commands)
    return "\n".join(lines)


def format_stats(stats) -> str:
    lines = [
        "Catalog stats",
        f"Generated: {stats.generated_at}",
        f"Corpus root: {stats.corpus_root}",
    ]
    if stats.current_mount:
        lines.extend(
            [
                f"Corpus URI: {stats.current_mount.corpus_uri}",
                f"Mount URI: {stats.current_mount.mount_uri}",
                f"Sync transport: {stats.current_mount.sync_transport or 'unknown'}",
            ]
        )
    if stats.registered_mount:
        role = stats.registered_mount.storage_role or "unspecified"
        lines.append(f"Mount storage role: {role}")
        if stats.registered_mount.intent:
            lines.append(f"Mount intent: {stats.registered_mount.intent}")
    lines.extend(
        [
            f"Files: {stats.total_file_count} ({format_bytes(stats.total_bytes)})",
            (
                "Markdown: "
                f"{stats.markdown_file_count} ({format_bytes(stats.markdown_bytes)})"
            ),
            (
                "Non-Markdown: "
                f"{stats.non_markdown_file_count} "
                f"({format_bytes(stats.non_markdown_bytes)})"
            ),
            f"Catalog-visible sources: {stats.catalog_visible_source_count}",
            (
                ".corpusignore-covered files: "
                f"{stats.corpusignored_file_count} "
                f"({format_bytes(stats.corpusignored_bytes)})"
            ),
            f"Git available: {'yes' if stats.git_available else 'no'}",
        ]
    )
    if stats.git_tracked_file_count is not None:
        lines.append(
            "Git-tracked files: "
            f"{stats.git_tracked_file_count} "
            f"({format_bytes(stats.git_tracked_bytes or 0)})"
        )
    if stats.corpusignore_patterns:
        lines.append(".corpusignore patterns:")
        lines.extend(f"- {pattern}" for pattern in stats.corpusignore_patterns)
    if stats.largest_files:
        lines.append("Largest files:")
        lines.extend(
            f"- {format_bytes(file.size_bytes)} {file.path}"
            f"{tracked_suffix(file.tracked_by_git)}"
            for file in stats.largest_files
        )
    if stats.largest_directories:
        lines.append("Largest directories:")
        lines.extend(
            f"- {format_bytes(directory.size_bytes)} "
            f"{directory.path} ({directory.file_count} files)"
            for directory in stats.largest_directories
        )
    if stats.extensions:
        lines.append("Top extensions:")
        lines.extend(
            f"- {extension.extension}: {extension.file_count} files, "
            f"{format_bytes(extension.size_bytes)}"
            for extension in stats.extensions
        )
    if stats.source_code_directories:
        lines.append("Source code directories:")
        for directory in stats.source_code_directories:
            details = []
            if directory.markers:
                details.append("markers: " + ", ".join(directory.markers))
            if directory.readme_path:
                details.append(f"readme: {directory.readme_path}")
            ignored = "ignored" if directory.ignored_by_corpusignore else "visible"
            suffix = f" ({'; '.join(details)})" if details else ""
            lines.append(
                f"- {directory.path}: {format_bytes(directory.size_bytes)}, "
                f"{directory.file_count} files, {ignored}{suffix}"
            )
    return "\n".join(lines)


def format_health(report) -> str:
    lines = [
        "Catalog health",
        f"Generated: {report.generated_at}",
        f"Corpus root: {report.corpus_root}",
        f"Issue count: {len(report.issues)}",
    ]
    if not report.issues:
        lines.append("No health issues found.")
        return "\n".join(lines)

    lines.append("Issues:")
    for issue in report.issues:
        path = f" {issue.path}" if issue.path else ""
        size = f" [{format_bytes(issue.size_bytes)}]" if issue.size_bytes else ""
        lines.append(
            f"- {issue.severity.upper()} {issue.code}{path}{size}: "
            f"{issue.message}"
        )
        if issue.recommendation:
            lines.append(f"  Recommendation: {issue.recommendation}")
        if issue.suggested_mounts:
            targets = ", ".join(mount.mount_uri for mount in issue.suggested_mounts)
            lines.append(f"  Suggested mounts: {targets}")
    return "\n".join(lines)


def format_bytes(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown"
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def tracked_suffix(tracked_by_git: bool | None) -> str:
    if tracked_by_git is True:
        return " [tracked]"
    if tracked_by_git is False:
        return " [local]"
    return " [git unknown]"


def health_should_fail(report, fail_on: str) -> bool:
    if fail_on == "never":
        return False
    if fail_on == "error":
        return any(issue.severity == "error" for issue in report.issues)
    if fail_on == "warning":
        return any(issue.severity in {"error", "warning"} for issue in report.issues)
    return False


def format_mount_inventory(inventory: MountInventory) -> str:
    lines = [
        f"Registry: {inventory.registry_path}",
        f"Registry updated: {'yes' if inventory.registry_updated else 'no'}",
    ]
    if inventory.current_mount is None:
        lines.append("Current mount: unknown")
    else:
        mount = inventory.current_mount
        lines.extend(
            [
                f"Current mount: {mount.mount_uri}",
                f"Logical corpus: {mount.corpus_uri}",
                f"Aliases: {', '.join(mount.aliases)}",
                f"Owner: {mount.owner_id}",
                f"Realm: {mount.realm}",
                f"Tier: {mount.tier}",
                f"Node: {mount.node_id}",
                f"Sync transport: {mount.sync_transport or 'unknown'}",
            ]
        )
    if inventory.sync_status:
        lines.append(
            "Sync status: "
            f"{inventory.sync_status.state} "
            f"({inventory.sync_status.confidence}) - "
            f"{inventory.sync_status.detail}"
        )
    if inventory.known_mounts:
        lines.append("Known mounts:")
        lines.extend(f"- {mount.mount_uri} -> {mount.root_path}" for mount in inventory.known_mounts)
    else:
        lines.append("Known mounts: none")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
