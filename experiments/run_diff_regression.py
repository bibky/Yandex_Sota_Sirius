"""Differential regression (paper Appx 3): OLS vs RidgeCV vs differential polynomial regression.

Script version of notebooks/02_differential_regression.ipynb. The experiment itself is the same
as in the notebook; this script only adds command-line parameters and logging to
results/diff_regression/<timestamp>_<mode>/.

Sections (all by default):
    single     one seed, predicted vs exact price (Black–Scholes and Bachelier n=3)
    compare    RMSE of all methods over many seeds (Black–Scholes and Bachelier n=3)
    lambda     sensitivity to the regularization strength alpha
    curve      learning curve over the training set size
    dimension  growth of the basket dimension n

Mode quick = LIGHT=True of the notebook, full = LIGHT=False.

Examples (from the repository root):
    python experiments/run_diff_regression.py                       # quick mode
    python experiments/run_diff_regression.py --mode full --threads 4
    python experiments/run_diff_regression.py --sections compare lambda
"""

import argparse
import os
import sys

from runlog import RunLogger, run_main

NOTEBOOK = "notebooks/02_differential_regression.ipynb"
SECTIONS = ["single", "compare", "lambda", "curve", "dimension"]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["quick", "full"], default="quick",
                   help="quick = LIGHT mode of the notebook (fewer seeds, smaller test set, no n=7, no m=8000)")
    p.add_argument("--threads", type=int, default=2,
                   help="CPU threads for numpy/sklearn (fewer = cooler machine, slower run)")
    p.add_argument("--sections", nargs="+", choices=SECTIONS, default=SECTIONS)
    p.add_argument("--results-dir", default=None, help="default: <repo>/results")
    return p.parse_args()


def main(run, args):
    import warnings
    warnings.filterwarnings("ignore")
    from math import comb

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    from dml.metrics import evaluate_regressors
    from dml.models.regression import (DifferentialRegression, PolynomialRidge, PolynomialRidgeCV,
                                       make_polynomial)
    from dml.plotting import plot_methods
    from dml.simulators import BachelierBasket, BlackScholesCall, grid, uniform

    # ---------------------------------------------------------------- settings (as in the notebook)
    LIGHT = args.mode == "quick"
    DEGREE = 5
    SEEDS = list(range(10 if LIGHT else 30))
    SEEDS_SWEEP = SEEDS[:10] if LIGHT else SEEDS[:20]
    SEEDS_DIM = SEEDS[:5] if LIGHT else SEEDS[:10]
    N_TEST = 2000 if LIGHT else 5000
    SIZES = [250, 500, 1000, 2000, 4000] + ([] if LIGHT else [8000])
    DIMS = [1, 2, 3, 5] + ([] if LIGHT else [7])
    run.log(f"seeds: compare={len(SEEDS)}, lambda/curve={len(SEEDS_SWEEP)}, dimension={len(SEEDS_DIM)}; "
            f"n_test={N_TEST}; sizes={SIZES}; dims={DIMS}; threads={args.threads}")

    def bs_data(seed, m=200):
        rng = np.random.default_rng(seed)
        opt = BlackScholesCall(K=110, vol=0.2, T=2)
        x = grid(10, 200, m)
        y, z = opt.sample_payoffs(x, rng)
        xt = grid(10, 200, N_TEST)
        return opt, x, y, z, xt

    def bach_data(seed, n=3, m=1000):
        rng = np.random.default_rng(seed)
        opt = BachelierBasket.random(n, rng, basket_vol=20, K=110, T=3)
        x = uniform(10, 200, m, n, rng)
        y, z = opt.sample_payoffs(x, rng)
        xt = uniform(10, 200, N_TEST, n, rng)
        return opt, x, y, z, xt

    def run_one(data_fn, methods, seed, **kw):
        opt, x, y, z, xt = data_fn(seed, **kw)
        return evaluate_regressors(methods, x, y, z, xt, opt.price(xt), opt.delta(xt))

    METHODS = {
        "OLS": lambda: make_polynomial(DEGREE),
        "RidgeCV": lambda: PolynomialRidgeCV(DEGREE),
        "Differential": lambda: DifferentialRegression(DEGREE),
    }

    def fit_all(x, y, z, xt):
        preds = {}
        for name, make in METHODS.items():
            m = make()
            m.fit(x, y, z) if name == "Differential" else m.fit(x, y)
            preds[name] = m.predict(xt)
            if name == "RidgeCV":
                run.log(f"RidgeCV: chosen alpha = {m.alpha_:.4f}")
        return preds

    def to_long(results_by_key, methods, key_name, keys):
        """{key: {method: (price, delta)}} -> long table."""
        return pd.DataFrame([{key_name: k, "method": meth,
                              "rmse_price": results_by_key[k][meth][0],
                              "rmse_delta": results_by_key[k][meth][1]}
                             for k in keys for meth in methods])

    sections = set(args.sections)
    summary = {}

    # 1. single seed
    if "single" in sections:
        with run.timed("single: Black–Scholes, seed 0"):
            opt, x, y, z, xt = bs_data(seed=0)
            fig = plot_methods(xt, opt.price(xt), fit_all(x, y, z, xt), samples=(x, y),
                               xlim=(0, 225), ylim=(-20, 100))
            run.save_figure(fig, "bs_single_seed")
        with run.timed("single: Bachelier n=3, seed 0"):
            opt, x, y, z, xt = bach_data(seed=0)
            fig = plot_methods(opt.basket(xt), opt.price(xt), fit_all(x, y, z, xt),
                               samples=(opt.basket(x), y), xlim=(0, 225), ylim=(-20, 100))
            run.save_figure(fig, "bachelier3_single_seed")

    # 2. methods over seeds
    if "compare" in sections:
        METHODS_EXT = {
            **METHODS,
            "OLS raw": lambda: make_polynomial(DEGREE, scale=False),
            "RidgeCV raw": lambda: PolynomialRidgeCV(DEGREE, scale=False),
            "Differential std": lambda: DifferentialRegression(DEGREE, standardize=True),
        }
        per_seed = []
        for dataset, data_fn in [("Black–Scholes", bs_data), ("Bachelier n=3", bach_data)]:
            with run.timed(f"compare: {dataset}", seeds=len(SEEDS)):
                for s in SEEDS:
                    r = run_one(data_fn, METHODS_EXT, s)
                    per_seed += [{"dataset": dataset, "seed": s, "method": k,
                                  "rmse_price": v[0], "rmse_delta": v[1]} for k, v in r.items()]
        per_seed = pd.DataFrame(per_seed)
        # same statistic as the notebook (numpy std, ddof=0)
        table = per_seed.groupby(["dataset", "method"], sort=False).agg(
            rmse_price_mean=("rmse_price", "mean"),
            rmse_price_std=("rmse_price", lambda v: float(np.std(v))),
            rmse_delta_mean=("rmse_delta", "mean"),
            rmse_delta_std=("rmse_delta", lambda v: float(np.std(v)))).reset_index()
        run.log("Methods over seeds (mean ± std):\n" + table.round(4).to_string(index=False))
        run.save_table(per_seed, "compare_per_seed")
        run.save_table(table, "compare_summary")
        summary["compare"] = {f"{r.dataset} | {r.method}": {"rmse_price": round(r.rmse_price_mean, 4),
                                                            "rmse_delta": round(r.rmse_delta_mean, 4)}
                              for r in table.itertuples() if r.method in METHODS}

    # 3. sensitivity to alpha
    if "lambda" in sections:
        alphas_diff = [1e-3, 1e-2, 1e-1, 1, 10, 100, 1000]
        alphas_ridge = [1e-4, 1e-3, 1e-2, 1e-1, 1, 10]
        sweep = {**{("Differential", a): (lambda a=a: DifferentialRegression(DEGREE, alpha=a)) for a in alphas_diff},
                 **{("Ridge", a): (lambda a=a: PolynomialRidge(DEGREE, alpha=a)) for a in alphas_ridge}}
        with run.timed("lambda: Bachelier n=3", seeds=len(SEEDS_SWEEP)):
            res = [run_one(bach_data, sweep, s) for s in SEEDS_SWEEP]
        lam = pd.DataFrame([{"method": k[0], "alpha": k[1],
                             "rmse_price": np.mean([r[k] for r in res], axis=0)[0],
                             "rmse_delta": np.mean([r[k] for r in res], axis=0)[1]} for k in sweep])
        run.log("Sensitivity to alpha (mean over seeds):\n" + lam.round(4).to_string(index=False))
        run.save_table(lam, "lambda_sensitivity")

        fig, axs = plt.subplots(1, 2, figsize=(11, 4))
        for ax, col, title in zip(axs, ["rmse_price", "rmse_delta"], ["Price RMSE", "Delta RMSE"]):
            for meth, mk in [("Differential", "o-"), ("Ridge", "s--")]:
                d = lam[lam.method == meth]
                ax.plot(d.alpha, d[col], mk, label=meth)
            ax.set_xscale("log"); ax.set_xlabel("alpha"); ax.set_title(title); ax.legend()
        fig.tight_layout()
        run.save_figure(fig, "lambda_sensitivity")

    # 4. learning curve
    if "curve" in sections:
        curve = {}
        for m in SIZES:
            with run.timed(f"curve: m={m}", seeds=len(SEEDS_SWEEP)):
                res = [run_one(bach_data, METHODS, s, m=m) for s in SEEDS_SWEEP]
            curve[m] = {k: np.mean([r[k] for r in res], axis=0) for k in METHODS}
        curve_df = to_long(curve, METHODS, "train_size", SIZES)
        run.log("Learning curve (mean over seeds):\n" + curve_df.round(4).to_string(index=False))
        run.save_table(curve_df, "learning_curve")

        fig, axs = plt.subplots(1, 2, figsize=(11, 4))
        for ax, col, title in zip(axs, ["rmse_price", "rmse_delta"], ["Price RMSE", "Delta RMSE"]):
            for k in METHODS:
                d = curve_df[curve_df.method == k]
                ax.plot(d.train_size, d[col], "o-", label=k)
            ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlabel("training set size m")
            ax.set_title(title); ax.legend()
            ax.set_xticks(SIZES, [str(m) for m in SIZES]); ax.minorticks_off()
        fig.tight_layout()
        run.save_figure(fig, "learning_curve")

    # 5. dimension
    if "dimension" in sections:
        dim_res = {}
        for n in DIMS:
            with run.timed(f"dimension: n={n}", seeds=len(SEEDS_DIM)):
                res = [run_one(bach_data, METHODS, s, n=n) for s in SEEDS_DIM]
            dim_res[n] = {k: np.mean([r[k] for r in res], axis=0) for k in METHODS}
        dim_df = to_long(dim_res, METHODS, "n", DIMS)
        dim_df.insert(1, "n_monomials", [comb(n + DEGREE, DEGREE) for n in dim_df["n"]])
        run.log("Dimension (mean over seeds):\n" + dim_df.round(4).to_string(index=False))
        run.save_table(dim_df, "dimension")

        n_plot = max(DIMS)
        with run.timed(f"dimension: single seed plot n={n_plot}"):
            opt, x, y, z, xt = bach_data(seed=0, n=n_plot)
            fig = plot_methods(opt.basket(xt), opt.price(xt), fit_all(x, y, z, xt),
                               xlim=(0, 225), ylim=(-20, 100))
            run.save_figure(fig, f"bachelier{n_plot}_single_seed")

    run.add_summary(**summary, sections=sorted(sections))


if __name__ == "__main__":
    args = parse_args()
    # thread limits must be set before numpy is imported
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = str(args.threads)
    run_main(lambda run: main(run, args),
             lambda: RunLogger("diff_regression", args.mode, vars(args), NOTEBOOK, args.results_dir))
    sys.exit(0)
