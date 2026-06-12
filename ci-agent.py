"""
Demo 1: CI/CD AI Agent — GitHub Actions YAML Risk Reviewer
-----------------------------------------------------------
Usage:
    python3 ci_agent.py deploy.yml

Requires:
    pip install openai pyyaml

Set your key:
    export OPENAI_API_KEY=sk-...       # OpenAI
    # OR
    export ANTHROPIC_API_KEY=sk-ant-... # Anthropic Claude
"""

import os
import sys
import json
import yaml


# ── LLM CALL (supports both OpenAI and Anthropic) ──────────────────────────

def call_llm(prompt: str) -> str:
    """Send a prompt to the LLM and return the text response."""

    # Try OpenAI first, then Anthropic
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
        raise EnvironmentError(
            "No API key found. Set OPENAI_API_KEY or ANTHROPIC_API_KEY."
        )


# ── YAML LOADER ────────────────────────────────────────────────────────────

def load_workflow(path: str) -> str:
    """Load a GitHub Actions YAML file and return it as a formatted string."""
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    # Return pretty-printed YAML for the prompt
    return yaml.dump(data, default_flow_style=False)


# ── PROMPT BUILDER ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior DevOps security engineer reviewing GitHub Actions CI/CD pipelines.

Your job is to identify risky steps, insecure patterns, and missing safety gates.

Respond ONLY with a valid JSON object — no markdown, no explanation outside JSON.

Return this exact structure:
{
  "summary": "One-sentence overall assessment",
  "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
  "approval_required": true or false,
  "risks": [
    {
      "step": "name of the step or job",
      "issue": "what the risk is",
      "severity": "LOW | MEDIUM | HIGH | CRITICAL"
    }
  ],
  "suggestions": [
    "Actionable fix in one sentence"
  ],
  "safe_to_run": true or false
}"""


def build_prompt(workflow_yaml: str) -> str:
    return f"""{SYSTEM_PROMPT}

Here is the GitHub Actions workflow to review:

```yaml
{workflow_yaml}
```

Return your JSON analysis now:"""


# ── OUTPUT FORMATTER ───────────────────────────────────────────────────────

RISK_COLORS = {
    "LOW":      "\033[92m",   # green
    "MEDIUM":   "\033[93m",   # yellow
    "HIGH":     "\033[91m",   # red
    "CRITICAL": "\033[95m",   # magenta
}
RESET = "\033[0m"
BOLD  = "\033[1m"


def color(text: str, level: str) -> str:
    return f"{RISK_COLORS.get(level, '')}{text}{RESET}"


def print_report(report: dict) -> None:
    print()
    print(f"{BOLD}{'─' * 60}{RESET}")
    print(f"{BOLD}  CI/CD AI Agent — Pipeline Risk Report{RESET}")
    print(f"{'─' * 60}")

    risk_lvl = report.get("risk_level", "UNKNOWN")
    safe     = report.get("safe_to_run", False)
    approval = report.get("approval_required", False)

    print(f"\n  Summary     : {report.get('summary', '')}")
    print(f"  Risk Level  : {color(risk_lvl, risk_lvl)}")
    print(f"  Safe to Run : {color('YES', 'LOW') if safe else color('NO', 'HIGH')}")
    print(f"  Needs Approval: {'YES' if approval else 'no'}")

    risks = report.get("risks", [])
    if risks:
        print(f"\n{BOLD}  ⚠  Risks Found ({len(risks)}){RESET}")
        for i, r in enumerate(risks, 1):
            sev = r.get("severity", "")
            print(f"\n  {i}. {color(r.get('step', ''), sev)}")
            print(f"     Issue    : {r.get('issue', '')}")
            print(f"     Severity : {color(sev, sev)}")

    suggestions = report.get("suggestions", [])
    if suggestions:
        print(f"\n{BOLD}  ✅  Suggestions{RESET}")
        for s in suggestions:
            print(f"  • {s}")

    print(f"\n{'─' * 60}\n")


# ── MAIN ───────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 ci_agent.py <path-to-workflow.yml>")
        sys.exit(1)

    workflow_path = sys.argv[1]

    print(f"\n🔍  Loading workflow: {workflow_path}")
    workflow_yaml = load_workflow(workflow_path)

    print("🤖  Sending to AI agent for review...")
    prompt   = build_prompt(workflow_yaml)
    raw      = call_llm(prompt)

    # Strip any accidental markdown fences before parsing
    clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

    try:
        report = json.loads(clean)
    except json.JSONDecodeError:
        print("⚠  Agent returned non-JSON. Raw output:\n")
        print(raw)
        sys.exit(1)

    # Pretty-print the raw JSON for demo purposes
    print("\n📄  Raw JSON from agent:")
    print(json.dumps(report, indent=2))

    # Human-readable formatted report
    print_report(report)

    # Gate logic — how you'd use this in a real pipeline
    if not report.get("safe_to_run", True):
        print("🚫  Pipeline BLOCKED by AI agent. Fix risks before deploying.\n")
        sys.exit(1)
    elif report.get("approval_required"):
        print("⏸   Pipeline PAUSED — manual approval required.\n")
        sys.exit(2)
    else:
        print("✅  Pipeline cleared by AI agent. Proceeding.\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
