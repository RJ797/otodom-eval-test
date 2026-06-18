"""Run a registered dataset through the model variants and store results.

Usage:
    python -m scripts.run_experiment --dataset batch1 --name "first eval"
    python -m scripts.run_experiment --dataset batch1 --run my_run_id \
        --variants gemini_min gemini_high flux --force

Each invocation creates/uses a run id (default: timestamp) so the same dataset
can be evaluated repeatedly without re-uploading inputs.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from app import config, experiment


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an evaluation over a dataset.")
    parser.add_argument("--dataset", required=True, help="Dataset id to evaluate")
    parser.add_argument("--run", default=None, help="Run id (default: timestamp)")
    parser.add_argument("--name", default="", help="Human-friendly run name")
    parser.add_argument(
        "--variants",
        nargs="*",
        default=config.DEFAULT_VARIANTS,
        help=f"Subset of variants (default: {config.DEFAULT_VARIANTS})",
    )
    parser.add_argument("--force", action="store_true", help="Re-run variants already completed")
    args = parser.parse_args()

    if not config.has_mongo():
        raise SystemExit("MONGODB_URI must be set in .env")
    if not config.has_s3():
        raise SystemExit("S3_BUCKET and CDN_BASE_URL must be set in .env")

    run_id = args.run or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    print(f"Run '{run_id}' over dataset '{args.dataset}' with variants {args.variants}")

    summary = experiment.run(
        run_id=run_id,
        name=args.name or run_id,
        dataset_id=args.dataset,
        variants=args.variants,
        force=args.force,
    )
    print(
        f"Done: {summary['completed']} ok, {summary['failed']} failed, "
        f"{summary['total']} total in {summary['elapsed_s']}s"
    )


if __name__ == "__main__":
    main()
