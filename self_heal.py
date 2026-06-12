"""
Demo 3: Self-Healing Pipeline — AI Deployment Decision Engine
--------------------------------------------------------------

"""

import os
import sys
import json
import time
import subprocess
import re


# ── PRESET SCENARIOS ───────────────────────────────────────────────────────

SCENARIOS = {
    "bad": {
        "error_rate_pct":    12.4,
        "p99_latency_ms":    4200,
        "health_score":      38,
        "cpu_usage_pct":     91,
        "memory_usage_pct":  87,
        "active_pods":       3,
        "desired_pods":      5,
        "deployment":        "api-server",
        "namespace":         "default",
        "version":           "v2.3.1",
        "previous_version":  "v2.3.0",
    },
    "good": {
        "error_rate_pct":    0.2,
        "p99_latency_ms":    142,
        "health_score":      97,
        "cpu_usage_pct":     34,
        "memory_usage_pct":  51,
        "active_pods":       5,
        "desired_pods":      5,
        "deployment":        "api-server",
        "namespace":         "default",
        "version":           "v2.3.1",
        "previous_version":  "v2.3.0",
    },
    "spike": {
        "error_rate_pct":    1.1,
        "p99_latency_ms":    890,
        "health_score":      72,
        "cpu_usage_pct":     96,
        "memory_usage_pct":  68,
        "active_pods":       5,
        "desired_pods":      5,
        "deployment":        "api-server",
        "namespace":         "default",
        "version":           "v2.3.1",
        "previous_version":  "v2.3.0",
    },
}


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
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    else:
        raise EnvironmentError("Set OPENAI_API_KEY or ANTHROPIC_API_KEY.")


# ── PROMPT ─────────────────────────────────────────────────────────────────

def build_prompt(metrics: dict) -> str:
    deployment = metrics["deployment"]
    namespace  = metrics["namespace"]

    system = f"""You are a deployment health AI agent responsible for self-healing production systems.

Analyze the deployment metrics and respond ONLY with valid JSON — no markdown, no prose.

Decision rules (use your judgment, these are guidelines):
- error_rate > 5%       → likely ROLLBACK
- p99_latency > 2000ms  → likely ROLLBACK or SCALE_UP
- health_score < 50     → likely ROLLBACK
- cpu > 90% + no errors → likely SCALE_UP
- all metrics normal    → CONTINUE
- team notification needed without action → ALERT_TEAM

IMPORTANT: Use ONLY these real values in commands — never use placeholders like <name> or <namespace>:
  deployment name : {deployment}
  namespace       : {namespace}

Return this exact JSON with NO angle-bracket placeholders anywhere:
{{
  "decision": "ROLLBACK | SCALE_UP | ALERT_TEAM | CONTINUE",
  "confidence": "HIGH | MEDIUM | LOW",
  "reason": "One sentence explanation",
  "rollback_command": "kubectl rollout undo deployment/{deployment} -n {namespace}",
  "scale_command": "kubectl scale deployment/{deployment} --replicas=8 -n {namespace}",
  "risk_if_ignored": "What happens if we do nothing"
}}"""

    return f"""{system}

Deployment metrics:
{json.dumps(metrics, indent=2)}

Return your JSON decision now:"""


# ── COMMAND SANITISER ──────────────────────────────────────────────────────

def sanitise_cmd(cmd: str, deployment: str, namespace: str) -> str:
    """
    Replace any leftover <placeholder> tokens with real values.
    Handles: <name>, <namespace>, <deployment>, <N>, <replicas> etc.
    """
    cmd = re.sub(r'deployment/<[^>]+>', f'deployment/{deployment}', cmd)
    cmd = re.sub(r'-n\s+<[^>]+>',      f'-n {namespace}',          cmd)
    cmd = re.sub(r'--replicas=<[^>]+>', '--replicas=8',              cmd)
    # Catch any remaining angle-bracket tokens
    cmd = re.sub(r'<[^>]+>', '', cmd).strip()
    return cmd


# ── ACTION EXECUTOR ────────────────────────────────────────────────────────

def execute_action(decision: str, report: dict, metrics: dict, dry_run: bool = True):
    B   = "\033[1m";  R   = "\033[0m"
    RED = "\033[91m"; GRN = "\033[92m"
    YLW = "\033[93m"; CYN = "\033[96m"

    deployment = metrics["deployment"]
    namespace  = metrics["namespace"]

    print(f"\n{'─'*62}")
    print(f"{B}  ⚡  Executing Decision: {decision}{R}")
    print(f"{'─'*62}")

    if decision == "ROLLBACK":
        raw_cmd = report.get(
            "rollback_command",
            f"kubectl rollout undo deployment/{deployment} -n {namespace}"
        )
        cmd = sanitise_cmd(raw_cmd, deployment, namespace)

        print(f"\n  {RED}🔴  ROLLBACK triggered{R}")
        print(f"  Reason   : {report.get('reason', '')}")
        print(f"  Command  : {B}{cmd}{R}")

        if dry_run:
            print(f"\n  {YLW}[DRY RUN] Would execute: {cmd}{R}")
            print(f"  {YLW}  Rolling back {deployment} "
                  f"({metrics['version']} → {metrics['previous_version']}) "
                  f"in namespace '{namespace}'{R}")
        else:
            print(f"\n  Executing: {cmd}")
            result = subprocess.run(cmd.split(), capture_output=True, text=True)
            if result.returncode == 0:
                print(f"  {GRN}✓ Rollback successful{R}")
                print(f"  {result.stdout.strip()}")
            else:
                print(f"  {RED}✗ kubectl error:{R}")
                print(f"  {result.stderr.strip()}")

    elif decision == "SCALE_UP":
        raw_cmd = report.get(
            "scale_command",
            f"kubectl scale deployment/{deployment} --replicas=8 -n {namespace}"
        )
        cmd = sanitise_cmd(raw_cmd, deployment, namespace)

        print(f"\n  {YLW}🟡  SCALE UP triggered{R}")
        print(f"  Reason   : {report.get('reason', '')}")
        print(f"  Command  : {B}{cmd}{R}")

        if dry_run:
            print(f"\n  {YLW}[DRY RUN] Would execute: {cmd}{R}")
        else:
            print(f"\n  Executing: {cmd}")
            result = subprocess.run(cmd.split(), capture_output=True, text=True)
            if result.returncode == 0:
                print(f"  {GRN}✓ Scale successful{R}")
                print(f"  {result.stdout.strip()}")
            else:
                print(f"  {RED}✗ kubectl error:{R}")
                print(f"  {result.stderr.strip()}")

    elif decision == "ALERT_TEAM":
        print(f"\n  {CYN}🔔  ALERT sent to team{R}")
        print(f"  Reason   : {report.get('reason', '')}")
        print(f"  Risk     : {report.get('risk_if_ignored', '')}")
        print(f"\n  [Simulating Slack/PagerDuty alert...]")
        time.sleep(0.5)
        print(f"  {GRN}✓ Alert delivered{R}")

    elif decision == "CONTINUE":
        print(f"\n  {GRN}✅  CONTINUE — no action needed{R}")
        print(f"  Reason   : {report.get('reason', '')}")
        print(f"  Deployment '{deployment}' in namespace '{namespace}' is healthy.")

    print(f"\n{'─'*62}\n")


# ── ARG PARSER ─────────────────────────────────────────────────────────────

def parse_args() -> tuple:
    """Returns (metrics dict, dry_run bool)."""
    args = sys.argv[1:]
    dry_run = "--live" not in args
    args = [a for a in args if a != "--live"]

    def get_str(flag, default):
        if flag in args:
            return args[args.index(flag) + 1]
        return default

    def get_float(flag, default):
        if flag in args:
            return float(args[args.index(flag) + 1])
        return default

    # Preset scenario
    if "--scenario" in args:
        scenario = get_str("--scenario", "bad")
        if scenario not in SCENARIOS:
            print(f"Unknown scenario '{scenario}'. Choose: bad, good, spike")
            sys.exit(1)
        metrics = dict(SCENARIOS[scenario])
        # Allow namespace override even on presets
        metrics["namespace"] = get_str("--namespace", metrics["namespace"])
        return metrics, dry_run

    # Manual flags — namespace defaults to "default"
    namespace  = get_str("--namespace",  "default")
    deployment = get_str("--deployment", "api-server")

    metrics = {
        "error_rate_pct":    get_float("--error-rate", 0.5),
        "p99_latency_ms":    get_float("--latency",    200),
        "health_score":      get_float("--health",     95),
        "cpu_usage_pct":     get_float("--cpu",        40),
        "memory_usage_pct":  get_float("--memory",     50),
        "active_pods":       int(get_float("--pods",   5)),
        "desired_pods":      5,
        "deployment":        deployment,
        "namespace":         namespace,
        "version":           "v2.3.1",
        "previous_version":  "v2.3.0",
    }
    return metrics, dry_run


# ── MAIN ───────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    metrics, dry_run = parse_args()

    B   = "\033[1m";  R   = "\033[0m"
    YLW = "\033[93m"; RED = "\033[91m"; GRN = "\033[92m"

    print(f"\n{B}{'─'*62}{R}")
    print(f"{B}  Self-Healing Agent — Deployment Health Check{R}")
    print(f"{'─'*62}")
    print(f"\n  Deployment   : {metrics['deployment']}  ({metrics['version']})")
    print(f"  Namespace    : {metrics['namespace']}")
    print(f"  Error Rate   : {metrics['error_rate_pct']}%")
    print(f"  P99 Latency  : {metrics['p99_latency_ms']} ms")
    print(f"  Health Score : {metrics['health_score']} / 100")
    print(f"  CPU / Memory : {metrics['cpu_usage_pct']}% / {metrics['memory_usage_pct']}%")
    print(f"  Pods Running : {metrics['active_pods']} / {metrics['desired_pods']}")
    print(f"  Mode         : {'🔴 LIVE — kubectl will run' if not dry_run else '🟡 DRY RUN — no changes'}")

    print(f"\n🤖  Sending to AI decision engine...")

    raw   = call_llm(build_prompt(metrics))
    clean = raw.strip()
    # Strip markdown fences if LLM wraps the JSON
    clean = re.sub(r'^```(?:json)?', '', clean).strip()
    clean = re.sub(r'```$',          '', clean).strip()

    try:
        report = json.loads(clean)
    except json.JSONDecodeError:
        print("⚠  Could not parse JSON from LLM. Raw output:\n")
        print(raw)
        sys.exit(1)

    print("\n📄  Raw JSON from agent:")
    print(json.dumps(report, indent=2))

    decision   = report.get("decision",   "ALERT_TEAM")
    confidence = report.get("confidence", "LOW")

    conf_color = GRN if confidence == "HIGH" else YLW if confidence == "MEDIUM" else RED
    print(f"\n  AI Decision  : {B}{decision}{R}   "
          f"(Confidence: {conf_color}{confidence}{R})")
    print(f"  Risk if ignored: {report.get('risk_if_ignored', '')}")

    execute_action(decision, report, metrics, dry_run=dry_run)


if __name__ == "__main__":
    main()
