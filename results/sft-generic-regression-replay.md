# Generic regression: Qwen/Qwen3.8-27B-FP8 (A) vs qwen-sft-replay (B)

Paired percentile bootstrap, 10000 resamples over items; 95% CIs. Truncated = wrong.

| metric | n paired | A | B | B − A | A trunc | B trunc | A mean out tok | B mean out tok |
|---|---|---|---|---|---|---|---|---|
| GSM8K accuracy | 100 | 0.960 [0.920, 0.990] | 0.970 [0.930, 1.000] | +0.010 [+0.000, +0.030] | 2 | 2 | 407 | 395 |
| IFEval prompt-strict | 100 | 0.830 [0.750, 0.900] | 0.840 [0.770, 0.910] | +0.010 [-0.060, +0.070] | 7 | 6 | 1201 | 1199 |
| IFEval inst-strict | 100 | 0.857 [0.786, 0.919] | 0.857 [0.786, 0.920] | +0.000 [-0.061, +0.058] | 7 | 6 | 1201 | 1199 |
| MMLU-Pro accuracy | 200 | 0.725 [0.660, 0.785] | 0.745 [0.685, 0.805] | +0.020 [-0.010, +0.050] | 45 | 44 | 1186 | 1165 |

A delta CI that excludes 0 is a detectable change at this sample size; n=100-200 only detects large regressions (roughly 8-12 points).
