# ============================================================
# RUNNER: Runs the full pipeline and pushes results to n8n
# ============================================================
# Run with: python3 src/run.py
#
# What it does:
# 1. Runs agent.py → captures screenshots
# 2. Runs step2_analysis.py → generates UX report
# 3. POSTs results to n8n webhook
# 4. n8n writes to Google Sheets + sends Slack message

import json
import os
import subprocess
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")
PROJECT_DIR = Path(__file__).parent.parent
FLOW_ID = "cleanmymac-purchase"

# ------------------------------------------------------------
# RUN A SCRIPT AND STREAM OUTPUT
# ------------------------------------------------------------

def run_script(script_name: str) -> bool:
    """Runs a Python script and prints output in real time."""
    print(f"\n{'='*52}")
    print(f"▶  Running {script_name}...")
    print(f"{'='*52}")

    result = subprocess.run(
        ["python3", f"src/{script_name}"],
        cwd=PROJECT_DIR,
    )

    if result.returncode != 0:
        print(f"\n❌ {script_name} failed!")
        return False

    print(f"\n✅ {script_name} complete!")
    return True

# ------------------------------------------------------------
# PUSH RESULTS TO N8N
# ------------------------------------------------------------

def push_to_n8n(flow_id: str):
    """Reads analysis results and POSTs them to n8n webhook."""

    if not N8N_WEBHOOK_URL:
        print("⚠️  N8N_WEBHOOK_URL not set in .env — skipping push")
        return

    # Load metadata
    metadata_path = PROJECT_DIR / f"output/{flow_id}/flow-metadata.json"
    analysis_path = PROJECT_DIR / f"output/{flow_id}/ux-analysis.json"

    if not analysis_path.exists():
        print("❌ ux-analysis.json not found")
        return

    with open(metadata_path) as f:
        metadata = json.load(f)

    with open(analysis_path) as f:
        analyses = json.load(f)

    # Build summary stats
    avg_score = sum(a["overall_score"] for a in analyses) / len(analyses)
    total_issues = sum(len(a.get("issues", [])) for a in analyses)
    critical = sum(
        1 for a in analyses
        for issue in a.get("issues", [])
        if issue["severity"] == "critical"
    )

    # Build one row per step for Google Sheets
    rows = []
    for a in analyses:
        rows.append({
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "flow": metadata["name"],
            "step": a.get("step_label", ""),
            "score": a.get("overall_score", ""),
            "summary": a.get("summary", ""),
            "issues_count": len(a.get("issues", [])),
            "critical_count": sum(
                1 for i in a.get("issues", [])
                if i["severity"] == "critical"
            ),
            "quick_wins": " | ".join(a.get("quick_wins", [])[:3]),
            "issues_detail": " | ".join(
                f"{i['severity'].upper()}: {i['issue']}"
                for i in a.get("issues", [])
            ),
            "friction_points": " | ".join(a.get("friction_points", [])[:2]),
        })

    # Payload for n8n
    payload = {
        "flow_id": flow_id,
        "flow_name": metadata["name"],
        "analyzed_at": datetime.now().isoformat(),
        "avg_score": round(avg_score, 1),
        "total_steps": len(analyses),
        "total_issues": total_issues,
        "critical_issues": critical,
        "rows": rows,
        # Slack summary message
        "slack_message": (
            f"✅ *UX Analysis Complete: {metadata['name']}*\n"
            f"📊 Average Score: *{round(avg_score, 1)}/10*\n"
            f"📸 Steps analyzed: *{len(analyses)}*\n"
            f"⚠️  Total issues: *{total_issues}* "
            f"({critical} critical)\n"
            f"🔗 Results added to Google Sheets"
        )
    }

    print(f"\n📤 Pushing results to n8n...")
    response = requests.post(
        N8N_WEBHOOK_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30
    )

    if response.status_code == 200:
        print(f"✅ Results sent to n8n successfully!")
    else:
        print(f"❌ n8n returned {response.status_code}: {response.text}")

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    print("🤖 User Flow Analysis Pipeline")
    print("=" * 52)
    print(f"Flow: {FLOW_ID}")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Step 1: Capture screenshots
    if not run_script("agent.py"):
        return

    # Step 2: Run UX analysis
    if not run_script("step2_analysis.py"):
        return

    # Step 3: Push to n8n
    push_to_n8n(FLOW_ID)

    print(f"\n🎉 Pipeline complete!")

if __name__ == "__main__":
    main()