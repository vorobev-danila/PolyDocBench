# Benchmark Specification And Artifact Inventory

The [ICDAR 2027 roadmap](icdar-2027-plan.md) defines the publication work.
`configs/benchmark_icdar2027.json` is a Pydantic-validated **draft research target**,
not an executable generation configuration. It targets 8,640 images; it does
not claim that these images exist. All current inventory records remain
`split: "unassigned"` with inferred, unreviewed article families.

## Build An Inventory

From the repository root, with the project's `uv` environment installed:

```powershell
uv run python scripts/build_benchmark_manifest.py --input-dir outputs/experiments/tesseract_quality
```

Optional scope and output directory:

```powershell
uv run python scripts/build_benchmark_manifest.py --input-dir outputs/experiments/tesseract_quality --languages en ru --templates scientific_paper --output-dir outputs/benchmark_pilot_inventory
```

This is offline: no Wikipedia requests, OCR, model calls, rendering, or changes
to existing artifacts. It reads the current experiment tree:

```text
INPUT_ROOT/<language>/<article>/<template>/noisy/page_NNN/<profile>_<variant>_gt.json
INPUT_ROOT/<language>/<article>/<template>/noisy/page_NNN/<profile>_<variant>.jpg
INPUT_ROOT/<language>/<article>/<template>/noisy/page_NNN/clean_0.png
INPUT_ROOT/<language>/<article>/<template>/document.pdf
INPUT_ROOT/<language>/<article>/<template>/document_gt.json
INPUT_ROOT/<language>/<article>/source.json
```

The command writes `manifest.json` and `inventory_report.json` under
`INPUT_ROOT/benchmark_inventory` unless `--output-dir` is set. Paths inside each
record are POSIX paths **relative to INPUT_ROOT**, not to the manifest location.
Pass that same root, or its relocated copy, when verifying.

## Recorded Evidence

- Manifest schema `0.1`, distinct from GT schema and evaluation protocol.
- SHA-256 and byte size for source JSON, PDF, PDF GT, scan and paired scan GT.
- Content-addressed artifact ID based on identity and those five hashes.
- Language, article, template, original PDF page, local image page, noise profile
  and variant; image dimensions, DPI and the recorded affine transform.
- Source URL and declared schema versions. A URL is not a pinned source revision.
- Accepted and rejected counts, rejection details, and missing provenance counts.

The inventory validates source/GT schemas, declared image dimensions, pixel
coordinate convention, profile/variant identity, matrix shape/finite values and
presence of the source page in PDF GT. Missing images or parent files are errors,
not skipped samples. Shared parent files are hashed once during each build.

New pipeline 0.2 scans can include a validated `noise_generation` trace. The
inventory checks its PDF/GT/image hashes, source page, DPI, profile, variant and
composed transform against the paired files. It embeds the trace and removes
only the seed/parameter recording gaps. Historical records retain those gaps.
Ambiguous PNG/JPEG pairs are errors. See [Reproducible Noise](reproducible-noise.md).

This is **not** a complete annotation or renderer audit: it does not prove PDF
content, every GT polygon, visibility, label semantics, page provenance, or
reading order correct. E0 in the roadmap covers those checks.

Discovery starts from GT files in the documented tree. It does not discover
orphan images, failed requests with no GT, or samples that were never generated.
The draft matrix is not automatically compared with existing articles/templates.
Do not interpret an accepted count as benchmark completeness or model success rate.

## Verify Recorded Files

```powershell
uv run python scripts/build_benchmark_manifest.py --input-dir outputs/experiments/tesseract_quality --verify outputs/experiments/tesseract_quality/benchmark_inventory/manifest.json
```

Verification checks saved file fingerprints, without replacing the manifest.
It detects changed or missing recorded files, not newly added unrecorded files.
Rebuild a separate inventory to review additions. Verification is an integrity
check, not proof that historical generation can be repeated.

## Historical Provenance And Exit Codes

Historical artifacts do not reliably contain their generation seed, sampled
noise parameters, generator revision/environment, layout snapshots or asset
provenance. The importer conservatively lists these as gaps; it does not fill
them from the current installation or assume revision/license verification.
`generation_reproducibility` is always `not_established` for this inventory.

```powershell
uv run python scripts/build_benchmark_manifest.py --input-dir outputs/experiments/tesseract_quality --strict
```

- Exit `0`: nonempty selected inventory, no structural issues (or recorded file
  hashes verified). Provenance is still incomplete in ordinary mode.
- Exit `1`: empty inventory, rejected artifacts, or verification failures.
- Exit `2`: structurally valid data but missing historical provenance under
  `--strict`. Expected for current historical datasets; not a noise/render failure.

An inventory containing rejected records preserves the rejection list and returns
failure; accepted records do not make the full selected inventory valid. Files
are assumed quiescent during build/verification. Regenerating an inventory after
tampering creates a new baseline, not proof of integrity against the old baseline.

Isolated noise RNG, generation traces and clean controls are now available for
new scans. Next work: reviewed families/splits, full source/render provenance,
pilot timings and budget. Existing experiment runners are not yet switched to
manifest-driven execution. Noise-only replay is not a complete benchmark release.
