# Fleet Triage Agent

An AI agent that watches a Kubernetes cluster, detects unhealthy pods,
investigates root cause using tool-calling (Anthropic SDK, no framework),
and produces a plain-English diagnosis + fix recommendation.

## Setup

1. Start minikube:
   ```
   minikube start
   ```

2. Install dependencies:
   ```
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Set your API key:
   ```
   echo "GROQ_API_KEY=your_key_here" > .env
   ```
   *(Note: You can also skip setting a global `.env` and pass your own key directly via the dashboard UI, or via the `X-Groq-Key` header on API requests for Bring-Your-Own-Key support).*

4. Run the API:
   ```
   uvicorn app.main:app --reload
   ```

## Demo flow

1. Open the live dashboard in your browser:
   http://localhost:8000/dashboard

2. Break something on purpose (in a new terminal):
   ```
   python app/chaos/break_stuff.py crashloop
   ```

3. Watch the background poller automatically detect it, investigate it, and execute a restart! (Check the backend server logs or refresh the dashboard to see the magic happen live).

4. See raw JSON incident history (optional):
   ```
   curl http://localhost:8000/incidents
   ```

## What's built vs. what's next

**Built:**
- K8s client wrapper (`app/k8s/client.py`) - detection + log/event/describe tools
- Agent loop (`app/agent/triage_agent.py`) - tool-calling loop from scratch
- FastAPI + SQLite storage (`app/main.py`, `app/db/models.py`)
- Chaos scripts to generate real failures for demoing
- Background polling loop (`app/agent/poller.py`)
- Auto-remediation with safety rate-limits (`app/agent/remediation_executor.py`)
- Frontend dashboard to visualize incidents and remediation actions (`app/static/dashboard.html`)
- Multi-namespace support (watches all namespaces by default)

**Not yet built (next steps):**
- Multi-cluster support (monitoring multiple kubeconfigs)
