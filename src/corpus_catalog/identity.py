from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_catalog.config import CatalogConfig
from corpus_catalog.models import (
    CorpusIdentity,
    CorpusItem,
    CorpusMount,
    KnownCorpusMount,
    MountInventory,
    MountSyncStatus,
)
from corpus_catalog.naming import entry_paths, field_value


CORPUS_URI_RE = re.compile(
    r"^corpus://(?P<owner>[^/]+)/(?P<realm>[^/]+)/(?P<tier>[^/@]+)"
    r"(?:@(?P<node>[^/]+))?$"
)
CORPUS_HOME_ENV = "CORPUS_HOME"
REGISTRY_FILENAME = "mounts.json"
PLACEMENT_FIELDS = (
    "storage_role",
    "intent",
    "preferred_for",
    "avoid_for",
    "large_file_warn_bytes",
    "large_file_error_bytes",
)


class CorpusIdentityError(ValueError):
    """Raised when a declared corpus identity is malformed or mismatched."""


def extract_current_mount(
    items: list[CorpusItem], config: CatalogConfig
) -> CorpusMount | None:
    root_item = root_entry_item(items)
    if root_item is None:
        return None
    return mount_from_front_matter(root_item.front_matter, config)


def mount_from_front_matter(
    front_matter: dict[str, Any], config: CatalogConfig
) -> CorpusMount | None:
    corpus_uri = string_field(front_matter, "corpus_spec_corpus_uri")
    mount_uri = string_field(front_matter, "corpus_spec_mount_uri")
    owner_id = string_field(front_matter, "corpus_spec_owner_id")
    realm = string_field(front_matter, "corpus_spec_realm")
    tier = string_field(front_matter, "corpus_spec_tier")
    node_id = string_field(front_matter, "corpus_spec_node_id")
    sync_transport = string_field(front_matter, "corpus_spec_sync_transport")

    if not any((corpus_uri, mount_uri, owner_id, realm, tier, node_id)):
        return None

    if not all(
        (corpus_uri, mount_uri, owner_id, realm, tier, node_id, sync_transport)
    ):
        raise CorpusIdentityError(
            "Corpus identity is incomplete; corpus URI, mount URI, owner, "
            "realm, tier, node, and sync transport are required."
        )

    corpus_parts = parse_corpus_uri(corpus_uri)
    mount_parts = parse_corpus_uri(mount_uri)

    owner_id = select_declared_value(owner_id, corpus_parts, mount_parts, "owner")
    realm = select_declared_value(realm, corpus_parts, mount_parts, "realm")
    uri_tier = select_declared_value(None, corpus_parts, mount_parts, "tier")
    tier = tier or (uri_tier.upper() if uri_tier else None)
    node_id = select_declared_value(node_id, None, mount_parts, "node")

    validate_consistent_identity(
        corpus_uri,
        mount_uri,
        owner_id,
        realm,
        tier,
        node_id,
    )

    identity = CorpusIdentity(
        corpus_uri=corpus_uri,
        owner_id=owner_id,
        realm=realm,
        tier=tier,
        aliases=identity_aliases(owner_id, realm, tier),
    )
    return CorpusMount(
        corpus_uri=identity.corpus_uri,
        mount_uri=mount_uri,
        owner_id=owner_id,
        realm=realm,
        tier=tier,
        node_id=node_id,
        sync_transport=sync_transport,
        root_path=str(config.corpus_root),
        aliases=mount_aliases(owner_id, realm, tier, node_id),
    )


def current_identity(mount: CorpusMount | None) -> CorpusIdentity | None:
    if mount is None:
        return None
    return CorpusIdentity(
        corpus_uri=mount.corpus_uri,
        owner_id=mount.owner_id,
        realm=mount.realm,
        tier=mount.tier,
        aliases=identity_aliases(mount.owner_id, mount.realm, mount.tier),
    )


def resolve_current_mount_selector(
    mount: CorpusMount | None,
    *,
    corpus_selector: str | None = None,
    mount_selector: str | None = None,
) -> CorpusMount | None:
    if corpus_selector is None and mount_selector is None:
        return mount
    if mount is None:
        raise CorpusIdentityError(
            "This corpus root does not declare corpus identity frontmatter."
        )

    if corpus_selector and corpus_selector not in corpus_selector_values(mount):
        raise CorpusIdentityError(
            f"Requested corpus {corpus_selector!r} does not match "
            f"current corpus {mount.corpus_uri!r}."
        )
    if mount_selector and mount_selector not in mount_selector_values(mount):
        raise CorpusIdentityError(
            f"Requested mount {mount_selector!r} does not match "
            f"current mount {mount.mount_uri!r}."
        )
    return mount


def build_mount_inventory(
    items: list[CorpusItem],
    config: CatalogConfig,
    *,
    register: bool = True,
) -> MountInventory:
    mount = extract_current_mount(items, config)
    registry_path = user_registry_path()
    known_mounts = read_known_mounts(registry_path)
    registry_updated = False
    if register and mount is not None:
        known_mounts, registry_updated = register_mount(registry_path, known_mounts, mount)

    return MountInventory(
        registry_path=str(registry_path),
        current_mount=mount,
        known_mounts=known_mounts,
        registry_updated=registry_updated,
        sync_status=mount_sync_status(config, mount),
    )


def read_known_mounts(registry_path: Path) -> list[KnownCorpusMount]:
    if not registry_path.exists():
        return []
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [
        KnownCorpusMount.model_validate(mount)
        for mount in payload.get("mounts", [])
        if isinstance(mount, dict)
    ]


def known_mount_for_current_root(
    mount: CorpusMount | None,
    registry_path: Path | None = None,
) -> KnownCorpusMount | None:
    """Return the registered mount matching the current mount URI and root path."""

    if mount is None:
        return None
    registry_path = registry_path or user_registry_path()
    for known_mount in read_known_mounts(registry_path):
        if known_mount.mount_uri == mount.mount_uri and same_root_path(
            known_mount.root_path,
            mount.root_path,
        ):
            return known_mount
    return None


def mount_is_registered(
    mount: CorpusMount | None,
    registry_path: Path | None = None,
) -> bool:
    return known_mount_for_current_root(mount, registry_path) is not None


def mount_registration_warning(
    config: CatalogConfig, mount: CorpusMount | None
) -> str | None:
    if mount is None or mount_is_registered(mount):
        return None
    return (
        f"Current mount {mount.mount_uri} is not registered at "
        f"{user_registry_path()}; run catalog mounts --root {config.corpus_root}."
    )


def same_root_path(left: str, right: str) -> bool:
    return str(Path(left).expanduser().resolve()) == str(
        Path(right).expanduser().resolve()
    )


def register_mount(
    registry_path: Path,
    mounts: list[KnownCorpusMount],
    mount: CorpusMount,
) -> tuple[list[KnownCorpusMount], bool]:
    now = utc_now()
    updated = False
    by_uri = {known.mount_uri: known for known in mounts}
    existing = by_uri.get(mount.mount_uri)
    if existing is None:
        by_uri[mount.mount_uri] = KnownCorpusMount(
            **mount.model_dump(mode="json"),
            registered_at=now,
            last_seen_at=now,
        )
        updated = True
    elif existing.root_path != mount.root_path or existing.last_seen_at != now:
        payload = mount.model_dump(mode="json")
        for field in PLACEMENT_FIELDS:
            value = getattr(existing, field)
            if value not in (None, []):
                payload[field] = value
        by_uri[mount.mount_uri] = KnownCorpusMount(
            **payload,
            registered_at=existing.registered_at,
            last_seen_at=now,
        )
        updated = True

    sorted_mounts = sorted(by_uri.values(), key=lambda known: known.mount_uri)
    if updated:
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "updated_at": now,
                    "mounts": [
                        known.model_dump(mode="json") for known in sorted_mounts
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return sorted_mounts, updated


def mount_sync_status(
    config: CatalogConfig, mount: CorpusMount | None
) -> MountSyncStatus | None:
    if mount is None:
        return None

    transport = (mount.sync_transport or "").casefold()
    realm = mount.realm.casefold()
    if transport == "git" or realm in {"work", "git"}:
        return git_sync_status(config, mount)
    if transport == "icloud" or realm == "icloud":
        return MountSyncStatus(
            realm=mount.realm,
            sync_transport=mount.sync_transport,
            confidence="local-metadata",
            state="local-exists",
            detail="Local mount path exists; cloud convergence is opaque.",
        )
    return MountSyncStatus(
        realm=mount.realm,
        sync_transport=mount.sync_transport,
        confidence="declared-only",
        state="opaque",
        detail="No realm-specific freshness check is available.",
    )


def git_sync_status(config: CatalogConfig, mount: CorpusMount) -> MountSyncStatus:
    status = run_git(config.corpus_root, "status", "--short")
    if status is None:
        return MountSyncStatus(
            realm=mount.realm,
            sync_transport=mount.sync_transport,
            confidence="declared-only",
            state="git-unavailable",
            detail="Git status is unavailable for this mount path.",
        )

    branch = run_git(config.corpus_root, "rev-parse", "--abbrev-ref", "HEAD")
    commit = run_git(config.corpus_root, "rev-parse", "HEAD")
    dirty_paths = len([line for line in status.splitlines() if line.strip()])
    state = "clean" if dirty_paths == 0 else "dirty"
    detail = (
        "Git worktree is clean."
        if dirty_paths == 0
        else f"Git worktree has {dirty_paths} changed path(s)."
    )
    return MountSyncStatus(
        realm=mount.realm,
        sync_transport=mount.sync_transport,
        confidence="git",
        state=state,
        detail=detail,
        branch=branch,
        commit=commit,
        dirty_paths=dirty_paths,
    )


def run_git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ("git", "-C", str(root), *args),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def root_entry_item(items: list[CorpusItem]) -> CorpusItem | None:
    by_path = {item.source.path: item for item in items}
    for path in entry_paths():
        if item := by_path.get(path):
            return item
    return None


def string_field(front_matter: dict[str, Any], key: str) -> str | None:
    value = field_value(front_matter, key)
    if value is not None:
        return str(value)
    return None


def parse_corpus_uri(uri: str) -> dict[str, str | None]:
    match = CORPUS_URI_RE.match(uri)
    if match is None:
        raise CorpusIdentityError(f"Invalid corpus URI: {uri}")
    return match.groupdict()


def select_declared_value(
    explicit: str | None,
    corpus_parts: dict[str, str | None] | None,
    mount_parts: dict[str, str | None] | None,
    key: str,
) -> str | None:
    values = [
        value
        for value in (
            explicit,
            corpus_parts.get(key) if corpus_parts else None,
            mount_parts.get(key) if mount_parts else None,
        )
        if value
    ]
    if not values:
        return None
    first = values[0]
    if any(value.casefold() != first.casefold() for value in values):
        raise CorpusIdentityError(f"Corpus identity field {key!r} is inconsistent.")
    return first


def validate_consistent_identity(
    corpus_uri: str,
    mount_uri: str,
    owner_id: str,
    realm: str,
    tier: str,
    node_id: str,
) -> None:
    corpus_parts = parse_corpus_uri(corpus_uri)
    mount_parts = parse_corpus_uri(mount_uri)
    expected = {
        "owner": owner_id,
        "realm": realm,
        "tier": tier.casefold(),
    }
    for key, expected_value in expected.items():
        if str(corpus_parts[key]).casefold() != expected_value.casefold():
            raise CorpusIdentityError(
                f"Corpus URI does not match declared {key}: {expected_value}."
            )
        if str(mount_parts[key]).casefold() != expected_value.casefold():
            raise CorpusIdentityError(
                f"Mount URI does not match declared {key}: {expected_value}."
            )
    if mount_parts.get("node") != node_id:
        raise CorpusIdentityError("Mount URI does not match declared node ID.")
    if corpus_parts.get("node") is not None:
        raise CorpusIdentityError("Logical corpus URI must not include a node suffix.")


def format_corpus_uri(
    owner_id: str,
    realm: str,
    tier: str,
    *,
    node_id: str | None = None,
) -> str:
    uri = f"corpus://{owner_id}/{realm}/{tier.casefold()}"
    if node_id:
        uri = f"{uri}@{node_id}"
    return uri


def identity_aliases(owner_id: str, realm: str, tier: str) -> list[str]:
    short = f"{realm}/{tier.casefold()}"
    owner_scoped = f"{owner_id}/{short}"
    return [short, owner_scoped]


def mount_aliases(owner_id: str, realm: str, tier: str, node_id: str) -> list[str]:
    return [
        *identity_aliases(owner_id, realm, tier),
        f"{realm}/{tier.casefold()}@{node_id}",
        f"{owner_id}/{realm}/{tier.casefold()}@{node_id}",
    ]


def corpus_selector_values(mount: CorpusMount) -> set[str]:
    return {mount.corpus_uri, *identity_aliases(mount.owner_id, mount.realm, mount.tier)}


def mount_selector_values(mount: CorpusMount) -> set[str]:
    return {mount.mount_uri, *mount.aliases}


def user_registry_path() -> Path:
    corpus_home = os.environ.get(CORPUS_HOME_ENV)
    if corpus_home:
        return Path(corpus_home).expanduser() / REGISTRY_FILENAME
    return Path.home() / ".corpus" / REGISTRY_FILENAME


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
