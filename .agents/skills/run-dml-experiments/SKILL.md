---
name: run-dml-experiments
description: Run the reproduction experiments of the "Differential Machine Learning" paper (Huge & Savine) in this repository and log every run to results/. Covers the twin network vs standard network experiment and differential regression (Appx 3). Use when the user asks to run, rerun or reproduce an experiment, to check that the experiments still work, or to produce fresh results and logs. Not for analysing old results or building slides.
---

# Run DML experiments

Runs the experiment scripts in `experiments/` and reports what happened. Every run writes its own
folder under `results/` with a manifest, metric tables, figures and the console log. The scripts
reproduce the notebooks in `notebooks/`; do not run the notebooks themselves for this task.

## Experiments

| Key | Script | Notebook | What it shows | Quick | Full (laptop CPU) |
|---|---|---|---|---|---|
| `twin_network` (main) | `experiments/run_twin_network.py` | `DifferentialML_PyTorch.ipynb` | standard vs differential network, Black–Scholes and Bachelier d = 1, 7, 50 | ~1 min | ~3–5 min |
| `diff_regression` (optional) | `experiments/run_diff_regression.py` | `02_differential_regression.ipynb` | OLS vs RidgeCV vs differential polynomial regression | ~30 s | ~3 min |

If the user does not name an experiment, run `twin_network`.

`notebooks/DML_diff_seeds.ipynb` (seed and sample-size sensitivity, authors' TensorFlow code) is
notebook-only and is not run by this skill. If the user asks for it, say so and suggest running the
notebook manually.

### Parameters

All scripts take `--mode {quick,full}` (default `quick`) and `--results-dir` (default `<repo>/results`).
Run `python experiments/<script> --help` for the full list.

- `run_twin_network.py`: `--device {auto,cpu,cuda}`, `--seed` (base seed, default 20261009), `--dtype {float32,float64}`.
  quick = 15 epochs, one training size per task, 1000 test points; full = 100 epochs and the sizes of the notebook.
- `run_diff_regression.py`: `--sections {single,compare,lambda,curve,dimension}`, `--threads` (CPU threads, default 2).
  quick = LIGHT mode of the notebook (10 seeds, 2000 test points, no n = 7 and m = 8000); full = 30 seeds.

## Procedure

1. **Choose the experiment, mode and parameters** from the request. Use `--mode quick` unless the
   user explicitly asks for full or reference results. Map wording such as "on GPU", "only the
   alpha sweep", "base seed 7" to the parameters above; ask only if the request cannot be mapped.
2. **Check the environment** from the repository root:
   `python -c "import dml, torch"` (the regression script needs only `import dml`).
   If it fails, tell the user and install into the active virtual environment:
   `pip install -e ".[torch,notebooks]"`. Never install packages globally.
3. **Before a full run**, tell the user the expected time from the table and run it only if they
   asked for it. On a machine without CUDA, `--device auto` falls back to CPU.
4. **Run** from the repository root, for example
   `python experiments/run_twin_network.py --mode quick`.
   The last log line prints the run folder. Exit code 0 = success, 1 = failure.
5. **Report** from `manifest.json` of the new run folder:
   - experiment, mode (say clearly that quick numbers are only a pipeline check, not reference results), status;
   - total time (`duration_seconds`) and the per-step times (`timings`; for `twin_network` the time of every training is in the `seconds` column of `results.csv`);
   - the key numbers from `summary`;
   - the path of the run folder and the list of `outputs`.
6. **On failure** read `error` in `manifest.json` and the end of `run.log`. Fix only environment
   problems (missing package, no CUDA → offer `--device cpu`) and rerun. Do not change code to make
   a run pass; report the error instead.

## Rules

- Do not edit `src/dml/`, `notebooks/` or the experiment scripts as part of running experiments.
- Do not delete or overwrite earlier runs; every run gets a new folder.
- `results/` is in `.gitignore`: never commit run outputs.
- Always state the mode when quoting numbers; quick and full results are not comparable.
- Both scripts give the same numbers as their notebooks for the same settings and device.

## Output format

```
results/<experiment>/<YYYYmmdd-HHMMSS>_<mode>/
├── manifest.json
├── run.log          console output with timestamps
├── *.csv            metric tables; first column `mode`
└── figures/*.png
```

`manifest.json` fields: `experiment`, `notebook`, `mode`, `mode_note`, `status`
(`running` / `ok` / `failed`), `params` (all script arguments), `command`, `started_at`,
`finished_at`, `duration_seconds`, `git` (`commit`, `branch`, `dirty`), `environment`
(Python, platform, CPU count, package versions, `device`), `timings` (list of `step`, `seconds`
and step details), `summary` (key results), `outputs` (files of the run), `error` (traceback or null).

Metric tables use the columns `rmse_price` and `rmse_delta` (RMSE against exact prices and deltas):

- `twin_network`: `results.csv` (task, train_size, method, rmse_price, rmse_delta, seconds), `gain.csv` (standard / differential RMSE ratio).
- `diff_regression`: `compare_per_seed.csv`, `compare_summary.csv`, `lambda_sensitivity.csv`, `learning_curve.csv`, `dimension.csv`.

## Examples

| Request | Command |
|---|---|
| "Run the main experiment" | `python experiments/run_twin_network.py` |
| "Full twin network run on GPU" | `python experiments/run_twin_network.py --mode full --device cuda` |
| "Rerun the differential regression, only the alpha sweep" | `python experiments/run_diff_regression.py --sections lambda` |
| "Run the main experiment with base seed 7 in float64" | `python experiments/run_twin_network.py --seed 7 --dtype float64` |
| "Check that all experiments still run" | both scripts in quick mode, one after another |