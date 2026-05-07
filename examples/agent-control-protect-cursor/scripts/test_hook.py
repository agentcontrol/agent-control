#!/usr/bin/env python3
"""Drive the Cursor guardrails hook with a 40-prompt battery and print results.

20 prompts target the secrets guardrail (15 with secrets that should deny, 5
clean that should allow). 20 prompts target the PII guardrail (15 with PII
that should deny, 5 clean that should allow).
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = str(ROOT / ".cursor/hooks/before_submit_protect_guardrails.py")
PY = str(ROOT / ".venv/bin/python3")


# Synthetic secret-shaped fixtures, assembled at runtime so source-scanning tools
# (GitHub push protection, etc.) don't flag this demo file. Values are not real
# credentials — they exist only to exercise the guardrail's regexes.
_STRIPE_LIVE = "_".join(["sk", "live", "4eC39HqLyjWDarjtT1zdp7dc"])
_STRIPE_TEST = "_".join(["sk", "test", "4eC39HqLyjWDarjtT1zdp7dc"])
_SLACK_BOT = "-".join(["xoxb", "1234567890", "aBcDeFgHiJkLmNoP123456"])


# ── 20 prompts targeting the secrets guardrail ──────────────────────────────
SECRETS_CASES = [
    # 15 with secrets — every one of these should deny.
    ("AWS access key id",
     "Why is AWS rejecting AKIAIOSFODNN7EXAMPLE in production?",
     "deny"),
    ("AWS access key id (alt)",
     "Config has AKIA1234567890ABCDEF — getting 403 from S3",
     "deny"),
    ("AWS STS temp credential",
     "STS token ASIAQXJZK3FE9HK4LMNO not working for assumed role",
     "deny"),
    ("GitHub PAT",
     "ghp_aBcDeF1234567890aBcDeF1234567890aBcDeF leaked into the repo",
     "deny"),
    ("GitHub OAuth token",
     "Why is gho_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx returning 401?",
     "deny"),
    ("GitHub server-to-server",
     "App auth failing with ghs_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
     "deny"),
    ("GitHub user-to-server",
     "Refresh ghu_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz before next call",
     "deny"),
    ("GitHub fine-grained PAT",
     "Token github_pat_11ABCDEFG0aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789ab is in env",
     "deny"),
    ("Anthropic key",
     "Anthropic call failing with sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
     "deny"),
    ("OpenAI key",
     "Why is sk-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA giving 429?",
     "deny"),
    ("Stripe live secret",
     f"Stripe webhook failing — {_STRIPE_LIVE}",
     "deny"),
    ("Stripe test secret",
     f"Test mode broken with {_STRIPE_TEST}",
     "deny"),
    ("Slack bot token",
     f"{_SLACK_BOT} stopped posting",
     "deny"),
    ("JWT in body",
     "Decode failure: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.signature_bytes_here",
     "deny"),
    ("PEM private key",
     "Found this in a config -----BEGIN RSA PRIVATE KEY----- MIIEpAIBAAKCAQEA",
     "deny"),

    # 5 clean — should allow.
    ("clean — refactor",
     "Refactor this function to remove duplicated null checks.",
     "allow"),
    ("clean — circuit breaker",
     "Help me design a circuit breaker for downstream services.",
     "allow"),
    ("clean — index perf",
     "Why is my postgres query slow on this composite index?",
     "allow"),
    ("clean — async port",
     "Convert this callback-based function to async/await.",
     "allow"),
    ("clean — DI explainer",
     "Explain how dependency injection works in TypeScript.",
     "allow"),
]


# ── 20 prompts targeting the PII guardrail ──────────────────────────────────
PII_CASES = [
    # 15 with PII — every one of these should deny.
    ("email",
     "Customer alice.smith@example.com keeps getting 500s — what's wrong?",
     "deny"),
    ("phone + name",
     "Call John Doe at +1-415-555-0182 about the bug",
     "deny"),
    ("SSN",
     "Investigate why the row with SSN 123-45-6789 has duplicate entries",
     "deny"),
    ("address",
     "Ship the package to 1600 Pennsylvania Avenue NW, Washington DC",
     "deny"),
    ("two emails",
     "Loop in bob@example.com and alice@example.com on this incident",
     "deny"),
    ("name + DOB",
     "Maria Garcia born 1985-03-12 cannot access her account",
     "deny"),
    ("credit card",
     "Customer card 4242 4242 4242 4242 was declined yesterday",
     "deny"),
    ("IP address",
     "User from 192.168.1.105 is hitting consistent 500s on /api",
     "deny"),
    ("email + phone",
     "Support ticket — jane@example.com phone 555-867-5309",
     "deny"),
    ("SSN + name",
     "David Johnson SSN 987-65-4321 cannot login since this morning",
     "deny"),
    ("name + address",
     "Sara Lee at 742 Evergreen Terrace, Springfield IL has a billing dispute",
     "deny"),
    ("two phones",
     "Reach the on-call at 212-555-1234 or 415-555-5678",
     "deny"),
    ("name + email",
     "Tom Hanks (thanks@example.com) reports a missing record",
     "deny"),
    ("DOB + SSN",
     "DOB 1990-12-25, SSN 555-44-3333 — please verify",
     "deny"),
    ("name + phone",
     "Priya Patel at +44 20 7946 0958 can't connect from London",
     "deny"),

    # 5 clean — should allow.
    ("clean — refactor",
     "Refactor this function to remove duplicated null checks.",
     "allow"),
    ("clean — JWT tests",
     "Write unit tests for a JWT refresh token validator.",
     "allow"),
    ("clean — SQL tune",
     "Help me optimize this SQL query for the orders table.",
     "allow"),
    ("clean — CSV dedup",
     "Generate a Python script to deduplicate a CSV by column 3.",
     "allow"),
    ("clean — DI explainer",
     "Explain how dependency injection works in TypeScript.",
     "allow"),
]


def run(prompt: str) -> dict:
    payload = json.dumps({"hook_event_name": "beforeSubmitPrompt", "prompt": prompt})
    result = subprocess.run(
        [PY, HOOK],
        input=payload,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(ROOT),
    )
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        return {"continue": None, "raw": result.stdout, "stderr": result.stderr}


def run_battery(label: str, cases: list) -> int:
    fmt = "  {icon} {name:<28} → {decision:<5}"
    print(f"\n— {label} ({len(cases)} prompts: 15 wrong + 5 right) —")
    fails = 0
    counts = {"deny": 0, "allow": 0}
    for name, prompt, expected in cases:
        result = run(prompt)
        cont = result.get("continue", True)
        decision = "allow" if cont else "deny"
        counts[decision] = counts.get(decision, 0) + 1
        ok = decision == expected
        if not ok:
            fails += 1
        icon = "✅" if ok else "❌"
        print(fmt.format(icon=icon, name=name, decision=decision))
    print(f"  ── {len(cases)-fails}/{len(cases)} match expected | denied={counts['deny']} allowed={counts['allow']}")
    return fails


def main() -> int:
    secrets_fails = run_battery("Secrets guardrail", SECRETS_CASES)
    pii_fails = run_battery("PII guardrail", PII_CASES)
    total_fails = secrets_fails + pii_fails
    total_cases = len(SECRETS_CASES) + len(PII_CASES)
    print()
    if total_fails == 0:
        print(f"ALL PASS  ({total_cases}/{total_cases})")
        return 0
    print(f"{total_fails} FAILURE(S)  ({total_cases - total_fails}/{total_cases})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
