"""CORPUS-SPEC Catalog CLI and library surface."""

from corpus_catalog.config import CatalogConfig
from corpus_catalog.context import build_context_packet
from corpus_catalog.corpus import load_corpus, search_corpus
from corpus_catalog.health import build_corpus_stats, build_health_report
from corpus_catalog.models import (
    CatalogQuery,
    CorpusStats,
    CorpusIdentity,
    ContextItem,
    ContextPacket,
    CorpusItem,
    CorpusMount,
    HealthIssue,
    HealthReport,
    KnownCorpusMount,
    MountSuggestion,
    MountInventory,
    MountSyncStatus,
    SourceRef,
    SourceCodeDirectoryStat,
    ValidationIssue,
)
from corpus_catalog.release import (
    VALIDATED_CORPUS_SPEC_VERSION,
    catalog_version,
    release_metadata,
)

__all__ = [
    "CatalogConfig",
    "CatalogQuery",
    "ContextItem",
    "ContextPacket",
    "CorpusIdentity",
    "CorpusItem",
    "CorpusMount",
    "CorpusStats",
    "HealthIssue",
    "HealthReport",
    "KnownCorpusMount",
    "MountInventory",
    "MountSuggestion",
    "MountSyncStatus",
    "SourceRef",
    "SourceCodeDirectoryStat",
    "ValidationIssue",
    "VALIDATED_CORPUS_SPEC_VERSION",
    "build_context_packet",
    "build_corpus_stats",
    "build_health_report",
    "catalog_version",
    "load_corpus",
    "release_metadata",
    "search_corpus",
]
