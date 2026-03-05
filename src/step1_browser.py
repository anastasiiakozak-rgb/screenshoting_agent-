import sys
# ============================================================
# STEP 1: Multi-page Flow Screenshot Capture
# ============================================================
# Run with: python3 src/step1_browser.py

import asyncio
import sys
import json
import os
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------
# FLOWS
# ------------------------------------------------------------

FLOWS = [
    {
        "id": "bartender-purchase",
        "name": "Bartender App Purchase Flow",
        "steps": [
            {
                "label": "Landing Page",
                "action": "navigate",
                "url": "https://setapp.com/apps/bartender",
            },
            {
                "label": "Plans Page",
                "action": "navigate",
                "url": "https://pay.macpaw.com/bartender/configure?svn=236103807.1768217807&redirectUrl=https://setapp.com/success?app=bartender%26type=single&returnUrl=https://setapp.com/apps/bartender&productId=3&planId=price_1Rbf0zLgyQHONn05kzbtJqYE",
            },
            {
                "label": "Sign Up Page",
                "action": "manual_login",
                "url": "https://pay.macpaw.com/bartender/account?svn=236103807.1768217807&redirectUrl=https%3A%2F%2Fsetapp.com%2Fsuccess%3Fapp%3Dbartender%26type%3Dsingle&returnUrl=https%3A%2F%2Fsetapp.com%2Fapps%2Fbartender&productId=3&planId=price_1Rbf0zLgyQHONn05kzbtJqYE",
            },
            {
                "label": "Checkout Page",
                "action": "navigate",
                "url": "https://pay.macpaw.com/bartender/payment?planId=price_1Rbf0zLgyQHONn05kzbtJqYE&productId=3&redirectUrl=https%3A%2F%2Fsetapp.com%2Fsuccess%3Fapp%3Dbartender%26type%3Dsingle&returnUrl=https%3A%2F%2Fsetapp.com%2Fapps%2Fbartender",
            },
        ]
    },
]

# ------------------------------------------------------------
# UTILITIES
# ------------------------------------------------------------

def ensure_output_dir(flow_id):
    dir_path = Path(f"./output/{flow_id}/screenshots")
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path

async def save_screenshot(page, dir_path, step_index, label):
    filename = f"step-{str(step_index).zfill(3)}.png"
    filepath = dir_path / filename
    screenshot_bytes = await page.screenshot(full_page=True)
    filepath.write_bytes(screenshot_bytes)
    print(f"  📸 [{step_index}] '{label}' → {filename}")
    return filepath

async def wait_for_page_settle(page, timeout=10000):
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    try:
        await page.wait_for_load_state("load", timeout=timeout)
    except Exception:
        pass
    await page.wait_for_timeout(5000)

async def dismiss_overlays(page):
    selectors = [
        "button[id*='accept']", "button[class*='cookie']",
        "button[class*='consent']", "[aria-label*='Accept']",
        "#onetrust-accept-btn-handler", ".cookie-accept",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=600):
                await btn.click()
                await page.wait_for_timeout(400)
        except Exception:
            pass

# ------------------------------------------------------------
# MANUAL LOGIN HANDOFF
# ------------------------------------------------------------

async def wait_for_manual_login(page, flow_name):
    print(f"\n{'='*52}")
    print(f"  🔐 MANUAL SIGN UP REQUIRED")
    print(f"{'='*52}")
    print(f"\n  The browser is showing the sign up page.")
    print(f"  Please sign up manually in the browser window.")
    print(f"  Once done, come back here and...")
    print(f"\n  ▶  Press ENTER to continue\n")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, sys.stdin.readline)
    print(f"  ✅ Resuming — agent taking over...\n")
    await page.wait_for_timeout(1000)

# ------------------------------------------------------------
# CORE: Walk through each step
# ------------------------------------------------------------

async def capture_flow(flow_config, page):
    print(f"\n🚀 Starting: {flow_config['name']}")

    output_dir = ensure_output_dir(flow_config["id"])
    steps = []
    step_index = 0

    for step in flow_config["steps"]:
        label = step["label"]
        action = step["action"]
        url = step["url"]

        print(f"\n  → [{step_index}] {label}")

        try:
            # 1. Navigate to the URL
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await wait_for_page_settle(page)
            await dismiss_overlays(page)

            # 2. Screenshot the page
            filepath = await save_screenshot(page, output_dir, step_index, label)
            steps.append({
                "index": step_index,
                "label": label,
                "url": page.url,
                "title": await page.title(),
                "screenshot_path": str(filepath),
                "timestamp": datetime.now().isoformat(),
            })
            step_index += 1

            # 3. If this step needs manual login, pause after screenshotting
            if action == "manual_login":
                await wait_for_manual_login(page, flow_config["name"])

        except Exception as e:
            print(f"  ❌ Error on '{label}': {e}")

    return steps

# ------------------------------------------------------------
# RUNNER
# ------------------------------------------------------------

async def run_all_flows():
    print("🤖 User Flow Agent — Screenshot Capture")
    print("=" * 52)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
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

        for flow in FLOWS:
            steps = await capture_flow(flow, page)

            metadata_path = Path(f"./output/{flow['id']}/flow-metadata.json")
            with open(metadata_path, "w") as f:
                json.dump({
                    "id": flow["id"],
                    "name": flow["name"],
                    "captured_at": datetime.now().isoformat(),
                    "step_count": len(steps),
                    "steps": steps,
                }, f, indent=2)

            print(f"\n✅ '{flow['name']}' done — {len(steps)} screenshot(s) saved.")
            print(f"   Output: ./output/{flow['id']}/screenshots/")

        await browser.close()

    print("\n🎉 All flows captured!")

if __name__ == "__main__":
    asyncio.run(run_all_flows())