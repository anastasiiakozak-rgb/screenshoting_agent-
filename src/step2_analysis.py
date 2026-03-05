# ============================================================
# STEP 2: UX Analysis — Claude reviews each screenshot
# ============================================================
# Run with: python3 src/step2_analysis.py

import base64
import json
import os
import anthropic
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

DEFAULT_FLOW_ID = "cleanmymac-purchase"

# ------------------------------------------------------------
# ANALYZE A SINGLE SCREENSHOT
# ------------------------------------------------------------

def analyze_screenshot(screenshot_path: Path, step: dict, flow_name: str, all_steps: list) -> dict:
    with open(screenshot_path, "rb") as f:
        img_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    step_index = step["index"]
    label = step.get("label", f"Step {step_index}")
    all_labels = [s.get("label") for s in all_steps]

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": img_b64}
                },
                {
                    "type": "text",
                    "text": f"""You are a senior UX researcher analyzing a user flow for "{flow_name}".

This is step {step_index + 1} of {len(all_steps)}: "{label}"
Full flow: {" → ".join(all_labels)}

Analyze this screenshot and return ONLY a valid JSON object:
{{
  "step_label": "{label}",
  "overall_score": <1-10 score for UX quality>,
  "summary": "2-3 sentence overview of this step's UX",
  "positives": ["what works well — be specific"],
  "issues": [
    {{
      "severity": "critical | major | minor",
      "issue": "description of the UX problem",
      "recommendation": "specific actionable fix"
    }}
  ],
  "friction_points": ["anything that might cause a user to drop off or hesitate"],
  "best_practices_missing": ["industry best practices that are absent from this step"],
  "quick_wins": ["small changes that would have high impact"]
}}

Be specific, actionable, and focus on real UX problems — not generic advice.
Return ONLY the JSON object."""
                }
            ]
        }]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

# ------------------------------------------------------------
# GENERATE MARKDOWN REPORT
# ------------------------------------------------------------

def generate_report(flow_name: str, analyses: list, metadata: dict) -> str:
    avg_score = sum(a["overall_score"] for a in analyses) / len(analyses)
    critical_issues = [
        (a["step_label"], issue)
        for a in analyses
        for issue in a.get("issues", [])
        if issue["severity"] == "critical"
    ]

    lines = []
    lines += [
        f"# UX Analysis Report: {flow_name}",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Flow:** {' → '.join(s.get('label', f'Step {i}') for i, s in enumerate(metadata['steps']))}",
        f"**Overall UX Score:** {avg_score:.1f} / 10",
        "",
        "## Executive Summary",
        f"This flow was analyzed across {len(analyses)} steps. "
        f"The average UX score is **{avg_score:.1f}/10**. "
        f"There are **{len(critical_issues)} critical issue(s)** that need immediate attention.",
        "",
    ]

    if critical_issues:
        lines += ["## 🚨 Critical Issues (Fix First)", ""]
        for step_label, issue in critical_issues:
            lines += [
                f"**{step_label}:** {issue['issue']}",
                f"> **Fix:** {issue['recommendation']}",
                "",
            ]

    lines += ["## Step-by-Step Analysis", ""]

    for i, analysis in enumerate(analyses):
        score = analysis["overall_score"]
        score_emoji = "🟢" if score >= 8 else "🟡" if score >= 6 else "🔴"

        lines += [
            f"### Step {i + 1}: {analysis['step_label']} {score_emoji} {score}/10",
            "",
            f"**Summary:** {analysis['summary']}",
            "",
        ]

        if analysis.get("positives"):
            lines += ["**✅ What works well:**"]
            for p in analysis["positives"]:
                lines += [f"- {p}"]
            lines += [""]

        if analysis.get("issues"):
            lines += ["**⚠️ Issues:**"]
            for issue in analysis["issues"]:
                sev_emoji = "🔴" if issue["severity"] == "critical" else "🟡" if issue["severity"] == "major" else "⚪"
                lines += [
                    f"- {sev_emoji} **{issue['severity'].upper()}:** {issue['issue']}",
                    f"  - *Fix:* {issue['recommendation']}",
                ]
            lines += [""]

        if analysis.get("friction_points"):
            lines += ["**🚧 Friction Points:**"]
            for fp in analysis["friction_points"]:
                lines += [f"- {fp}"]
            lines += [""]

        if analysis.get("quick_wins"):
            lines += ["**⚡ Quick Wins:**"]
            for q in analysis["quick_wins"]:
                lines += [f"- {q}"]
            lines += [""]

        lines += ["---", ""]

    all_quick_wins = [qw for a in analyses for qw in a.get("quick_wins", [])]
    all_missing = [bp for a in analyses for bp in a.get("best_practices_missing", [])]

    if all_quick_wins:
        lines += ["## ⚡ Top Quick Wins Across the Flow", ""]
        for qw in all_quick_wins[:8]:
            lines += [f"- {qw}"]
        lines += [""]

    if all_missing:
        lines += ["## 📋 Missing Best Practices", ""]
        for bp in list(dict.fromkeys(all_missing))[:8]:
            lines += [f"- {bp}"]
        lines += [""]

    return "\n".join(lines)

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def run_analysis(flow_id: str = None):
    flow_id = flow_id or DEFAULT_FLOW_ID

    metadata_path = Path(f"./output/{flow_id}/flow-metadata.json")
    report_path = Path(f"./output/{flow_id}/ux-report.md")
    json_path = Path(f"./output/{flow_id}/ux-analysis.json")

    print("🔍 UX Analysis Agent")
    print("=" * 52)

    if not metadata_path.exists():
        print(f"❌ Metadata not found: {metadata_path}")
        print("   Run agent.py first to capture the flow.")
        return

    with open(metadata_path) as f:
        metadata = json.load(f)

    steps = metadata["steps"]
    flow_name = metadata["name"]

    print(f"\n  📋 Flow: {flow_name}")
    print(f"  📸 Analyzing {len(steps)} steps...\n")

    analyses = []

    for step in steps:
        screenshot_path = Path(step["screenshot_path"])
        label = step.get("label", f"Step {step['index']}")

        if not screenshot_path.exists():
            print(f"  ⚠️  Screenshot not found: {screenshot_path} — skipping")
            continue

        print(f"  🤖 Analyzing: {label}...")

        try:
            analysis = analyze_screenshot(screenshot_path, step, flow_name, steps)
            analyses.append(analysis)
            score = analysis.get("overall_score", "?")
            issues = len(analysis.get("issues", []))
            print(f"     Score: {score}/10 | Issues found: {issues}")
        except Exception as e:
            print(f"  ⚠️  Failed to analyze {label}: {e}")

    if not analyses:
        print("❌ No analyses completed.")
        return

    print(f"\n  📝 Generating report...")
    report = generate_report(flow_name, analyses, metadata)

    report_path.write_text(report)
    print(f"  ✅ Report saved: {report_path}")

    json_path.write_text(json.dumps(analyses, indent=2))
    print(f"  ✅ Raw data saved: {json_path}")

    print(f"\n{'='*52}")
    print(f"🎉 Analysis complete!")
    print(f"   Open: {report_path}")

if __name__ == "__main__":
    run_analysis()