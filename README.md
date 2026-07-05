---
title: "Catalog"
doc_type: tool-readme
corpus_spec_version: v0.20
status: prototype
maturity: prototype
---

# Catalog

Catalog is the CORPUS-SPEC-coupled CLI for making a directory of
well-organized Markdown files usable as a corpus.

Markdown plus Git remains the source of truth. CORPUS-SPEC defines the
organization rules and conformance levels. Catalog is the executable
companion that reads those rules, builds a derived queryable view, and
emits source-cited context packets and validation reports for humans,
Codex, local models, and future adapters.

## Name And Boundary

`Catalog` is a code artifact owned by the Spec project. It is not a
CANS integration, though CANS may later wrap it with an MCP server or
adapter.

The distinction matters:

- **Files** are just Markdown plus Git until a reader applies CORPUS-SPEC.
- **CORPUS-SPEC** defines the rules, profiles, version markers,
  conformance levels, and migration posture.
- **Catalog** is the executable reader over those files: inventory,
  search, validation, and source-cited context assembly.
- **Corpus** is the result of applying Catalog and CORPUS-SPEC to a
  mounted tree.
- **Adapters** such as MCP servers, Codex tools, or CANS integrations
  can wrap the CLI later.

Catalog should be tightly coupled to CORPUS-SPEC versions. When CORPUS-SPEC
changes project shape, front matter, conformance markers, or migration
rules, Catalog should gain the matching selectors and validators.

Catalog should also understand mixed conformance. One Catalog release
may need to validate a v0.18 tier root, a v0.16 project, and a partially
adopted older project without forcing an immediate migration.

## First Surface

The initial deterministic surface is:

- discover relevant Markdown sources under a corpus root;
- parse simple YAML-style front matter from `CORPUS.md`, legacy `CORPUS.md`,
  READMEs,
  registries, overviews, and task files;
- honor root `.corpusignore` rules before include pattern checks;
- index active epic `SPIKE.md` files and reference Markdown by default;
- model CORPUS-SPEC root, spec, and profile modules as first-class sources;
- route context packets through owning profile/spec modules before
  lexical search;
- parse corpus identity and mount identity from the tier-root entry;
- search corpus items lexically;
- assemble a source-cited context packet for a goal and cwd;
- run cheap validation checks, starting with root handbook presence and
  active epic bookmark checks.

This intentionally does not require an LLM. A model-facing agent,
MCP server, or Codex tool can sit on top once the deterministic CLI is
boring and tested.

## CLI

After installing the package, the executable is `catalog`.

All commands accept `--root`, but it is optional. When omitted, Catalog
uses the current working directory as the corpus root.

Running `catalog` with no subcommand defaults to `catalog status` when
the current directory looks like a corpus root. Elsewhere, it prints
the top-level help.

From this directory:

```bash
catalog init --root ../../..
catalog index --root ../../..
catalog status --root ../../..
```

From the corpus root:

```bash
catalog init
catalog index
catalog status
catalog stats
catalog health
catalog mounts
```

```bash
catalog context \
  --root ../../.. \
  --cwd projects/spec \
  --goal "Create a new project according to the local CORPUS-SPEC baseline"
```

Equivalent module invocation:

```bash
python -m corpus_catalog.cli context \
  --root ../../.. \
  --cwd projects/spec \
  --goal "Create a new project according to the local CORPUS-SPEC baseline"
```

Search:

```bash
catalog search --root ../../.. --query "context packet"
catalog search --corpus work/brief --query "context packet"
```

`search` prints compact source hits for command-line use: source
metadata, a matched snippet, selected CORPUS-SPEC metadata, and content
hash. Use `context` when you want bounded source excerpts for agent
work.

Validate:

```bash
catalog validate --root ../../.. --format json
catalog validate --corpus corpus://cmikeb/work/brief --format json
```

Stats and local health:

```bash
catalog stats --root ../../..
catalog stats --root ../../.. --format json --top 25
catalog health --root ../../..
catalog health --root ../../.. --format json --write-report --fail-on error
```

`stats` reports local corpus file counts, bytes, Markdown versus
non-Markdown balance, Catalog-visible source count, top extensions, top
directories, largest files, `.corpusignore` coverage, Git-tracked status
when available, and package-like `projects/*/code/*` directories with
obvious identity markers such as `README.md`, `pyproject.toml`,
`package.json`, `Cargo.toml`, and `go.mod`.

`health` is an operational node check, separate from `validate`.
`validate` answers whether source corpus content conforms to the current
CORPUS-SPEC rules. `health` answers whether the local mount, derived
data, search scope, large files, generated directories, and surrounding
tooling are healthy for this node. By default it is read-only: it does
not move files, edit `.corpusignore`, alter Git history, or clean build
output.

Health checks include:

- large Git-tracked files against the Git-light policy;
- large local files;
- heavy directories by byte or file count;
- generated/dependency/cache directories that may deserve
  `.corpusignore` rules;
- package-like source directories that should usually be ignored until a
  deliberate software-project summary interface exists;
- migration suggestions when registered mounts advertise storage roles.

First-pass Git-light thresholds are 1 MiB warning and 10 MiB error.
Mount registry entries may override these with
`large_file_warn_bytes` and `large_file_error_bytes`.

Release metadata:

```bash
catalog version
catalog version --format json
```

The version command reports both the Catalog package version and the
`corpus-spec` release this package was validated against.

Mount inventory:

```bash
catalog mounts --format json
catalog mounts --no-register
```

`mounts` reports the current declared corpus/mount identity and, by
default, records the current mount in the per-user registry at
`~/.corpus/mounts.json`. Set `CORPUS_HOME` to place that registry
somewhere else for tests or isolated runs.

Registry entries may carry optional placement metadata. Catalog
preserves these hand-edited fields when re-registering a mount and uses
them for health suggestions only:

```json
{
  "storage_role": "git-light",
  "intent": "Portable Markdown-first BRIEF corpus for broad device access.",
  "preferred_for": ["markdown", "small-docs", "source-of-truth"],
  "avoid_for": ["large-binaries", "media", "build-output"],
  "large_file_warn_bytes": 1048576,
  "large_file_error_bytes": 10485760
}
```

Suggested storage roles are `git-light`, `cloud-docs`, and
`bulk-media`.

`status` reports whether the current mount is already registered and
suggests `catalog mounts --root <root>` when the local registry has not
seen this mount/root pair. `validate` does not mutate the registry, but it
emits a warning when the current mount is missing from the registry.

`context`, `search`, and `validate` accept `--corpus` and `--mount`
selectors. Selectors must match the declared current root identity by
canonical URI or alias, such as `work/brief` or `work/brief@bilby`;
Catalog does not guess paths for a selector that names another corpus.

Project creation dry-run, from the corpus root:

```bash
catalog project new \
  --name "Example Project" \
  --tag personal \
  --tier BRIEF
```

Run project-creation follow-up commands from the corpus root; they use
the current working directory as the default root.

## `.corpus/` Derived State

`catalog init` creates a generated `.corpus/` directory at the corpus
root. `catalog index` refreshes it from source Markdown.

MVP artifacts:

- `.corpus/CORPUS.md` — generated orientation for humans and AI tools;
- `.corpus/manifest.json` — Catalog version, corpus identity, current
  mount identity, baseline, freshness, source fingerprint, artifacts,
  conformance markers, and spec/profile module inventory;
- `.corpus/catalog.sqlite` — durable source, validation, and
  conformance tables, plus reusable `spec_modules`,
  `corpus_identity`, and `corpus_mounts` registries;
- `.corpus/indexes/sources.jsonl` — portable source inventory;
- `.corpus/indexes/validation-issues.jsonl` — portable validation
  issue export;
- `.corpus/reports/validation.md` — human validation receipt;
- `.corpus/jobs/last-run.json` — last indexing receipt;
- `.corpus/reports/health.md` — optional human health receipt from
  `catalog health --write-report`;
- `.corpus/jobs/last-health.json` — optional machine-readable health
  receipt from `catalog health --write-report`;
- `.corpus/embeddings/` — reserved for future vector artifacts.

Source files remain canonical. Catalog excludes `.corpus/` from corpus
discovery and does not edit `.gitignore`; `catalog init` warns if the
generated directory does not appear to be ignored. Legacy `.catalog/`
state is not read after the cutover; rebuild `.corpus/` and delete the
old directory after validation.

## `.corpusignore`

Catalog reads a root `.corpusignore` before applying source include
patterns. The first implementation intentionally supports a small
`fnmatch` subset:

- blank lines and `#` comments are ignored;
- root-relative patterns match the POSIX-style corpus path;
- trailing-slash patterns match a directory and everything below it;
- bare filename patterns match any path segment with that name.

Use `.corpusignore` for package-local code docs, fixture corpora,
generated docs, build output, and other Markdown that belongs to the
software project rather than the human corpus. Validation warns when a
known package-local code checkout exists without a recommended
`.corpusignore` rule.

## Validation Ownership

Validation issue codes name the owning rule layer:

- `core-*` covers corpus root entrypoints, required conformance
  frontmatter, `.corpusignore` recommendations, and component README
  metadata.
- `profile-project-*`, `profile-workspace-*`, and
  `profile-reference-*` cover project, workspace, and reference profile
  shape checks.
- `spec-beta-*` and `profile-beta-*` cover beta stewardship checks in
  the Spec-owned source checkout.

Root, project, and reference entrypoint checks prefer current
`CORPUS.md` files and accept legacy `CORPUS.md` / `corpus.md` files during
the naming cutover.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
```

The package currently depends on Pydantic for boundary models and uses
the Python standard library for discovery, parsing, search, and CLI.

## Release And Deployment

Catalog is a Python package. A Catalog release has two version axes:

- `[project].version` in `pyproject.toml` is the Catalog package
  version and becomes the Git tag name, such as `v0.2.0`.
- `[tool.corpus-catalog.release].validated-corpus-spec` in
  `pyproject.toml` is the `corpus-spec` release used to validate this
  Catalog release, such as `v0.20`.

The runtime mirror in `corpus_catalog.release` is included in the
installed wheel so `catalog version` and generated `.corpus/` manifests
can report the validated `corpus-spec` release. Tests enforce that the
runtime mirror matches `pyproject.toml`.

Release checklist:

```bash
uv sync --reinstall --extra dev
uv run pytest
uv run ruff check .
uv build
git status --short --branch
git tag -a v0.2.0 -m "corpus-catalog v0.2.0"
git push origin main
git push origin v0.2.0
```

`uv build` creates the deployable artifacts under `dist/`:

- a wheel, installed by package tools for normal use;
- a source distribution, useful for source-based rebuilds and audit.

For local CLI deployment, prefer an isolated tool install rather than
writing into the system Python:

```bash
scripts/install-catalog-release
catalog version
```

For source snapshots, install a side-by-side wrapper:

```bash
scripts/install-catalog-dev
catalog-dev version
```

`catalog` is the stable released tool. `catalog-dev` runs this source
checkout through `uv run --project`, so pulling new commits into this
repo updates the snapshot command without reinstalling it.
