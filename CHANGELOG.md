# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-11-25

### Added
- Agent evaluation harness (`evals/`) with six recorded scenarios, including a prompt-injection attack, and a manual GitHub Actions workflow.
- Prometheus metrics at `/metrics`; `/status` and `/stats` endpoints.
- Per-diagnosis triage latency, token usage and model.
- Slack-compatible webhook notifications (`NOTIFY_WEBHOOK_URL`).
- Redesigned dashboard: status bar, summary tiles, filters, investigation timeline, light/dark themes, mobile layout.
- Sample-data seeder for UI development; contributor docs, issue/PR templates, Dependabot, pre-commit.

## [1.0.0] - 2026-11-25

### Fixed
- Auto-remediation crashed on every restart (missing `Diagnosis.incident` relationship).
- `/remediate` reported success when nothing ran.
- Agent loop had no iteration limit and crashed on tool errors.
- Poller blocked the event loop; timestamps lost their timezone.

### Added
- Safety rails: tools scoped to the incident pod, target pinning, protected namespaces, controller check, per-workload rate limit, opt-in auto-remediation, API token.
- Test suite (fake LLM + fake cluster), ruff, GitHub Actions CI.
- Dockerfile, least-privilege Kubernetes manifests.
- iOS companion app made buildable (XcodeGen).
