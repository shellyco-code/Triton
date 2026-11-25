# Contributing to Triton

Thanks for your interest! Bug reports, docs fixes, new failure scenarios and code are all welcome.

## Ground rules

- **Safety first.** Anything that mutates a cluster goes through `app/agent/remediation_executor.py`
  and needs tests covering the rails it touches. PRs that let the LLM act directly will not be merged.
- **The LLM is untrusted.** Treat model output and pod logs as data, never as instructions.
- Keep PRs small and focused. Open an issue first for anything large.

## Development setup

```bash
git clone https://github.com/shellyco-code/Triton.git && cd Triton
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
pre-commit install                                  # optional: lint on commit
```

| Task | Command |
|---|---|
| Run tests (no cluster / API key needed) | `pytest` |
| Lint + format | `ruff check . && ruff format .` |
| Run the API | `uvicorn app.main:app --reload` |
| UI work without a cluster | `DATABASE_URL=sqlite:///./demo.db python -m scripts.seed_demo_data` then run the API with the same `DATABASE_URL` and `ENABLE_POLLER=false` |
| Agent evals (needs `GROQ_API_KEY`) | `python -m evals.run --trials 3` |
| Real failures on a local cluster (kind or minikube) | `python -m app.chaos.break_stuff all` |

## Good first contributions

- **New eval scenario**: add a `Scenario` to `evals/scenarios.py` (recorded events/logs + expected action).
  Every new failure mode we can score makes the agent measurably better.
- **New detection rule**: extend `detect_issues` in `app/k8s/client.py` with a unit test in `tests/test_detection.py`.
- **New chaos scenario** in `app/chaos/break_stuff.py`.

## Pull requests

1. Fork and branch from `main`.
2. Add or update tests; `pytest` and `ruff check .` must pass (CI runs both).
3. If you change agent behaviour (prompt, tools, parsing), include `python -m evals.run` output in the PR.
4. Describe *why* in the PR, not just what.

By contributing you agree that your contributions are licensed under the MIT License,
and to follow our [Code of Conduct](CODE_OF_CONDUCT.md).
