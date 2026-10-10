"""Shared run logging for the experiment scripts.

Every run gets its own folder:

    results/<experiment>/<YYYYmmdd-HHMMSS>_<mode>/
        manifest.json   what was run, on which code and machine, timings, status, outputs
        run.log         console output of the run
        *.csv           metric tables (every row has a `mode` column)
        figures/*.png   plots

The manifest is written at the start (status "running") and rewritten at the end
(status "ok" or "failed"), so an interrupted run is still visible.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_DIR = REPO_ROOT / "results"
PACKAGES = ["numpy", "scipy", "pandas", "scikit-learn", "matplotlib", "torch", "dml"]

MODE_NOTES = {
    "quick": "Reduced settings for a fast check of the pipeline. "
             "Numbers are NOT comparable with full-mode runs or with the paper.",
    "full": "Settings of the corresponding notebook (reference results).",
}


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _package_versions() -> dict:
    versions = {}
    for name in PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _jsonable(value):
    """Convert numpy / torch scalars and other objects to plain JSON types."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class RunLogger:
    """Creates the run folder, mirrors console output to run.log and writes manifest.json."""

    def __init__(self, experiment: str, mode: str, params: dict, notebook: str,
                 results_dir: Path | str | None = None):
        self.experiment = experiment
        self.mode = mode
        self.started = time.perf_counter()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        root = Path(results_dir) if results_dir else DEFAULT_RESULTS_DIR
        self.dir = root / experiment / f"{stamp}_{mode}"
        suffix = 1
        while self.dir.exists():                      # two runs in the same second
            self.dir = root / experiment / f"{stamp}_{mode}_{suffix}"
            suffix += 1
        (self.dir / "figures").mkdir(parents=True)

        self.logger = logging.getLogger(f"run.{experiment}.{stamp}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        fmt = logging.Formatter("%(asctime)s | %(message)s", "%H:%M:%S")
        for handler in (logging.FileHandler(self.dir / "run.log", encoding="utf-8"),
                        logging.StreamHandler(sys.stdout)):
            handler.setFormatter(fmt)
            self.logger.addHandler(handler)

        self.timings: list[dict] = []
        self.outputs: list[str] = ["manifest.json", "run.log"]
        self.manifest = {
            "experiment": experiment,
            "notebook": notebook,
            "mode": mode,
            "mode_note": MODE_NOTES.get(mode, ""),
            "status": "running",
            "params": _jsonable(params),
            "command": " ".join([Path(sys.executable).name, *sys.argv]),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "duration_seconds": None,
            "git": {"commit": _git("rev-parse", "HEAD"),
                    "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                    "dirty": bool(_git("status", "--porcelain"))},
            "environment": {"python": platform.python_version(),
                            "platform": platform.platform(),
                            "cpu_count": os.cpu_count(),
                            "packages": _package_versions()},
            "timings": self.timings,
            "summary": {},
            "outputs": self.outputs,
            "error": None,
        }
        self._write_manifest()
        self.log(f"Run folder: {self.dir}")
        self.log(f"Experiment: {experiment} | mode: {mode.upper()} — {MODE_NOTES.get(mode, '')}")
        self.log(f"Parameters: {json.dumps(self.manifest['params'], ensure_ascii=False)}")

    # ------------------------------------------------------------------ logging
    def log(self, message: str) -> None:
        self.logger.info(message)

    def set_info(self, key: str, value) -> None:
        """Add extra information to the manifest, e.g. the device actually used."""
        self.manifest["environment"][key] = _jsonable(value)
        self._write_manifest()

    @contextmanager
    def timed(self, step: str, **meta):
        """Time a block: `with run.timed("section 2"): ...` -> recorded in manifest["timings"]."""
        start = time.perf_counter()
        self.log(f"start: {step}")
        try:
            yield
        finally:
            seconds = time.perf_counter() - start
            self.timings.append({"step": step, "seconds": round(seconds, 3), **_jsonable(meta)})
            self.log(f"done:  {step} ({seconds:.1f}s)")
            self._write_manifest()

    # ------------------------------------------------------------------ outputs
    def save_table(self, df, name: str, index: bool = False) -> Path:
        """Save a pandas DataFrame as CSV with a `mode` column in front."""
        df = df.copy()
        if "mode" not in df.columns:
            df.insert(0, "mode", self.mode)
        path = self.dir / f"{name}.csv"
        df.to_csv(path, index=index)
        self.outputs.append(path.name)
        self.log(f"saved table: {path.name}")
        return path

    def save_figure(self, fig, name: str) -> Path:
        import matplotlib.pyplot as plt
        path = self.dir / "figures" / f"{name}.png"
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        self.outputs.append(f"figures/{path.name}")
        self.log(f"saved figure: figures/{path.name}")
        return path

    def add_summary(self, **items) -> None:
        """Key results for a quick look (also used by the agent to report back)."""
        self.manifest["summary"].update(_jsonable(items))
        self._write_manifest()

    # ------------------------------------------------------------------ end of run
    def finish(self, error: BaseException | None = None) -> None:
        self.manifest["status"] = "failed" if error else "ok"
        self.manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
        self.manifest["duration_seconds"] = round(time.perf_counter() - self.started, 1)
        if error:
            self.manifest["error"] = "".join(traceback.format_exception(error)).strip()
            self.log(f"FAILED: {error!r}")
        self._write_manifest()
        self.log(f"Status: {self.manifest['status']} | total time "
                 f"{self.manifest['duration_seconds']}s | results in {self.dir}")
        for handler in list(self.logger.handlers):
            handler.close()
            self.logger.removeHandler(handler)

    def _write_manifest(self) -> None:
        with open(self.dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)


def run_main(main, logger_factory):
    """Run `main(run)` and always close the run with the right status.

    logger_factory: callable returning a RunLogger (created after argument parsing).
    Exit code is 1 on failure, so the agent and the shell can see it.
    """
    run = logger_factory()
    try:
        main(run)
    except BaseException as exc:          # also KeyboardInterrupt: mark the run as failed
        run.finish(error=exc)
        sys.exit(1)
    run.finish()
