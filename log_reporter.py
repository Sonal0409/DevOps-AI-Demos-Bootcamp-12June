
import os
import sys
import json
import smtplib
import textwrap
from email.mime.text import MIMEText
from datetime import datetime


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


# ── LOG LOADER ─────────────────────────────────────────────────────────────

def load_log(path: str) -> str:
    with open(path) as f:
        lines = f.readlines()
    # Keep last 150 lines to avoid token limits
    return "".join(lines[-150:])


# ── PROMPT ─────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a DevOps report generator writing for a non-technical engineering manager.

Convert raw CI/CD pipeline logs into a clear, jargon-free incident report.

Respond ONLY with valid JSON — no markdown code fences, no extra prose.

Return this exact structure:
{
  "pipeline_status": "SUCCESS | FAILURE | PARTIAL",
  "duration_minutes": <number or null>,
  "what_happened": "2-3 plain English sentences describing what the pipeline did",
  "root_cause": "1-2 sentences on WHY it failed (or 'Pipeline completed successfully.' if it passed)",
  "action_required": "Exactly what a human needs to do next, or 'No action required.' if healthy",
  "affected_services": ["service name 1", "service name 2"],
  "severity": "NONE | LOW | MEDIUM | HIGH | CRITICAL",
  "estimated_fix_minutes": <number or null>,
  "email_subject": "Short subject line for a status email"
}"""


def build_prompt(log_text: str) -> str:
    return f"""{SYSTEM_PROMPT}

Raw CI/CD pipeline log:

{log_text}

Return your JSON report now:"""


# ── EMAIL SENDER (optional) ────────────────────────────────────────────────

def send_email(report: dict, recipient: str):
    """
    Sends a plain-text status email.
    Requires SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS env vars.
    For demo purposes this prints the email instead if SMTP is not configured.
    """
    body = f"""Pipeline Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}
{'='*50}

Status       : {report['pipeline_status']}
Severity     : {report['severity']}

WHAT HAPPENED
{report['what_happened']}

ROOT CAUSE
{report['root_cause']}

ACTION REQUIRED
{report['action_required']}

Affected Services : {', '.join(report.get('affected_services', ['unknown']))}
Estimated Fix     : {report.get('estimated_fix_minutes', 'N/A')} minutes

— Sent automatically by CI/CD AI Agent
"""

    smtp_host = os.getenv("SMTP_HOST")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")

    if not smtp_host:
        # Demo mode: just print the email
        print("\n📧  Email that would be sent:\n")
        print(f"  To      : {recipient}")
        print(f"  Subject : {report.get('email_subject', 'Pipeline Report')}")
        print(f"  Body:\n")
        for line in body.splitlines():
            print(f"    {line}")
        return

    msg = MIMEText(body)
    msg["Subject"] = report.get("email_subject", "Pipeline Report")
    msg["From"]    = smtp_user
    msg["To"]      = recipient

    with smtplib.SMTP(smtp_host, int(os.getenv("SMTP_PORT", 587))) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

    print(f"\n✅  Email sent to {recipient}")


# ── OUTPUT FORMATTER ───────────────────────────────────────────────────────

STATUS_COLORS = {
    "SUCCESS": "\033[92m", "FAILURE": "\033[91m", "PARTIAL": "\033[93m",
    "NONE":    "\033[92m", "LOW":     "\033[92m",  "MEDIUM": "\033[93m",
    "HIGH":    "\033[91m", "CRITICAL":"\033[95m",
}
R = "\033[0m"; B = "\033[1m"


def c(text, key):
    return f"{STATUS_COLORS.get(key, '')}{text}{R}"


def print_report(report: dict, raw_log_lines: int):
    status   = report.get("pipeline_status", "UNKNOWN")
    severity = report.get("severity", "UNKNOWN")

    print(f"\n{B}{'─'*62}{R}")
    print(f"{B}  CI/CD AI Reporter — Plain-English Pipeline Report{R}")
    print(f"{'─'*62}")
    print(f"\n  Status         : {c(status, status)}")
    print(f"  Severity       : {c(severity, severity)}")
    dur = report.get('duration_minutes')
    if dur:
        print(f"  Duration       : {dur} min")
    svcs = report.get('affected_services', [])
    if svcs:
        print(f"  Affected       : {', '.join(svcs)}")
    fix = report.get('estimated_fix_minutes')
    if fix:
        print(f"  Est. Fix Time  : {fix} min")

    print(f"\n{B}  📋  What Happened{R}")
    for line in textwrap.wrap(report.get('what_happened',''), 58):
        print(f"  {line}")

    print(f"\n{B}  🔍  Root Cause{R}")
    for line in textwrap.wrap(report.get('root_cause',''), 58):
        print(f"  {line}")

    action = report.get('action_required', '')
    if action and action != "No action required.":
        print(f"\n{B}  🚨  Action Required{R}")
        for line in textwrap.wrap(action, 58):
            print(f"  {line}")
    else:
        print(f"\n  {c('✅  No action required', 'SUCCESS')}")

    print(f"\n  (Summarized {raw_log_lines} lines of logs into this report)")
    print(f"{'─'*62}\n")


# ── MAIN ───────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("--"):
        print(__doc__)
        sys.exit(1)

    log_path  = args[0]
    recipient = None
    if "--email" in args:
        recipient = args[args.index("--email") + 1]

    print(f"\n📂  Loading log: {log_path}")
    log_text   = load_log(log_path)
    log_lines  = log_text.count("\n")
    print(f"   Loaded {log_lines} lines")

    print("🤖  Sending to AI reporter...")
    raw   = call_llm(build_prompt(log_text))
    clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

    try:
        report = json.loads(clean)
    except json.JSONDecodeError:
        print("⚠  Non-JSON response:\n"); print(raw); sys.exit(1)

    print("\n📄  Raw JSON from agent:")
    print(json.dumps(report, indent=2))

    print_report(report, log_lines)

    if recipient:
        send_email(report, recipient)
    else:
        # Always show simulated email in demo
        send_email(report, "manager@company.com")


if __name__ == "__main__":
    main()
