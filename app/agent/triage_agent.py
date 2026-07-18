"""
The core agent loop. This is the most important file in the project -
it's the part that proves you understand tool-calling from first principles
rather than relying on a framework to hide it from you.

Flow:
  1. Give Groq a system prompt + the unhealthy pod info + a set of tools
  2. Groq decides which tool(s) to call to investigate
  3. We execute the tool, feed the result back
  4. Repeat until Groq stops calling tools and gives a final diagnosis
"""

import json
from groq import Groq
import groq
from app.k8s.client import get_pod_logs, describe_pod, get_pod_events

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You are a Kubernetes SRE triage agent. You are given a pod that
looks unhealthy. Investigate using the tools available to you, then produce a final diagnosis in JSON format.
Your final response MUST be a valid JSON object containing exactly two keys:
1. "diagnosis": A string (under 150 words) with root cause, evidence, recommended action, and confidence.
2. "remediation_proposal": An object with "action" (e.g. "restart_pod" or "manual_intervention"), "target" (the pod name), and "reason" (why this action is recommended).

Call tools as needed before answering. Don't guess without evidence - pull
logs and events first. Keep the final diagnosis concise."""

# Tool definitions - this is the schema Groq uses to decide what to call
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_pod_logs",
            "description": "Fetch recent log lines from a pod's container. Best first step for crash/error diagnosis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pod_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"},
                },
                "required": ["pod_name"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "describe_pod",
            "description": "Get structured pod detail: node, containers, resource limits, conditions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pod_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"},
                },
                "required": ["pod_name"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pod_events",
            "description": "Get Kubernetes events for a pod - often shows the clearest signal like OOMKilled or FailedScheduling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pod_name": {"type": "string"},
                    "namespace": {"type": "string", "default": "default"},
                },
                "required": ["pod_name"],
            }
        }
    },
]

# Maps tool names to the actual Python functions that execute them
TOOL_FUNCTIONS = {
    "get_pod_logs": get_pod_logs,
    "describe_pod": describe_pod,
    "get_pod_events": get_pod_events,
}


def run_tool(tool_name: str, tool_input: dict):
    """Executes the actual function a tool_use block refers to."""
    fn = TOOL_FUNCTIONS[tool_name]
    result = fn(**tool_input)
    # Tool results must be strings for the API - serialize dicts/lists
    if isinstance(result, (dict, list)):
        return json.dumps(result)
    return str(result)


def triage_pod(pod_summary: dict, api_key: str | None = None) -> dict:
    """
    Main entry point. Takes an unhealthy pod summary (from list_unhealthy_pods)
    and runs the full investigate -> diagnose loop.

    Returns a dict with the diagnosis text and the tool-call trace
    (useful for the dashboard to show "how the agent got there").
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Investigate this unhealthy pod and diagnose it:\n\n{json.dumps(pod_summary, indent=2)}",
        }
    ]

    trace = []  # record every tool call for transparency/debugging

    try:
        # Create client per-request
        client = Groq(api_key=api_key) if api_key else Groq()
    except Exception as e:
        # e.g., if neither api_key nor GROQ_API_KEY environment variable is set
        raise groq.AuthenticationError("No Groq API key found.")

    while True:
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=1024,
            )
        except groq.AuthenticationError as auth_err:
            raise auth_err
        
        response_message = response.choices[0].message

        # Groq either wants to call tools, or is done and gave a final answer
        if response_message.tool_calls:
            # Append Groq's turn (which includes the tool calls) to history
            messages.append(response_message.model_dump(exclude_none=True))

            for tool_call in response_message.tool_calls:
                tool_name = tool_call.function.name
                tool_input = json.loads(tool_call.function.arguments)
                
                result = run_tool(tool_name, tool_input)
                trace.append({"tool": tool_name, "input": tool_input})

                # Feed tool results back
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

        else:
            # Final answer
            try:
                # Strip markdown fences if present
                content = response_message.content.strip()
                if content.startswith("```json"):
                    content = content[7:]
                elif content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

                # The prompt asks for JSON, so we parse it
                final_output = json.loads(content)
                status = "pending_approval"
            except json.JSONDecodeError:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to parse LLM response as JSON. Raw response: {response_message.content}")
                # Fallback if the model returns plain text despite instructions
                final_output = {
                    "diagnosis": response_message.content,
                    "remediation_proposal": None
                }
                status = "parse_error"
            
            return {
                "diagnosis": final_output.get("diagnosis", response_message.content),
                "remediation_proposal": final_output.get("remediation_proposal", None),
                "tool_trace": trace,
                "action_status": status
            }
