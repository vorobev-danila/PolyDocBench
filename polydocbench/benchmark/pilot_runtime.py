"""Supervise persistent pilot workers and retain the full evaluation denominator."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from statistics import mean, median
from time import perf_counter, sleep

from polydocbench.eval.dotsocr import DEFAULT_DOTSOCR_BASE_URL, DEFAULT_DOTSOCR_MODEL, DOTSOCR_ORDERING_PROMPT
from polydocbench.provenance import fingerprint_file, json_sha256
from .manifest import verify_manifest
from .pilot import PilotPlan


def default_model_config() -> dict:
    return {"tesseract_cmd": "tesseract", "model": DEFAULT_DOTSOCR_MODEL,
            "base_url": DEFAULT_DOTSOCR_BASE_URL, "api_key_env": "LITELLM_API_KEY",
            "prompt": DOTSOCR_ORDERING_PROMPT, "request_timeout": 180.0, "max_retries": 0,
            "quality_iou": 0.3, "structure_iou": 0.5, "min_similarity": 0.3, "max_gt_span": 3,
            "visibility_policy": None, "evaluation_contract": None}


def _tree_rss(process) -> int:
    import psutil

    total = 0
    try:
        processes = [process, *process.children(recursive=True)]
    except psutil.Error:
        processes = [process]
    for child in processes:
        try:
            total += child.memory_info().rss
        except psutil.Error:
            pass
    return total


def _stop_tree(process) -> None:
    import psutil

    try:
        children = process.children(recursive=True)
    except psutil.Error:
        children = []
    for child in [*reversed(children), process]:
        try:
            child.kill()
        except psutil.Error:
            pass
    # Let subprocess.Popen reap its own worker; psutil only waits on descendants.
    psutil.wait_procs(children, timeout=5)


def runtime_environment() -> dict:
    import psutil

    packages = {}
    for name in ("polydocbench", "psutil", "pytesseract", "docling", "docling-core", "torch", "openai", "pydantic", "shapely"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    root = Path(__file__).resolve().parents[2]
    code = [fingerprint_file(root, path).model_dump() for path in sorted((root / "polydocbench").rglob("*.py"))]
    return {"python": platform.python_version(), "platform": platform.platform(),
            "processor": platform.processor(), "logical_cpus": psutil.cpu_count(),
            "host_ram_bytes": psutil.virtual_memory().total, "packages": packages,
            "code_sha256": json_sha256({"files": code})}


def summarize_run(rows: list[dict], *, elapsed: float, peak_rss: int, engine: str) -> dict:
    statuses = dict(Counter(row["status"] for row in rows))
    successes = [row for row in rows if row["status"] == "success"]
    later = [row["inference_seconds"] for row in successes if row["phase"] == "subsequent_call"]
    first = next((row for row in rows if row.get("phase") == "first_call"), None)
    scoped = [row["metrics"] for row in successes if (row.get("metrics") or {}).get("evaluation_protocol_version") == "0.3"]
    from polydocbench.eval.scoped import scope_summary

    return {
        "selected": len(rows), "statuses": statuses, "successful": len(successes),
        "success_rate": len(successes) / len(rows) if rows else None,
        "elapsed_seconds": elapsed,
        "successful_images_per_minute": 60 * len(successes) / elapsed if elapsed else None,
        "first_call_inference_seconds": first.get("inference_seconds") if first else None,
        "subsequent_successful_call_count": len(later),
        "subsequent_inference_mean_seconds": mean(later) if later else None,
        "subsequent_inference_median_seconds": median(later) if later else None,
        "sampled_process_tree_peak_rss_bytes": peak_rss,
        "memory_scope": "client_process_tree_only" if engine == "dotsocr" else "local_worker_process_tree",
        "gpu_peak_bytes": None, "server_memory_bytes": None,
        "cost_currency": None, "measured_cost": None,
        **({"visibility": scope_summary(scoped), "scored_images": sum(r["scope_eligible_gt"] > 0 for r in scoped)} if scoped else {}),
        "limitations": ["RSS is sampled and sums shared pages across processes; not GPU VRAM or remote-server memory.",
                        "First call includes lazy setup; filesystem/model caches are not cleared.",
                        "Subsequent calls reuse the session but are not a controlled warm-cache experiment.",
                        "Timing is observational; model weights/server revision and monetary cost are not verified."],
    }


def run_pilot(plan: PilotPlan, input_dir: str | Path, output_dir: str | Path, *, engine: str,
              config: dict | None = None, timeout_per_image: float = 600, sample_interval: float = 0.1) -> dict:
    import psutil

    if engine not in {"tesseract", "dotsocr", "docling"}:
        raise ValueError("Unsupported pilot engine")
    if timeout_per_image <= 0 or sample_interval <= 0:
        raise ValueError("Timeout and memory sample interval must be positive")
    root = Path(input_dir).resolve(strict=True)
    issues = verify_manifest(plan.selection, root)
    if issues:
        raise ValueError(f"Pilot integrity verification failed: {issues[0].path}")
    output = Path(output_dir).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Pilot run output must be new or empty; cached predictions are never counted as inference")
    config = {**default_model_config(), **(config or {})}
    if config["evaluation_contract"] is not None:
        from polydocbench.eval.contract import FrozenEvaluation

        contract = FrozenEvaluation.model_validate(config["evaluation_contract"])
        expected = contract.model_config_values()
        if any(config[key] != value for key, value in expected.items()):
            raise ValueError("Pilot settings differ from the frozen evaluation contract")
    if config["visibility_policy"] is not None:
        from polydocbench.eval.scope import VisibilityPolicy

        config["visibility_policy"] = VisibilityPolicy.model_validate(config["visibility_policy"]).model_dump()
    # Only these public configuration keys are persisted; no API key value is accepted.
    if set(config) != set(default_model_config()):
        raise ValueError("Unknown model configuration key")
    environment = runtime_environment()
    if engine == "tesseract":
        command = shutil.which(config["tesseract_cmd"])
        if command is None:
            raise ValueError("Tesseract not found; use --tesseract-cmd")
        config["tesseract_cmd"] = command
        environment["tesseract_version"] = subprocess.run(
            [command, "--version"], capture_output=True, text=True, check=True, timeout=15
        ).stdout.splitlines()[0]
    output.mkdir(parents=True, exist_ok=True)
    job = {"plan": plan.model_dump(), "input_dir": str(root), "engine": engine, "config": config}
    job_path = output / "job.json"
    job_path.write_text(json.dumps(job, allow_nan=False), encoding="utf-8")
    metadata = {"schema_version": "0.1", "plan_id": plan.plan_id, "engine": engine,
                "started_at": datetime.now(timezone.utc).isoformat(), "environment": environment,
                "configuration_sha256": json_sha256({"engine": engine, "config": config, "environment": environment}),
                "timeout_per_image": timeout_per_image, "memory_sample_interval": sample_interval}
    (output / "run.json").write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding="utf-8")
    events_path = output / "events.jsonl"
    events, offset, buffer = [], 0, ""
    records_by_id = {record.artifact_id: record for record in plan.selection.records}
    completed = 0
    peak_rss = 0
    started = last_progress = perf_counter()
    timed_out = False
    with (output / "worker.log").open("w", encoding="utf-8") as log:
        worker = subprocess.Popen([sys.executable, "-B", "-m", "polydocbench.benchmark.pilot_worker", str(job_path)],
                                  stdout=log, stderr=subprocess.STDOUT)
        process = psutil.Process(worker.pid)
        try:
            while True:
                peak_rss = max(peak_rss, _tree_rss(process))
                if events_path.exists():
                    with events_path.open(encoding="utf-8") as source:
                        source.seek(offset)
                        buffer += source.read()
                        offset = source.tell()
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        event = json.loads(line)
                        events.append(event)
                        last_progress = perf_counter()
                        if event["event"] == "result":
                            completed += 1
                            record = records_by_id[event["artifact_id"]]
                            print(f"[{completed}/{len(records_by_id)}] {engine} "
                                  f"{record.language}/{record.article_id}/{record.template}/{record.profile}: {event['status']} "
                                  f"({event['total_seconds']:.2f}s)", flush=True)
                if worker.poll() is not None:
                    break
                if perf_counter() - last_progress > timeout_per_image:
                    timed_out = True
                    _stop_tree(process)
                    break
                sleep(sample_interval)
        finally:
            if worker.poll() is None:
                _stop_tree(process)
            worker.wait()
    # Drain final complete events after the process exits.
    if events_path.exists():
        content = events_path.read_text(encoding="utf-8")
        events = [json.loads(line) for line in content.splitlines(keepends=True)
                  if line.endswith("\n") and line.strip()]
    results = {event["artifact_id"]: {k: v for k, v in event.items() if k != "event"}
               for event in events if event["event"] == "result"}
    attempted = {event["artifact_id"]: event for event in events if event["event"] == "start"}
    rows = []
    for record in plan.selection.records:
        row = results.get(record.artifact_id)
        if row is None:
            status = ("timeout" if timed_out else "worker_failed") if record.artifact_id in attempted else "not_run"
            row = {"artifact_id": record.artifact_id, "engine": engine, "status": status,
                   "phase": attempted.get(record.artifact_id, {}).get("phase"),
                   "inference_seconds": None, "evaluation_seconds": None, "metrics": None}
        rows.append({**row, "language": record.language, "source_family": record.source_family,
                     "article_id": record.article_id, "template": record.template,
                     "source_page_number": record.source_page_number, "profile": record.profile,
                     "plan_id": plan.plan_id, "configuration_sha256": metadata["configuration_sha256"]})
    with (output / "results.jsonl").open("x", encoding="utf-8") as target:
        for row in rows:
            target.write(json.dumps(row, ensure_ascii=True, allow_nan=False) + "\n")
    summary = summarize_run(rows, elapsed=perf_counter() - started, peak_rss=peak_rss, engine=engine)
    summary.update(plan_id=plan.plan_id, engine=engine, worker_exit_code=worker.returncode,
                   timeout_triggered=timed_out)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
    return summary
