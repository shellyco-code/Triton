# Changelog

Notable changes. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.0] - 2026-11-25

### Fixed
- Auto-remediation crashed on every restart (`Diagnosis` had no relationship to `Incident`).
- `/remediate` reported success even when nothing ran.
- The agent loop had no turn limit and crashed on tool errors.
- The poller blocked the event loop; timestamps lost their timezone in SQLite.

### Added
- Safety rails: tools scoped to the incident pod, target pinning, protected namespaces,
  controller check, per-workload restart rate limit, opt-in auto-remediation, API token.
- Eval harness with six recorded scenarios, including a prompt-injection case.
- Prometheus metrics, `/status` and `/stats`, per-incident latency and token usage, webhook alerts.
- New dashboard (status bar, filters, investigation timeline, dark mode, mobile layout).
- Test suite, CI, Dockerfile, Kubernetes manifests with least-privilege RBAC.
- iOS companion app is buildable (XcodeGen project).

## [1.0.0]

First version: detection, Groq tool-calling agent, SQLite history, dashboard, chaos scripts.
