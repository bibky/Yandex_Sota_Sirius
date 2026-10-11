"""Main experiment: standard vs differential (twin) network on Black–Scholes and Bachelier baskets.

Script version of notebooks/DifferentialML_PyTorch.ipynb. The experiment itself (data, seeds,
architecture, training, evaluation) is the same as in the notebook; this script only adds
command-line parameters and logging to results/twin_network/<timestamp>_<mode>/.

Examples (from the repository root):
    python experiments/run_twin_network.py                      # quick mode, auto device
    python experiments/run_twin_network.py --mode full --device cuda
"""

import argparse
import os
import sys

from runlog import RunLogger, run_main

NOTEBOOK = "notebooks/DifferentialML_PyTorch.ipynb"

# fixed in the notebook
HIDDEN_UNITS = 20
HIDDEN_LAYERS = 4
LAM = 1.0

SIZES = {
    "quick": {
        "Black–Scholes": [1024],
        "Bachelier d=1": [1024],
        "Bachelier d=7": [4096],
        "Bachelier d=50": [4096],
    },
    "full": {
        "Black–Scholes": [1024, 8192],
        "Bachelier d=1": [1024, 8192],
        "Bachelier d=7": [4096, 8192, 16384],
        "Bachelier d=50": [16384, 65536, 131072],
    },
}
N_TEST = {"quick": 1000, "full": 4096}
EPOCHS = {"quick": 15, "full": 100}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["quick", "full"], default="quick",
                   help="quick: 15 epochs, one size per task; full: 100 epochs, sizes of the notebook")
    p.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    p.add_argument("--seed", type=int, default=20261009, help="base seed (all other seeds derive from it)")
    p.add_argument("--dtype", choices=["float32", "float64"], default="float32")
    p.add_argument("--results-dir", default=None, help="default: <repo>/results")
    p.add_argument("--progress", action="store_true", help="show tqdm progress bars")
    return p.parse_args()


def main(run, args):
    import random
    import time

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import torch

    from dml.models.twin_network import Neural_Approximator
    from dml.simulators.lsm import Bachelier, BlackScholes

    # settings (as in the notebook)
    RUN_MODE, SEED, DTYPE = args.mode, args.seed, args.dtype
    DEVICE_NAME = args.device
    N_TEST_RUN, EPOCHS_RUN, SIZES_RUN = N_TEST[RUN_MODE], EPOCHS[RUN_MODE], SIZES[RUN_MODE]

    if DEVICE_NAME == "auto":
        DEVICE_NAME = "cuda" if torch.cuda.is_available() else "cpu"
    if DEVICE_NAME == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available. Use --device cpu or run on a GPU machine.")
    device = torch.device(DEVICE_NAME)
    real_type = torch.float32 if DTYPE == "float32" else torch.float64
    np.random.seed(SEED)
    random.seed(SEED)
    torch.manual_seed(SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(SEED)

    run.set_info("device", str(device))
    if device.type == "cuda":
        run.set_info("gpu", torch.cuda.get_device_name(device))
    run.log(f"PyTorch {torch.__version__}; device={device}; dtype={DTYPE}; mode={RUN_MODE}; "
            f"epochs={EPOCHS_RUN}; n_test={N_TEST_RUN}")

    # experiment (as in the notebook)
    def evaluate_task(task, sizes, task_index):
        gen = BlackScholes() if task == "Black–Scholes" else Bachelier(int(task.split('=')[1]))
        # separate deterministic random stream for every task
        x, y, z = gen.trainingSet(max(sizes), anti=True, seed=SEED + 101 * task_index)
        xt, _, yt, zt, _ = gen.testSet(num=N_TEST_RUN, seed=SEED + 1000 + 101 * task_index)
        rows = []
        for m in sizes:
            for method in ("standard", "differential"):
                approximator = Neural_Approximator(x, y, z, device=device, dtype=real_type)
                approximator.prepare(m, differential=(method == "differential"),
                                     lam=LAM, hidden_units=HIDDEN_UNITS,
                                     hidden_layers=HIDDEN_LAYERS,
                                     weight_seed=SEED + 10_000 + task_index * 100 + m)
                start = time.perf_counter()
                approximator.train(f"{task} | N={m} | {method}", epochs=EPOCHS_RUN)
                if device.type == "cuda":
                    torch.cuda.synchronize()
                seconds = time.perf_counter() - start
                yp, zp = approximator.predict_values_and_derivs(xt)
                price_rmse = float(np.sqrt(np.mean((yp - yt) ** 2)))
                delta_rmse = float(np.sqrt(np.mean((zp - zt) ** 2)))
                rows.append({"task": task, "train_size": m, "method": method,
                             "rmse_price": price_rmse, "rmse_delta": delta_rmse,
                             "seconds": seconds})
                run.log(f"{task:16} N={m:6} {method:12} price={price_rmse:.6g} "
                        f"delta={delta_rmse:.6g} time={seconds:.1f}s")
        return rows

    results = []
    for i, (task, sizes) in enumerate(SIZES_RUN.items()):
        with run.timed(f"task: {task}", sizes=sizes):
            results.extend(evaluate_task(task, sizes, i))
    results_df = pd.DataFrame(results)
    run.save_table(results_df, "results")

    # summary and plot (as in the notebook)
    price = results_df.pivot(index=["task", "train_size"], columns="method", values="rmse_price")
    delta = results_df.pivot(index=["task", "train_size"], columns="method", values="rmse_delta")
    gain = pd.DataFrame({"price_gain_x": price["standard"] / price["differential"],
                         "delta_gain_x": delta["standard"] / delta["differential"]})
    run.log("Gain of differential over standard (RMSE standard / RMSE differential):\n"
            + gain.round(3).to_string())
    run.save_table(gain.reset_index(), "gain")

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    for task in SIZES_RUN:
        sub = gain.loc[task]
        axes[0].plot(sub.index, sub["price_gain_x"], marker="o", label=task)
        axes[1].plot(sub.index, sub["delta_gain_x"], marker="o", label=task)
    for ax, label in zip(axes, ["Price RMSE: standard / differential", "Delta RMSE: standard / differential"]):
        ax.set_xscale("log", base=2)
        ax.axhline(1, linestyle="--", linewidth=1)
        ax.set_xlabel("Training set size")
        ax.set_ylabel("Gain, x")
        ax.set_title(label)
        ax.grid(alpha=0.3)
    axes[1].legend()
    fig.tight_layout()
    run.save_figure(fig, "gain")

    # largest training size of every task
    largest = gain.groupby(level="task").tail(1).round(3)
    run.add_summary(gain_at_largest_size={f"{t} (N={n})": row.to_dict() for (t, n), row in largest.iterrows()},
                    total_training_seconds=round(float(results_df["seconds"].sum()), 1))


if __name__ == "__main__":
    args = parse_args()
    if not args.progress:
        os.environ.setdefault("TQDM_DISABLE", "1")
    run_main(lambda run: main(run, args),
             lambda: RunLogger("twin_network", args.mode, vars(args), NOTEBOOK, args.results_dir))
    sys.exit(0)
