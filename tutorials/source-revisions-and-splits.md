# Wikipedia Revisions And Benchmark Splits

Controlled excerpts with synthetic tables/figures use a separate, replayable
derived-source provenance chain, not a false claim that modified JSON is an
unchanged Wikipedia response. The bounded candidate and its dev-only family
reservation are described in [Development Corpus](development-corpus.md).

Publication runs should not use an unfixed "latest" Wikipedia page. PolyDocBench
can resolve an article once, request that exact MediaWiki `oldid`, and preserve
the raw query response, parse response, rendered HTML, normalized source JSON,
parser fingerprints, and SHA-256 checksums.

## Capture And Verify A Source

Use a new or empty directory:

```powershell
uv run python -m polydocbench capture-wiki "https://en.wikipedia.org/wiki/ASCII" -o outputs/sources/en/ascii
uv run python -m polydocbench verify-wiki-source outputs/sources/en/ascii --reparse
```

`verify-wiki-source` is offline. Without `--reparse` it verifies saved bytes,
MediaWiki page/revision identity, HTML, source schema, and source binding. With
`--reparse` it additionally requires the current parser files and parser package
versions to reproduce `source.json` exactly.

An explicit revision can be selected either in the URL or with `--revision-id`:

```powershell
uv run python -m polydocbench capture-wiki "https://en.wikipedia.org/w/index.php?oldid=1383170257" -o outputs/sources/en/ascii_1383170257
```

The capture is response-bound evidence, not a Wikimedia signature. Transcluded
templates and media are represented by the saved parsed HTML; render snapshots
must still copy the concrete media bytes. Copyright and redistribution rights
are a separate review and are never inferred from hashes or a Wikidata ID.

## Use Pinned Sources In An Experiment

For a new experiment root:

```powershell
uv run python scripts/run_tesseract_ocr_experiment.py --output-dir outputs/experiments/tesseract_pinned --languages en --article-ids history_russia --templates scientific_paper --profiles clean medium_scan --page-scope first --pin-source-revisions --snapshot-inputs --allow-asset-downloads
```

On the first run, `--pin-source-revisions` captures the source evidence. On a
later run, combine it with `--reuse`; the runner verifies the existing evidence
and refuses a plain legacy `source.json`. It never assigns a current revision to
an older source file retrospectively.

## Review Source Families

Build an artifact inventory, then generate a draft catalog:

```powershell
uv run python scripts/build_benchmark_manifest.py --input-dir outputs/experiments/tesseract_pinned
uv run python scripts/prepare_benchmark_splits.py draft --manifest outputs/experiments/tesseract_pinned/benchmark_inventory/manifest.json --output outputs/planning/source_families.draft.json
```

The draft groups equal `article_id` values only as a candidate. Review every
family, merge translated or concept-equivalent articles where appropriate, then
set `review_status` to `reviewed` and provide `reviewed_by` and a timezone-aware
`reviewed_at`. This is a human research decision; the tool does not self-approve it.

The catalog rejects a source SHA, canonical URL, language/page ID, or Wikidata
item assigned to different families. These checks prevent obvious leakage, but
they do not prove that two semantically related articles were identified.

## Freeze And Apply Dev/Test

After review:

```powershell
uv run python scripts/prepare_benchmark_splits.py freeze --catalog outputs/planning/source_families.reviewed.json --output outputs/planning/split_plan.json --seed 42 --development-fraction 0.2
uv run python scripts/build_benchmark_manifest.py --input-dir outputs/experiments/tesseract_pinned --split-plan outputs/planning/split_plan.json --output-dir outputs/experiments/tesseract_pinned/benchmark_release
```

`family_hash_v1` deterministically assigns whole families. Every language,
page, template, noise profile, and variant of a source follows its family into
one split. The plan is content-addressed and embedded in the resulting manifest.
Freeze it before model tuning; changing the catalog creates a new plan rather
than silently editing the test set. The target fraction is by family count, not
by image count, so report actual source and image counts for both splits.
