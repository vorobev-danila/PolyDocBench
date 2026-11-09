"""Prepare or verify the evidence-bound human review handoff."""

import argparse
import json
from pathlib import Path

from polydocbench.benchmark.development_review import check_development_review, prepare_development_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "check"])
    parser.add_argument("--input-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.stage == "prepare":
        result = prepare_development_review(args.input_dir)
        print(f"Prepared {len(result.decisions)} pending decisions; no approval granted")
        return 0
    result = check_development_review(args.input_dir)
    print(json.dumps(result, indent=2))
    return 0 if result["development_approved"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
