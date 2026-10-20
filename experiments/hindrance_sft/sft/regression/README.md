# Capability regression check

`regress.py` scores GSM8K, IFEval and MMLU-Pro (frozen items in `data/`) against an
OpenAI-compatible endpoint; `run_regression.sh` and `run_both.sh` wrap it.

## Client environment

The wrappers expect a virtualenv at `.venv/` in this folder. IFEval scoring needs:

    python3 -m venv .venv
    .venv/bin/pip install 'nltk>=3.9.1' langdetect immutabledict packaging
    NLTK_DATA=nltk_data .venv/bin/python -c "import nltk; nltk.download('punkt_tab', download_dir='nltk_data')"

Versions used for the 2026-10-20 results: nltk 3.10.3, langdetect 1.0.9,
immutabledict 4.3.1. `regress.py` sets `NLTK_DATA` to `./nltk_data` by default; the
downloaded data is not committed. Before sending any request, `regress.py` imports the
IFEval checker and scores one trivial response, and exits with an error if that fails.

## Vendored IFEval checker

`ifeval_lm_eval/` is the IFEval checker from EleutherAI lm-evaluation-harness 0.4.13
(`lm_eval/tasks/ifeval/`, MIT license, see `ifeval_lm_eval/LICENSE.md`), with imports
made relative and otherwise unchanged. The instruction files carry their original
Google Research Apache 2.0 headers.
