
# ============================================================
# STEP 2: Upload flow screenshots to Miro as a flow map
# ============================================================
# Run with: python3 src/step2_miro.py
#
# What it does:
# 1. Reads flow-metadata.json from your output folder
# 2. Creates a new Miro board named after the flow
# 3. Uploads each screenshot as a large image node
# 4. Adds a label below each screenshot
# 5. Connects them with arrows in sequence
# 6. Prints a shareable link to the board

import json
import os
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

MIRO_TOKEN = os.getenv("MIRO_ACCESS_TOKEN")
MIRO_API   = "https://api.miro.com/v2"
HEADERS    = {"Authorization": f"Bearer {MIRO_TOKEN}", "Accept": "application/json"}

# ------------------------------------------------------------
# CONFIG — point this to your output folder
# ------------------------------------------------------------

FLOW_ID = "cleanmymac-purchase"   # matches the id in your RUNS config
METADATA_PATH = Path(f"./output/{FLOW_ID}/flow-metadata.json")

# Layout settings
IMG_WIDTH    = 600   # px width of each screenshot node
IMG_HEIGHT   = 400   # px height (Miro keeps aspect ratio)
H_SPACING    = 800   # horizontal gap between nodes
LABEL_OFFSET = 240   # how far below image the label sits
START_X      = 0     # starting X position on board
START_Y      = 0     # starting Y position on board

# ------------------------------------------------------------
# MIRO API HELPERS
# ------------------------------------------------------------

def create_board(name: str) -> str:
    """Creates a new Miro board and returns its ID."""
    res = requests.post(
        f"{MIRO_API}/boards",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={
            "name": name,
            "teamId": "3074457358901383318",
        }
    )
    res.raise_for_status()
    board_id = res.json()["id"]
    print(f"  ✅ Board created: {name} (id: {board_id})")
    return board_id

def upload_image(board_id: str, image_path: Path, x: int, y: int) -> str:
    """Uploads a local image file to the Miro board and returns the item ID."""
    with open(image_path, "rb") as f:
        res = requests.post(
            f"{MIRO_API}/boards/{board_id}/images",
            headers={"Authorization": f"Bearer {MIRO_TOKEN}"},
            data={"data": json.dumps({
                "position": {"x": x, "y": y, "origin": "center"},
                "geometry": {"width": IMG_WIDTH, "height": IMG_HEIGHT}
            })},
            files={"resource": (image_path.name, f, "image/png")}
        )
    res.raise_for_status()
    item_id = res.json()["id"]
    print(f"  🖼️  Uploaded: {image_path.name} → item {item_id}")
    return item_id

def add_label(board_id: str, text: str, x: int, y: int) -> str:
    """Adds a text label below a screenshot."""
    res = requests.post(
        f"{MIRO_API}/boards/{board_id}/texts",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={
            "data": {"content": f"<p><strong>{text}</strong></p>"},
            "position": {"x": x, "y": y, "origin": "center"},
            "geometry": {"width": IMG_WIDTH},
            "style": {"fontSize": "18", "textAlign": "center"}
        }
    )
    res.raise_for_status()
    return res.json()["id"]

def add_connector(board_id: str, from_id: str, to_id: str):
    """Draws an arrow between two items."""
    res = requests.post(
        f"{MIRO_API}/boards/{board_id}/connectors",
        headers={**HEADERS, "Content-Type": "application/json"},
        json={
            "startItem": {"id": from_id},
            "endItem":   {"id": to_id},
            "style": {
                "strokeColor": "#4262FF",
                "strokeWidth": "2",
                "endStrokeCap": "arrow"
            }
        }
    )
    res.raise_for_status()
    print(f"  ➡️  Connected {from_id} → {to_id}")

def get_board_link(board_id: str) -> str:
    """Returns the shareable URL for the board."""
    res = requests.get(
        f"{MIRO_API}/boards/{board_id}",
        headers=HEADERS
    )
    res.raise_for_status()
    return res.json().get("viewLink", f"https://miro.com/app/board/{board_id}/")

# ------------------------------------------------------------
# MAIN: Build the flow map
# ------------------------------------------------------------

def build_flow_map():
    print("🎨 Building Miro flow map...")
    print("=" * 52)

    # 1. Load metadata
    if not METADATA_PATH.exists():
        print(f"❌ Metadata not found: {METADATA_PATH}")
        print("   Run agent.py first to capture the flow.")
        return

    with open(METADATA_PATH) as f:
        metadata = json.load(f)

    steps = metadata["steps"]
    flow_name = metadata["name"]
    print(f"\n  📋 Flow: {flow_name}")
    print(f"  📸 Steps: {len(steps)}\n")

    # 2. Create Miro board
    board_id = create_board(f"User Flow: {flow_name}")

    # 3. Upload each screenshot + label, collect item IDs
    item_ids = []

    for i, step in enumerate(steps):
        screenshot_path = Path(step["screenshot_path"])
        label = step.get("label") or f"Step {i}"
        x = START_X + i * H_SPACING
        y = START_Y

        if not screenshot_path.exists():
            print(f"  ⚠️  Screenshot not found: {screenshot_path} — skipping")
            continue

        print(f"\n  → Step {i}: {label}")

        # Upload screenshot
        item_id = upload_image(board_id, screenshot_path, x, y)
        item_ids.append(item_id)

        # Add label below
        add_label(board_id, label, x, y + LABEL_OFFSET)

    # 4. Connect steps with arrows
    print(f"\n  🔗 Adding connectors...")
    for i in range(len(item_ids) - 1):
        add_connector(board_id, item_ids[i], item_ids[i + 1])

    # 5. Print shareable link
    link = get_board_link(board_id)
    print(f"\n{'='*52}")
    print(f"  🎉 Done! Your flow map is ready:")
    print(f"  🔗 {link}")
    print(f"{'='*52}")

if __name__ == "__main__":
    build_flow_map()