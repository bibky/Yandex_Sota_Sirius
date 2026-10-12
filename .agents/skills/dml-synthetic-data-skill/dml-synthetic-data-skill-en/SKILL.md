---
name: dml-synthetic-data
description: "Generate synthetic training and test sets (x, y, dy/dx) for Differential Machine Learning following Huge & Savine (2020). Covers a Black–Scholes call and a Bachelier basket."
---

# Synthetic Data for Differential Machine Learning

Instructions for generating datasets to reproduce B. Huge, A. Savine, "Differential Machine Learning" (arXiv:2005.02347). The output is a training set of triples (input, payoff, pathwise derivatives) and a test set with exact prices and deltas.

## When to use

- you need to reproduce the experiments from the paper or compare a standard network with a twin network;
- you need a dataset "market state → payoff + slopes" for any model and payoff in this setup.

## What to clarify before generating

If the user has not specified these, ask, or take the defaults from the "Reference problems" section and state explicitly that you did:

1. problem: Black–Scholes call, Bachelier basket, or a custom one;
2. mode: single-path payoffs (main) or exact prices;
3. sizes of the training sets and the test set;
4. model and contract parameters;
5. random seed and file format.

## Two modes from the paper

| Mode | Label $y$ | Label $z = \partial y / \partial x$ | Cost |
|---|---|---|---|
| payoffs (main, LSM-style) | payoff on a single path | pathwise derivative of the payoff | the whole set costs one Monte Carlo valuation |
| exact prices | price computed numerically | Greeks | one full pricing run per example |

The main mode is described below. Exact prices are used for the test set.

## How one example is built (payoff mode)

1. Choose the input $x^{(i)}$: the market state at the horizon date $T_1$.
2. From $x^{(i)}$, simulate **one** path to the payoff date $T_2$ under the risk-neutral measure.
3. Compute the payoff $y^{(i)}$ on this path.
4. On the **same** path, with the same random numbers, compute $z^{(i)}_j = \partial y^{(i)} / \partial x^{(i)}_j$ for all $j$.

This gives one row: $x^{(i)} \in \mathbb{R}^n$, $y^{(i)} \in \mathbb{R}$, $z^{(i)} \in \mathbb{R}^n$.

## Mandatory rules

- **Measure.** The segment $T_1 \to T_2$ is simulated strictly in the pricing model (measure $\mathbb{Q}$). Otherwise $y$ and $z$ are biased.
- **The input distribution is free.** It only determines the region where the approximation will be accurate. Acceptable choices: simulation from 0 to $T_1$ with inflated volatility, a uniform grid, a Sobol sequence.
- **One path per example.** Averaging an antithetic pair ($N$ and $-N$) is allowed: the authors' notebooks do this. Average $y$ and $z$ over the same pair.
- **Pathwise derivatives.** Compute them analytically with the chain rule or with AAD (JAX, PyTorch, TensorFlow). Finite differences are acceptable only as a check.
- **Continuous payoff.** For digital and barrier payoffs the pathwise derivative is biased. Such payoffs must be smoothed (as the authors do); otherwise warn the user.
- **No normalization.** Store raw values. Normalization belongs to training.
- **Reproducibility.** Fix the seed and store all parameters together with the data.

## Reference problems

The "default" values below were chosen for convenience. Where a value comes from the paper, this is stated.

### A. European call, Black–Scholes, one asset

Default parameters: $S_0 = 100$, $K = 110$, $\sigma = 0.2$, $T_1 = 1$, $T_2 = 2$, zero rate, volatility multiplier for inputs 1.5.

- Input: $S_{T_1} = S_0 \exp\left(-\tfrac12 \sigma_1^2 T_1 + \sigma_1 \sqrt{T_1}\, N_1\right)$, where $\sigma_1 = 1.5\,\sigma$.
- Path: $S_{T_2} = S_{T_1} \exp\left(-\tfrac12 \sigma^2 \Delta t + \sigma \sqrt{\Delta t}\, N_2\right)$, $\Delta t = T_2 - T_1$.
- Payoff: $y = \max(S_{T_2} - K,\ 0)$.
- Derivative: $z = \mathbb{1}\{S_{T_2} > K\}\, S_{T_2} / S_{T_1}$.
- Reference: the Black–Scholes formula with maturity $\Delta t$, delta $N(d_1)$.

### B. Basket, Bachelier, $n$ correlated assets

In the paper $n = 7$, training on 1,024 and 65,536 paths, testing on 1,024 scenarios. The remaining parameters are defaults: $S_{0,j} = 100$, weights $a_j = 1/n$, normal volatilities $\sigma_j = 20$, pairwise correlation $\rho = 0.5$, $K = 100$, $T_1 = 1$, $T_2 = 2$.

- $L$ is the Cholesky factor of the correlation matrix, $N \sim \mathcal N(0, I_n)$.
- Input: $S_{T_1} = S_0 + \sigma \circ (L N_1)\sqrt{T_1}$, optionally with a volatility multiplier.
- Path: $S_{T_2} = S_{T_1} + \sigma \circ (L N_2)\sqrt{\Delta t}$.
- Basket: $b = a^\top S_{T_2}$. Payoff: $y = \max(b - K,\ 0)$.
- Derivatives: $z_j = \mathbb{1}\{b > K\}\, a_j$.
- Reference: the basket is normal under Bachelier. Let $B = a^\top S_{T_1}$, $\sigma_b^2 = \sum_{j,k} a_j a_k \sigma_j \sigma_k \rho_{jk}$, $s = \sigma_b \sqrt{\Delta t}$, $d = (B - K)/s$. Then price $= (B - K)\Phi(d) + s\,\varphi(d)$, delta with respect to asset $j$ $= a_j\,\Phi(d)$.

## Test set

- Inputs from the same distribution as the training inputs, with a different seed.
- Labels are exact prices and deltas from the reference formulas. If there is no formula, use nested Monte Carlo: at least $10^5$ paths per point, with the standard error reported.
- Default size: 1,024 points.

## Output format

A folder of `.parquet` files per training-set size:

| Array | Shape | Contents |
|---|---|---|
| `x_train` | $m \times n$ | inputs |
| `y_train` | $m \times 1$ | payoffs |
| `z_train` | $m \times n$ | pathwise derivatives |
| `x_test` | $m_{test} \times n$ | test inputs |
| `y_test`, `z_test` | | exact prices and deltas |

Alongside it, a `meta.json`: problem, model, all parameters, seed, number of paths, antithetic yes/no, method used for derivatives, date.

Default training-set sizes: powers of two from $2^{10}$ to $2^{16}$.

## Checks before delivery

1. **Unbiasedness.** For 3–5 fixed inputs, generate $10^5$ paths each: the mean of $y$ matches the reference price and the mean of $z$ matches the reference delta within three standard errors.
2. **Derivatives.** On 100 rows, compare $z$ with a finite difference using the same random numbers. The discrepancy is at the level of rounding error.
3. **Structure.** No NaNs or infinities. Where $y = 0$ (out of the money), $z = 0$. The share of in-the-money paths is given in the report.
4. **Reproducibility.** A rerun with the same seed produces bit-identical arrays.
5. **Coverage.** The histogram of inputs covers the region where the test set lies.

## What not to do

- do not simulate the segment $T_1 \to T_2$ under the real-world measure;
- do not take $y$ and $z$ from different paths;
- do not average many paths per example unless explicitly asked (this is a different, more expensive mode);
- do not train a model or normalize the data as part of this task;
- do not invent parameters from the paper: if a value is not in the text, call it a chosen default.

## Source

B. Huge, A. Savine, "Differential Machine Learning", 2020: https://arxiv.org/abs/2005.02347. Authors' code: https://github.com/differential-machine-learning/notebooks
