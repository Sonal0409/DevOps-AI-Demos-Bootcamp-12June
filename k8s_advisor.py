"""
Demo 2: Kubernetes AI Ops — Pod Health Advisor
-----------------------------------------------

"""

import os
import sys
import json


# ── LLM CALL ───────────────────────────────────────────────────────────────

def call_llm(prompt: str) -> str:
    if os.getenv("OPENAI_API_KEY"):
        from openai import OpenAI
        client = OpenAI()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content
    elif os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    else:
        raise EnvironmentError("Set OPENAI_API_KEY or ANTHROPIC_API_KEY.")


# ── LIVE CLUSTER FETCH (optional) ──────────────────────────────────────────

def fetch_live_pods() -> list:
    from kubernetes import client, config
    config.load_kube_config()
    v1 = client.CoreV1Api()
    pods = v1.list_pod_for_all_namespaces(watch=False)
    result = []
    for p in pods.items:
        cs = p.status.container_statuses or []
        result.append({
            "name":      p.metadata.name,
            "namespace": p.metadata.namespace,
            "phase":     p.status.phase,
            "restarts":  sum(c.restart_count for c in cs),
            "ready":     all(c.ready for c in cs),
            "state":     {
                c.name: (
                    "running"          if c.state.running      else
                    "waiting:"         + (c.state.waiting.reason  or "") if c.state.waiting  else
                    "terminated:"      + (c.state.terminated.reason or "") if c.state.terminated else
                    "unknown"
                )
                for c in cs
            },
        })
    return result


# ── LOAD FROM FILE ─────────────────────────────────────────────────────────

def load_pods_from_file(path: str) -> list:
    with open(path) as f:
        raw = json.load(f)

    # Accept either raw kubectl JSON or our simplified list
    if isinstance(raw, list):
        return raw

    pods = []
    for item in raw.get("items", []):
        meta   = item.get("metadata", {})
        status = item.get("status", {})
        cs     = status.get("containerStatuses") or []
        pods.append({
            "name":      meta.get("name"),
            "namespace": meta.get("namespace", "default"),
            "phase":     status.get("phase", "Unknown"),
            "restarts":  sum(c.get("restartCount", 0) for c in cs),
            "ready":     all(c.get("ready", False) for c in cs),
            "state": {
                c.get("name", "?"): next(
                    (k + (":" + (v.get("reason") or "")) for k, v in c.get("state", {}).items() if v),
                    "unknown"
                )
                for c in cs
            },
        })
    return pods


# ── PROMPT ─────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Kubernetes SRE expert. Analyze pod health data and return ONLY valid JSON.

Return this exact structure:
{
  "cluster_health": "HEALTHY | DEGRADED | CRITICAL",
  "summary": "One sentence overall status",
  "unhealthy_pods": [
    {
      "name": "pod name",
      "namespace": "namespace",
      "issue": "root cause explanation",
      "severity": "LOW | MEDIUM | HIGH | CRITICAL",
      "fix_command": "exact kubectl command to remediate",
      "fix_explanation": "what the command does"
    }
  ],
  "scaling_recommendation": "SCALE_UP | SCALE_DOWN | NO_CHANGE",
  "scaling_reason": "why",
  "immediate_actions": ["action 1", "action 2"]
}"""


def build_prompt(pods: list) -> str:
    pods_yaml = json.dumps(pods, indent=2)
    return f"""{SYSTEM_PROMPT}

Here is the current pod status data:

{pods_yaml}

Return your JSON analysis now:"""


# ── OUTPUT FORMATTER ───────────────────────────────────────────────────────

COLORS = {
    "HEALTHY":  "\033[92m", "DEGRADED": "\033[93m", "CRITICAL": "\033[91m",
    "LOW":      "\033[92m", "MEDIUM":   "\033[93m",  "HIGH":    "\033[91m",
    "SCALE_UP": "\033[93m", "SCALE_DOWN": "\033[96m", "NO_CHANGE": "\033[92m",
}
R = "\033[0m"; B = "\033[1m"


def c(text, key):
    return f"{COLORS.get(key, '')}{text}{R}"


def print_report(report: dict):
    health = report.get("cluster_health", "UNKNOWN")
    print(f"\n{B}{'─'*62}{R}")
    print(f"{B}  K8s AI Ops — Cluster Health Report{R}")
    print(f"{'─'*62}")
    print(f"\n  Cluster Health  : {c(health, health)}")
    print(f"  Summary         : {report.get('summary', '')}")
    scaling = report.get("scaling_recommendation", "")
    print(f"  Scaling Advice  : {c(scaling, scaling)}  — {report.get('scaling_reason', '')}")

    unhealthy = report.get("unhealthy_pods", [])
    if unhealthy:
        print(f"\n{B}  ⚠  Unhealthy Pods ({len(unhealthy)}){R}")
        for pod in unhealthy:
            sev = pod.get("severity", "")
            print(f"\n  Pod       : {c(pod.get('name',''), sev)}  [{pod.get('namespace','')}]")
            print(f"  Issue     : {pod.get('issue','')}")
            print(f"  Severity  : {c(sev, sev)}")
            print(f"  Fix       : {B}{pod.get('fix_command','')}{R}")
            print(f"  What it does: {pod.get('fix_explanation','')}")
    else:
        print(f"\n  {c('All pods healthy ✓', 'HEALTHY')}")

    actions = report.get("immediate_actions", [])
    if actions:
        print(f"\n{B}  ✅  Immediate Actions{R}")
        for a in actions:
            print(f"  • {a}")

    print(f"\n{'─'*62}\n")


# ── MAIN ───────────────────────────────────────────────────────────────────

def main():
    live_mode = "--live" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if live_mode:
        print("\n📡  Fetching live pod data from cluster...")
        pods = fetch_live_pods()
    elif args:
        print(f"\n📂  Loading pod data from: {args[0]}")
        pods = load_pods_from_file(args[0])
    else:
        print("Usage: python3 k8s_advisor.py pods.json  [--live]")
        sys.exit(1)

    print(f"   Found {len(pods)} pods")
    print("🤖  Sending to AI advisor...")

    raw   = call_llm(build_prompt(pods))
    clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

    try:
        report = json.loads(clean)
    except json.JSONDecodeError:
        print("⚠  Non-JSON response:\n"); print(raw); sys.exit(1)

    print("\n📄  Raw JSON from agent:")
    print(json.dumps(report, indent=2))
    print_report(report)


if __name__ == "__main__":
    main()
