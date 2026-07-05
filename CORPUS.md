---
title: "CORPUS.md - Catalog"
doc_type: corpus-entry
corpus_spec_version: v0.20
corpus_spec_profile: project
corpus_spec_adoption: partial
corpus_spec_reviewed: 2026-06-03
corpus_spec_betas: []
tag: personal
tier_composition: BRIEF
---

# CORPUS.md - Catalog

Catalog is CORPUS-SPEC's executable companion: a CLI-first tool for
turning CORPUS-SPEC-shaped Markdown trees into queryable, source-cited
corpora.

## Boundary

Catalog is tightly coupled to CORPUS-SPEC but remains a separate
codebase so the lightweight `corpus-spec/` source tree can still be
pulled into projects without Python tooling.

Catalog owns:

- corpus discovery;
- CORPUS-SPEC version/profile/adoption parsing;
- source references;
- context packet assembly;
- deterministic validation;
- migration-aware conformance checks;
- CLI output suitable for humans and local AI tools.

Catalog does not own:

- normative CORPUS-SPEC text;
- CANS deployments or adapters;
- persistent memory;
- MCP/gateway protocols as the primary product.

## Working Rules

- Keep the executable CLI as the primary product. Adapters should wrap
  the CLI or library, not replace it.
- When CORPUS-SPEC changes, update Catalog selectors and validators in the
  same work cycle.
- Support mixed conformance. Validate each project against its declared
  baseline instead of forcing every project to the newest CORPUS-SPEC
  immediately.
- Keep deterministic behavior useful without a model.
- Do not add write automation until patch, diff, approval, validation,
  apply, and report behavior is explicit.

## Current Surface

- `catalog init`
- `catalog index`
- `catalog status`
- `catalog stats`
- `catalog health`
- `catalog context`
- `catalog search`
- `catalog validate`
- `catalog version`
- `catalog project new`

The Python module path is `corpus_catalog`.

## Release Contract

Catalog is released independently from `corpus-spec`, but every Catalog
release declares the `corpus-spec` version it was validated against.
The declaration lives in [`pyproject.toml`](./pyproject.toml):

```toml
[tool.corpus-catalog.release]
validated-corpus-spec = "v0.20"
```

The runtime mirror lives in `corpus_catalog.release` so installed wheels
can report the same value without needing the source checkout. Tests
must keep the runtime value and `pyproject.toml` value synchronized.

Release process:

1. Update `[project].version` in `pyproject.toml`.
2. Update `[tool.corpus-catalog.release].validated-corpus-spec` to the
   `corpus-spec` release used for validation.
3. Update `CHANGELOG.md` with the package release, validated
   `corpus-spec` version, and migration or install notes.
4. Run `uv sync --reinstall --extra dev` after moves/renames or when
   the local environment is stale.
5. Run `uv run pytest` and `uv run ruff check .`.
6. Run `uv build`; the releasable artifacts are the wheel and source
   distribution under `dist/`.
7. Commit release-prep changes, tag the package as `v<project.version>`,
   and push the branch and tag.
8. For local CLI deployment, use `scripts/install-catalog-release` for
   stable `catalog` and `scripts/install-catalog-dev` for source-backed
   `catalog-dev`. Avoid installing into the system Python.

## Verification

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv build
uv run catalog version
scripts/install-catalog-release --no-build
scripts/install-catalog-dev
uv run catalog context --root /Users/cmikeb/work/brief --cwd projects/spec --goal "Create a new project according to the local CORPUS-SPEC baseline"
```
