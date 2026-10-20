# Generic regression: Qwen/Qwen3.8-27B-FP8 (A) vs qwen-sft (B)

Paired percentile bootstrap, 10000 resamples over items; 95% CIs. Truncated = wrong.

| metric | n paired | A | B | B − A | A trunc | B trunc | A mean out tok | B mean out tok |
|---|---|---|---|---|---|---|---|---|
| GSM8K accuracy | 100 | 0.960 [0.920, 0.990] | 0.970 [0.930, 1.000] | +0.010 [-0.020, +0.050] | 2 | 2 | 407 | 420 |
| IFEval prompt-strict | 100 | 0.830 [0.750, 0.900] | 0.820 [0.740, 0.890] | -0.010 [-0.080, +0.050] | 7 | 8 | 1201 | 1158 |
| IFEval inst-strict | 100 | 0.857 [0.786, 0.919] | 0.843 [0.769, 0.910] | -0.014 [-0.069, +0.037] | 7 | 8 | 1201 | 1158 |
| MMLU-Pro accuracy | 200 | 0.725 [0.660, 0.785] | 0.750 [0.690, 0.810] | +0.025 [-0.005, +0.060] | 45 | 43 | 1186 | 1178 |

A delta CI that excludes 0 is a detectable change at this sample size; n=100-200 only detects large regressions (roughly 8-12 points).
