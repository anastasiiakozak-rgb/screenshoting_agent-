# ============================================================
# DEBUG — see exactly what Claude sees and recommends
# ============================================================
# Run with: python3 src/debug.py

import asyncio
import base64
import json
import os
import anthropic
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

async def debug_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        await page.goto("https://cleanmymac.com/", wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        # Screenshot
        screenshot_bytes = await page.screenshot(full_page=False)
        Path("./output").mkdir(exist_ok=True)
        Path("./output/debug.png").write_bytes(screenshot_bytes)
        print("📸 Screenshot saved to output/debug.png\n")

        # Print ALL buttons and links on the page
        print("🔍 BUTTONS found:")
        buttons = await page.locator("button").all()
        for btn in buttons:
            try:
                txt = (await btn.inner_text()).strip()
                sel_id = await btn.get_attribute("id")
                sel_class = await btn.get_attribute("class")
                if txt:
                    print(f"  - '{txt}' | id='{sel_id}' | class='{sel_class}'")
            except:
                pass

        print("\n🔍 LINKS found (that look like CTAs):")
        links = await page.locator("a").all()
        for link in links:
            try:
                txt = (await link.inner_text()).strip()
                href = await link.get_attribute("href")
                if txt and any(word in txt.lower() for word in ["buy", "get", "try", "start", "download", "price", "plan", "free"]):
                    print(f"  - '{txt}' | href='{href}'")
            except:
                pass

        # Ask Claude
        print("\n🤖 Asking Claude what it recommends...")
        img_b64 = base64.standard_b64encode(screenshot_bytes).decode("utf-8")

        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": img_b64}
                    },
                    {
                        "type": "text",
                        "text": """This is the CleanMyMac landing page.
Goal: reach the pricing/checkout page.

Return ONLY a JSON object:
{
  "label": "page name",
  "what_you_see": "describe the main CTA buttons visible",
  "next_action": {
    "type": "click",
    "selector": "ONE CSS selector for the most relevant CTA button or link",
    "description": "what you are clicking and why"
  },
  "should_stop": false,
  "stop_reason": ""
}"""
                    }
                ]
            }]
        )

        print("\n📋 Claude's recommendation:")
        print(response.content[0].text)

        print("\n⏳ Keeping browser open for 10 seconds so you can inspect the page...")
        await page.wait_for_timeout(10000)
        await browser.close()

asyncio.run(debug_page())