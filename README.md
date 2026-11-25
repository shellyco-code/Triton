# Triton

[![CI](https://github.com/shellyco-code/Triton/actions/workflows/ci.yml/badge.svg)](https://github.com/shellyco-code/Triton/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.12-blue)

**An AI on-call agent for Kubernetes.** Triton watches a cluster, detects unhealthy pods,
investigates them with an LLM tool-calling loop (logs, events, pod spec), writes a plain-English
root-cause diagnosis, and proposes a fix. Restarts run only after they pass a set of
**deterministic safety rails**, and by default only after a human approves them.

<!-- Add a demo GIF here: docs/demo.gif (dashboard catching chaos-crashloop end to end) -->

## Why it's interesting

- **Agent loop built from scratch.** It uses the Groq SDK directly, with no LangChain. The loop has an iteration budget, parallel tool calls, tool errors fed back to the model, and output validated with Pydantic.
- **The LLM is treated as untrusted.** Pod logs are attacker-controllable input, so the agent's tools are bound to the pod under investigation and every proposal is re-checked by plain code before anything touches the cluster.
- **Production-minded.** Least-privilege RBAC, a non-root read-only container, a CI pipeline, and 34 tests that run without a cluster or an API key.

## Architecture

```mermaid
flowchart LR
    subgraph Cluster[Kubernetes cluster]
        P[Pods / Events / Logs]
    end
    Poller[Poller<br/>scan + dedup by workload] -->|list pods| P
    Poller --> Agent
    API[FastAPI<br/>/scan /triage] --> Agent
    Agent[Triage agent<br/>LLM tool-calling loop] -->|get_pod_logs<br/>describe_pod<br/>get_pod_events| P
    Agent <-->|chat + tools| LLM[(Groq<br/>Llama 3.3 70B)]
    Agent --> DB[(SQLite<br/>incidents + diagnoses)]
    DB --> Exec[Remediation executor<br/>safety rails]
    Exec -->|delete pod| P
    Dash[Web dashboard] & iOS[iOS companion] -->|GET /incidents<br/>POST /remediate| API
```

| Stage | What happens |
|---|---|
| **Detect** | Every 30s, flag pods with `CrashLoopBackOff`, `ImagePullBackOff`, `OOMKilled`, high restart counts, not-ready, or stuck in `Pending`. Pods are deduplicated by **workload** (e.g. `ReplicaSet/api-7d9f`), so a crash-looping Deployment isn't re-triaged every time it gets a new pod name. |
| **Investigate** | The agent calls tools until it has evidence (default budget: 6 turns), then returns `{diagnosis, remediation_proposal}` as validated JSON. |
| **Decide** | Proposals are either `restart_pod` or `manual_intervention` (bad image, OOM limit, config error). |
| **Act** | Restarts go through the executor, either approved in the UI or automatically when `AUTO_REMEDIATE=true`. |

## Safety rails

The model never acts on the cluster directly. Before a pod is deleted, the executor checks each rail in order. Each skip is recorded with a reason shown in the UI.

1. **Status check**: only `pending_approval` proposals can run. Approvals are idempotent, so double-clicking does nothing.
2. **Supported actions only**: anything other than `restart_pod` becomes `manual_intervention`.
3. **Target pinning**: the target must equal the incident's pod. A prompt-injected "restart payments-db" is rejected.
4. **Protected namespaces**: `kube-system`, `kube-public`, `kube-node-lease` are never touched (the in-cluster deploy adds `triton` itself).
5. **Controller check**: the pod must be owned by a ReplicaSet, StatefulSet or DaemonSet. Deleting a bare pod would destroy it, not restart it.
6. **Rate limit per workload**: at most 2 restarts per 30 minutes per ReplicaSet. Counting by pod name wouldn't work, because Deployment pods are renamed on every restart.
7. **Auth**: `POST /triage` and `/remediate` require a bearer token when `TRITON_API_TOKEN` is set.

Agent tools take **no pod or namespace arguments**. They're closures over the incident pod, so the model can't read other workloads' logs either.

## Quickstart (local, minikube)

```bash
minikube start
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                               # add GROQ_API_KEY
uvicorn app.main:app --reload
```

Open http://localhost:8000. In another terminal, break things:

```bash
python -m app.chaos.break_stuff all       # crashloop + OOM + bad image, in namespace triton-chaos
python -m app.chaos.break_stuff cleanup
```

Within a minute or two the dashboard shows three incidents. The crash loop gets a `restart_pod`
proposal with an **Approve restart** button. The OOM and bad-image incidents are flagged
*Needs a human*, with the fix spelled out.

## Deploy in-cluster

```bash
docker build -t triton:latest .
minikube image load triton:latest
kubectl apply -k deploy/k8s
kubectl -n triton create secret generic triton-secrets \
  --from-literal=GROQ_API_KEY=... --from-literal=TRITON_API_TOKEN=...
kubectl -n triton port-forward svc/triton 8000:80
```

The manifests use a dedicated ServiceAccount whose ClusterRole allows only `pods: get/list/delete`,
`pods/log: get` and `events: list`. The container runs as non-root with a read-only root
filesystem and all capabilities dropped.

## Configuration

All settings are environment variables. See [`app/config.py`](app/config.py) and [`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | – | LLM access (the poller is disabled without it) |
| `AUTO_REMEDIATE` | `false` | Execute approved-by-policy restarts without a human |
| `TRITON_API_TOKEN` | – | Bearer token for mutating endpoints |
| `WATCH_NAMESPACE` | all | Limit scanning to one namespace |
| `POLL_INTERVAL_SECONDS` | `30` | Scan frequency |
| `TRIAGE_COOLDOWN_MINUTES` | `10` | Don't re-triage the same workload within this window |
| `MAX_RESTARTS_PER_WINDOW` / `RESTART_WINDOW_MINUTES` | `2` / `30` | Restart rate limit per workload |
| `PROTECTED_NAMESPACES` | `kube-system,…` | Never remediate here |
| `MAX_AGENT_ITERATIONS` | `6` | Tool-calling budget per incident |

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness |
| `GET` | `/scan?namespace=` | Detection only, no LLM call |
| `POST` | `/triage/{namespace}/{pod}` | Run the agent now (header `X-Groq-Key` optional, for bring-your-own-key) |
| `GET` | `/incidents?limit=&namespace=` | Incident history with diagnosis, trace and outcome |
| `GET` | `/incidents/{id}` | One incident |
| `POST` | `/remediate/{diagnosis_id}` | Human approval, runs the safety rails (`409` if not actionable) |

Interactive docs: http://localhost:8000/docs

## Development

```bash
pytest            # 34 tests, no cluster or API key needed (fake LLM + fake k8s)
ruff check . && ruff format --check .
```

CI runs lint, tests on Python 3.10 and 3.12, a Docker build with a health-check smoke test,
and `kubeconform` validation of the manifests.

```
app/
  agent/triage_agent.py         LLM tool-calling loop, output validation
  agent/remediation_executor.py safety rails + pod restart
  agent/poller.py               background scan → triage → remediate
  k8s/client.py                 detection (pure function) + read-only tools
  services.py                   persistence shared by API and poller
  main.py                       FastAPI app
  static/dashboard.html         live dashboard
  chaos/break_stuff.py          broken Deployments for demos
ios/                            SwiftUI companion app (XcodeGen: cd ios && xcodegen)
deploy/k8s/                     RBAC, Deployment, Service (kustomize)
tests/                          pytest suite
```

## Roadmap

- Agent evaluation harness: replay recorded incidents and score diagnosis accuracy
- More remediations behind the same rails (`rollout undo`, scale) with dry-run diffs
- Prometheus metrics (MTTR, triage latency, token usage) and Slack notifications
- Postgres + Alembic migrations for multi-replica deployments
