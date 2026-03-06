# ============================================================
# WORKER: Runs on your Mac — polls Render for jobs
# ============================================================
# Run with: python3 src/worker.py
# Keep this running — it polls Render every 5 seconds for new jobs

import asyncio
import base64
import json
import os
import time
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------
# CONFIG — update RENDER_URL after deploying webapp_server.py
# ------------------------------------------------------------

RENDER_URL = os.getenv("RENDER_URL", "https://screenshoting-agent.onrender.com")
WORKER_SECRET = os.getenv("WORKER_SECRET", "my-worker-secret-123")
POLL_INTERVAL = 5  # seconds between polls

HEADERS = {
    "X-Worker-Secret": WORKER_SECRET,
    "Content-Type": "application/json",
}

# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def log(job_id, msg):
    print(msg)
    try:
        requests.post(
            f"{RENDER_URL}/worker/jobs/{job_id}/update",
            headers=HEADERS,
            json={"log_line": msg},
            timeout=10,
        )
    except Exception:
        pass

def update_status(job_id, status, message):
    try:
        requests.post(
            f"{RENDER_URL}/worker/jobs/{job_id}/update",
            headers=HEADERS,
            json={"status": status, "message": message},
            timeout=10,
        )
    except Exception as e:
        print(f"Failed to update status: {e}")

def get_fallback_url(url: str):
    if "cleanmymac" in url:
        return "https://macpaw.com/store/cleanmymac"
    if "setapp" in url:
        return "https://setapp.com/membership/join"
    if "notion" in url:
        return "https://www.notion.so/signup"
    return None

# ------------------------------------------------------------
# PROCESS A SINGLE JOB
# ------------------------------------------------------------

async def process_job(job):
    job_id = job["job_id"]
    url = job["url"]
    goal = job["goal"]

    print(f"\n{'='*52}")
    print(f"🔨 Processing job: {job_id}")
    print(f"   URL: {url}")
    print(f"   Goal: {goal}")
    print(f"{'='*52}")

    update_status(job_id, "running", "🌐 Opening browser...")

    # Import agent
    import sys
    import importlib.util
    PROJECT_DIR = Path(__file__).parent.parent
    sys.path.insert(0, str(PROJECT_DIR / "src"))

    spec = importlib.util.spec_from_file_location(
        "agent_job", str(PROJECT_DIR / "src/agent_job.py")
    )
    agent_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent_mod)

    config = {
        "id": job_id,
        "name": f"Flow: {url}",
        "start_url": url,
        "first_click": "a[href*='store']",
        "first_click_fallback_url": get_fallback_url(url),
        "goal": goal,
        "max_steps": 15,
        "payment": None,
    }

    # Create output dir
    output_dir = PROJECT_DIR / f"output/{job_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,  # visible on your Mac
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            log(job_id, "📸 Taking screenshots...")
            await agent_mod.run_agent(config, page)
            await browser.close()

        # Read metadata
        metadata_path = output_dir / "flow-metadata.json"
        if not metadata_path.exists():
            raise Exception("No screenshots captured")

        with open(metadata_path) as f:
            metadata = json.load(f)

        steps = metadata.get("steps", [])
        log(job_id, f"✅ {len(steps)} screenshots captured!")
        update_status(job_id, "running", "📤 Uploading results...")

        # Read all screenshots and encode as base64
        screenshots_data = {}
        step_info = []

        for step in steps:
            screenshot_path = Path(step["screenshot_path"])
            if screenshot_path.exists():
                img_bytes = screenshot_path.read_bytes()
                img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                screenshots_data[screenshot_path.name] = img_b64
                step_info.append({
                    "index": step["index"],
                    "label": step.get("label") or f"Step {step['index']}",
                    "url": step.get("url", ""),
                    "filename": screenshot_path.name,
                })

        # Post results to Render
        response = requests.post(
            f"{RENDER_URL}/worker/jobs/{job_id}/complete",
            headers=HEADERS,
            json={
                "name": metadata.get("name", f"Flow: {url}"),
                "steps": step_info,
                "screenshots": screenshots_data,
            },
            timeout=120,
        )

        if response.ok:
            print(f"✅ Job {job_id} completed and uploaded!")
            print(f"   View: {RENDER_URL}/gallery/{job_id}")
        else:
            print(f"❌ Failed to upload: {response.text}")

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Job {job_id} failed: {error_msg}")
        requests.post(
            f"{RENDER_URL}/worker/jobs/{job_id}/error",
            headers=HEADERS,
            json={"message": error_msg},
            timeout=10,
        )

# ------------------------------------------------------------
# MAIN LOOP — polls Render for pending jobs
# ------------------------------------------------------------

async def main():
    print("🤖 Worker started — polling for jobs...")
    print(f"   Server: {RENDER_URL}")
    print(f"   Polling every {POLL_INTERVAL} seconds")
    print("   Press Ctrl+C to stop\n")

    while True:
        try:
            res = requests.get(
                f"{RENDER_URL}/worker/jobs/pending",
                headers=HEADERS,
                timeout=10,
            )

            if res.ok:
                pending = res.json().get("jobs", [])
                if pending:
                    print(f"📬 Found {len(pending)} pending job(s)")
                    for job in pending:
                        # Mark as picked up immediately
                        update_status(job["job_id"], "running", "Worker picked up job...")
                        await process_job(job)
                else:
                    print(".", end="", flush=True)  # dot = polling, no jobs
            else:
                print(f"\n⚠️  Server returned {res.status_code}")

        except requests.exceptions.ConnectionError:
            print(f"\n⚠️  Can't reach server — retrying in {POLL_INTERVAL}s")
        except Exception as e:
            print(f"\n⚠️  Error: {e}")

        await asyncio.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())