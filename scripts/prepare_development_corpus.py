"""Capture pinned sources and build a separate development-only candidate."""

import argparse
import json
from pathlib import Path

from polydocbench.benchmark.development import DevelopmentSpec, build_development_corpus, capture_development_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["capture", "build"])
    parser.add_argument("--config", type=Path, default=Path("configs/development_corpus.json"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-cache", type=Path, help="Copy verified existing captures instead of requesting latest revisions")
    args = parser.parse_args()
    spec = DevelopmentSpec.model_validate_json(args.config.read_text(encoding="utf-8"))
    if args.stage == "capture":
        summary = capture_development_sources(spec, args.output_dir, source_cache=args.source_cache)
    else:
        manifest = build_development_corpus(spec, args.output_dir)
        summary = manifest.summary()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
