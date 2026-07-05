from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from corpus_catalog.naming import legacy_field, normalize_metadata_fields


Severity = Literal["info", "warning", "error"]
SourceKind = Literal[
    "handbook",
    "overview",
    "tasks",
    "spike",
    "reference",
    "registry",
    "readme",
    "spec-root",
    "spec-module",
    "profile-module",
    "spec",
    "note",
]
CatalogState = Literal["missing", "stale", "fresh"]
SpecModuleType = Literal["root-spec", "spec", "profile"]
SyncConfidence = Literal["git", "local-metadata", "declared-only"]


class SourceRef(BaseModel):
    """Stable reference to source corpus material."""

    model_config = ConfigDict(extra="forbid")

    path: str
    kind: SourceKind = "note"
    title: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    excerpt: str | None = None

    @model_validator(mode="after")
    def validate_line_range(self) -> SourceRef:
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class CorpusItem(BaseModel):
    """Parsed corpus item with source metadata and text."""

    model_config = ConfigDict(extra="forbid")

    source: SourceRef
    title: str
    front_matter: dict[str, Any] = Field(default_factory=dict)
    text: str
    content_hash: str | None = None


class ContextItem(BaseModel):
    """Bounded source excerpt selected for a context packet."""

    model_config = ConfigDict(extra="forbid")

    source: SourceRef
    title: str
    front_matter: dict[str, Any] = Field(default_factory=dict)
    excerpt: str


class ValidationIssue(BaseModel):
    """Cheap deterministic issue found while reading the corpus."""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Severity
    message: str
    source: SourceRef | None = None
    baseline: str | None = None


class CatalogQuery(BaseModel):
    """Request shape for a context packet."""

    model_config = ConfigDict(extra="forbid")

    goal: str
    cwd: str | None = None


class ContextPacket(BaseModel):
    """Source-cited context bundle for an agent or adapter."""

    model_config = ConfigDict(extra="forbid")

    query: CatalogQuery
    items: list[ContextItem]
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)
    baseline: str | None = None
    source_fingerprint: str | None = None


class ConformanceMarker(BaseModel):
    """Declared CORPUS-SPEC conformance metadata discovered in source files."""

    model_config = ConfigDict(extra="forbid")

    path: str
    corpus_spec_version: str | None = None
    corpus_spec_profile: str | None = None
    corpus_spec_adoption: str | None = None
    corpus_spec_reviewed: str | None = None
    corpus_spec_betas: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return normalize_metadata_fields(data)
        return data


class SpecModule(BaseModel):
    """CORPUS-SPEC root/spec/profile module discovered in source."""

    model_config = ConfigDict(extra="forbid")

    path: str
    module_type: SpecModuleType
    module_id: str
    title: str | None = None
    doc_type: str | None = None
    status: str | None = None
    corpus_spec_version: str | None = None
    source_checkout: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return normalize_metadata_fields(data)
        return data


class CorpusIdentity(BaseModel):
    """Logical CORPUS-SPEC corpus identity declared by a corpus root."""

    model_config = ConfigDict(extra="forbid")

    corpus_uri: str
    owner_id: str
    realm: str
    tier: str
    aliases: list[str] = Field(default_factory=list)


class CorpusMount(BaseModel):
    """One local mount of a logical corpus on a node."""

    model_config = ConfigDict(extra="forbid")

    corpus_uri: str
    mount_uri: str
    owner_id: str
    realm: str
    tier: str
    node_id: str
    sync_transport: str | None = None
    root_path: str
    aliases: list[str] = Field(default_factory=list)
    storage_role: str | None = None
    intent: str | None = None
    preferred_for: list[str] = Field(default_factory=list)
    avoid_for: list[str] = Field(default_factory=list)
    large_file_warn_bytes: int | None = Field(default=None, ge=0)
    large_file_error_bytes: int | None = Field(default=None, ge=0)


class KnownCorpusMount(CorpusMount):
    """A mount recorded in the per-user corpus registry."""

    registered_at: str | None = None
    last_seen_at: str | None = None


class MountSyncStatus(BaseModel):
    """Realm-specific local freshness signal, separate from validation."""

    model_config = ConfigDict(extra="forbid")

    realm: str
    sync_transport: str | None = None
    confidence: SyncConfidence
    state: str
    detail: str
    branch: str | None = None
    commit: str | None = None
    dirty_paths: int | None = None


class MountInventory(BaseModel):
    """Current and known corpus mounts visible to Catalog."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    registry_path: str
    current_mount: CorpusMount | None = None
    known_mounts: list[KnownCorpusMount] = Field(default_factory=list)
    registry_updated: bool = False
    sync_status: MountSyncStatus | None = None


class FileStat(BaseModel):
    """One scanned local file in a corpus root."""

    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int = Field(ge=0)
    extension: str
    is_markdown: bool = False
    tracked_by_git: bool | None = None
    ignored_by_corpusignore: bool = False
    catalog_visible: bool = False


class DirectoryStat(BaseModel):
    """Aggregated local directory size/count data."""

    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int = Field(ge=0)
    file_count: int = Field(ge=0)
    markdown_file_count: int = Field(default=0, ge=0)
    catalog_visible_file_count: int = Field(default=0, ge=0)
    ignored_file_count: int = Field(default=0, ge=0)
    ignored_bytes: int = Field(default=0, ge=0)
    ignored_by_corpusignore: bool = False


class ExtensionStat(BaseModel):
    """Aggregated local file-extension size/count data."""

    model_config = ConfigDict(extra="forbid")

    extension: str
    file_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)


class SourceCodeDirectoryStat(BaseModel):
    """Package-like code directory surfaced for corpus-health review."""

    model_config = ConfigDict(extra="forbid")

    path: str
    size_bytes: int = Field(ge=0)
    file_count: int = Field(ge=0)
    markdown_file_count: int = Field(default=0, ge=0)
    catalog_visible_file_count: int = Field(default=0, ge=0)
    ignored_by_corpusignore: bool = False
    markers: list[str] = Field(default_factory=list)
    readme_path: str | None = None


class CorpusStats(BaseModel):
    """Corpus-local filesystem/search/sync observability report."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    generated_at: str
    corpus_root: str
    current_mount: CorpusMount | None = None
    registered_mount: KnownCorpusMount | None = None
    git_available: bool = False
    corpusignore_patterns: list[str] = Field(default_factory=list)
    total_file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    markdown_file_count: int = Field(ge=0)
    markdown_bytes: int = Field(ge=0)
    non_markdown_file_count: int = Field(ge=0)
    non_markdown_bytes: int = Field(ge=0)
    catalog_visible_source_count: int = Field(ge=0)
    corpusignored_file_count: int = Field(ge=0)
    corpusignored_bytes: int = Field(ge=0)
    git_tracked_file_count: int | None = None
    git_tracked_bytes: int | None = None
    largest_files: list[FileStat] = Field(default_factory=list)
    largest_directories: list[DirectoryStat] = Field(default_factory=list)
    extensions: list[ExtensionStat] = Field(default_factory=list)
    source_code_directories: list[SourceCodeDirectoryStat] = Field(
        default_factory=list
    )


class MountSuggestion(BaseModel):
    """Registered mount that may be a better home for a health finding."""

    model_config = ConfigDict(extra="forbid")

    mount_uri: str
    root_path: str
    storage_role: str | None = None
    intent: str | None = None


class HealthIssue(BaseModel):
    """Operational corpus-host health finding."""

    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Severity
    message: str
    path: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    file_count: int | None = Field(default=None, ge=0)
    tracked_by_git: bool | None = None
    confidence: str | None = None
    recommendation: str | None = None
    suggested_mounts: list[MountSuggestion] = Field(default_factory=list)


class HealthReport(BaseModel):
    """Read-only local node/tooling health report."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    generated_at: str
    corpus_root: str
    stats: CorpusStats
    issues: list[HealthIssue] = Field(default_factory=list)


class CatalogArtifact(BaseModel):
    """Generated artifact tracked in the Catalog manifest."""

    model_config = ConfigDict(extra="forbid")

    path: str
    kind: str
    exists: bool = False
    updated_at: str | None = None


class CatalogManifest(BaseModel):
    """Manifest for the generated .corpus workbench."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    catalog_version: str
    validated_corpus_spec_version: str | None = None
    corpus_root: str
    catalog_dir: str
    generated_at: str | None = None
    corpus_spec_baseline: str | None = None
    source_fingerprint: str | None = None
    source_count: int = 0
    validation_issue_count: int = 0
    corpus_identity: CorpusIdentity | None = None
    current_mount: CorpusMount | None = None
    artifacts: list[CatalogArtifact] = Field(default_factory=list)
    conformance: list[ConformanceMarker] = Field(default_factory=list)
    spec_modules: list[SpecModule] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            normalized = dict(data)
            legacy_key = legacy_field("baseline")
            if "corpus_spec_baseline" not in normalized and legacy_key in normalized:
                normalized["corpus_spec_baseline"] = normalized.pop(legacy_key)
            return normalized
        return data


class CatalogStatus(BaseModel):
    """Freshness and availability report for .corpus derived state."""

    model_config = ConfigDict(extra="forbid")

    state: CatalogState
    corpus_root: str
    catalog_dir: str
    manifest_exists: bool
    missing_artifacts: list[str] = Field(default_factory=list)
    stale_reasons: list[str] = Field(default_factory=list)
    next_commands: list[str] = Field(default_factory=list)
    current_mount: CorpusMount | None = None
    mount_registry_path: str | None = None
    mount_registered: bool | None = None
    mount_sync_status: MountSyncStatus | None = None
    manifest: CatalogManifest | None = None


class ProjectPlanFile(BaseModel):
    """One file operation in a read-only project scaffold plan."""

    model_config = ConfigDict(extra="forbid")

    path: str
    action: Literal["create", "update", "inspect"]
    purpose: str
    required: bool = True


class ProjectCreationPlan(BaseModel):
    """Dry-run contract for creating a CORPUS-SPEC-shaped project."""

    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str
    project_path: str
    lifecycle: str
    tag: str | None = None
    tier: str | None = None
    corpus_spec_baseline: str | None = None
    files: list[ProjectPlanFile]
    sources: list[SourceRef]
    commands: list[str]
    notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
