# Runs the agent for a specific job config
# Called by webapp.py with: python3 src/agent_job.py <config_path>

import asyncio
import sys
import json
import os
import base64
import random
import string
import re
import anthropic
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ------------------------------------------------------------
# Copy all helpers from agent.py directly here
# so this script is fully self-contained
# ------------------------------------------------------------

def generate_disposable_email():
    random_name = "agent" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{random_name}@mailinator.com"

def generate_password():
    return "AgentPass1!" + "".join(random.choices(string.digits, k=4))

def ensure_output_dir(run_id):
    dir_path = Path(f"./output/{run_id}/screenshots")
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path

async def save_screenshot(page, dir_path, step_index, label):
    filename = f"step-{str(step_index).zfill(3)}.png"
    filepath = dir_path / filename
    screenshot_bytes = await page.screenshot(full_page=False)
    filepath.write_bytes(screenshot_bytes)
    print(f"  📸 [{step_index}] '{label}' → {filename}")
    return filepath, screenshot_bytes

async def wait_for_page_settle(page, timeout=10000):
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        pass
    await page.wait_for_timeout(5000)  # increased for slower servers

async def dismiss_overlays(page):
    selectors = [
        "button.cky-btn-reject", "button.cky-btn-accept",
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

async def find_element(page, selector):
    candidates = [s.strip() for s in selector.split(",")]

    for sel in candidates:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=2000):
                print(f"  ✅ Found with: {sel}")
                return el
        except Exception:
            pass

    for frame in page.frames:
        if frame == page.main_frame:
            continue
        for sel in candidates:
            try:
                el = frame.locator(sel).first
                if await el.is_visible(timeout=1000):
                    print(f"  ✅ Found in iframe: {sel}")
                    return el
            except Exception:
                pass

    texts = re.findall(r"['\"]([^'\"]+)['\"]", selector)
    for text in texts:
        for tag in ["a", "button"]:
            try:
                el = page.locator(f"{tag}:has-text('{text}')").first
                if await el.is_visible(timeout=2000):
                    print(f"  ✅ Found via text fallback: {tag}:has-text('{text}')")
                    return el
            except Exception:
                pass
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            for tag in ["a", "button", "input"]:
                try:
                    el = frame.locator(f"{tag}:has-text('{text}')").first
                    if await el.is_visible(timeout=1000):
                        return el
                except Exception:
                    pass

    print(f"  ❌ Element not found for: {selector}")
    return None

def ask_claude(screenshot_bytes, goal, step_index, previous_steps, email, password, payment=None):
    img_b64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8")
    prev_labels = [s["label"] for s in previous_steps]

    if payment:
        payment_instructions = f"""
If you see a payment/card form, fill it using these test card details (no real charge):
- Card number field: {payment['card_number']}
- Expiry field: {payment['expiry']}
- CVC field: {payment['cvc']}
- Name on card field: {payment['name']}
- ZIP field: {payment['zip']}
Fill each field one at a time. After filling ALL card fields, click the submit/pay button.
Only set is_goal_complete to true after you see a confirmation/success page."""
    else:
        payment_instructions = """
IMPORTANT: Do NOT stop just because you see a checkout or order summary page.
A real payment form means you can see an actual CARD NUMBER input field (labeled 'Card number' with XXXX placeholder).
Only THEN set should_stop true with reason 'reached-payment'.
If the page shows email, country, or ZIP fields — fill them ALL and click continue to advance.
Never click the final pay/submit/subscribe button."""

    prompt = f"""You are an autonomous agent completing this goal:
GOAL: {goal}

Current step: {step_index}
Previous steps completed: {prev_labels}
Disposable email to use for sign up: {email}
Password to use for sign up: {password}

{payment_instructions}

Look at this screenshot and return ONLY a valid JSON object:
{{
  "label": "short name for this page e.g. Landing Page, Pricing Page, Sign Up Form, Payment Form, Confirmation",
  "description": "one sentence describing what you see",
  "goal_progress": "one sentence on how this page relates to the goal",
  "is_goal_complete": false,
  "should_stop": false,
  "stop_reason": "if should_stop is true, explain why",
  "next_action": {{
    "type": "click OR fill OR none",
    "selector": "ONE single CSS selector — no commas, no OR, no multiple selectors",
    "value": "text to type if action is fill, else empty string",
    "description": "plain English description of what you are doing"
  }}
}}

STRICT selector rules:
- Prefer href for links: a[href*='store'], a[href*='buy'], a[href*='checkout']
- Tag + attribute: input[type='email'], button[type='submit']
- Tag + class: button.cky-btn-reject
- Tag + has-text on a or button only: button:has-text('Create account')
- ID: #register-email-input
- NEVER use has-text on divs or spans
- NEVER use commas or combine selectors

Other rules:
- Use the disposable email above for any email fields
- Use the password above for any password fields
- For name fields use: Alex Johnson
- If you see a cookie banner, dismiss it first
- If you see Google sign up AND email/password option, ALWAYS choose email/password
- If you see ONLY a Google button, set should_stop true with reason "google-only"
- If you see a CAPTCHA, set should_stop true with reason "captcha"

Return ONLY the JSON object."""

    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": prompt}
            ]
        }]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())

async def run_agent(run_config, page):
    print(f"\n🤖 Starting agent: {run_config['name']}")
    output_dir = ensure_output_dir(run_config["id"])
    steps = []
    stuck_count = 0

    email = generate_disposable_email()
    password = generate_password()
    print(f"\n  📧 Using email: {email}")
    print(f"  🔑 Using password: {password}\n")

    await page.goto(run_config["start_url"], wait_until="domcontentloaded", timeout=30000)
    await wait_for_page_settle(page)
    await dismiss_overlays(page)
    await page.wait_for_timeout(3000)

    if run_config.get("first_click"):
        el = await find_element(page, run_config["first_click"])
        if el:
            await el.click()
            await wait_for_page_settle(page)
            await dismiss_overlays(page)
        elif run_config.get("first_click_fallback_url"):
            await page.goto(run_config["first_click_fallback_url"], wait_until="domcontentloaded", timeout=30000)
            await wait_for_page_settle(page)

    for step_index in range(run_config["max_steps"]):
        print(f"\n--- Step {step_index} ---")
        await dismiss_overlays(page)

        filepath, screenshot_bytes = await save_screenshot(page, output_dir, step_index, f"step-{step_index}")

        try:
            analysis = ask_claude(
                screenshot_bytes, run_config["goal"], step_index, steps,
                email, password, payment=run_config.get("payment")
            )
        except Exception as e:
            print(f"  ⚠️  Claude error: {e}")
            break

        print(f"  🏷️  {analysis.get('label')}")
        print(f"  📋 {analysis.get('description')}")
        print(f"  ➡️  {analysis.get('next_action', {}).get('description')}")

        safe_label = analysis.get('label', 'step').replace(' ', '_').lower()
        labeled_filename = f"step-{str(step_index).zfill(3)}-{safe_label}.png"
        labeled_path = output_dir / labeled_filename
        filepath.rename(labeled_path)

        steps.append({
            "index": step_index,
            "label": analysis.get("label"),
            "description": analysis.get("description"),
            "url": page.url,
            "title": await page.title(),
            "screenshot_path": str(labeled_path),
            "timestamp": datetime.now().isoformat(),
            "next_action": analysis.get("next_action"),
        })

        if analysis.get("is_goal_complete"):
            print(f"\n  🎉 Goal complete!")
            break

        if analysis.get("should_stop"):
            reason = analysis.get("stop_reason", "unknown")
            print(f"\n  ⏹️  Stopping: {reason}")
            break

        action = analysis.get("next_action", {})
        action_type = action.get("type", "none")
        selector = action.get("selector", "").strip()
        value = action.get("value", "")
        url_before = page.url

        if action_type == "none" or not selector:
            print("  ⏹️  No action — stopping.")
            break

        element = await find_element(page, selector)
        if element is None:
            break

        try:
            if action_type == "fill":
                await element.scroll_into_view_if_needed()
                await element.click()
                await element.fill(value)
                print(f"  ✏️  Filled: '{value}'")
                await page.wait_for_timeout(500)
            elif action_type == "click":
                await element.click()
                print(f"  🖱️  Clicked")
                await wait_for_page_settle(page)
        except Exception as e:
            print(f"  ⚠️  Action failed: {e}")
            break

        if page.url == url_before:
            prev_label = steps[-2]["label"] if len(steps) >= 2 else None
            curr_label = analysis.get("label")
            if prev_label == curr_label:
                stuck_count += 1
                print(f"  ⚠️  Same page and same label (stuck count: {stuck_count})")
                if stuck_count >= 8:  # higher threshold for server
                    print("  ⏹️  Stuck — stopping.")
                    break
            else:
                stuck_count = 0
        else:
            stuck_count = 0

    metadata_path = Path(f"./output/{run_config['id']}/flow-metadata.json")
    with open(metadata_path, "w") as f:
        json.dump({
            "id": run_config["id"],
            "name": run_config["name"],
            "goal": run_config["goal"],
            "email_used": email,
            "captured_at": datetime.now().isoformat(),
            "step_count": len(steps),
            "steps": steps,
        }, f, indent=2)

    print(f"\n✅ Done! {len(steps)} step(s) captured.")
    return steps

async def main():
    config_path = Path(sys.argv[1])
    with open(config_path) as f:
        config = json.load(f)

    browserless_token = os.getenv("BROWSERLESS_TOKEN")

    async with async_playwright() as p:
        if browserless_token:
            # Use Browserless cloud browser (for Render deployment)
            print("  🌐 Connecting to Browserless cloud browser...")
            browser = await p.chromium.connect_over_cdp(
                f"wss://chrome.browserless.io?token={browserless_token}&--disable-blink-features=AutomationControlled"
            )
        else:
            # Fall back to local browser (for development)
            print("  🖥️  Launching local browser...")
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
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)
        page = await context.new_page()
        await run_agent(config, page)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())