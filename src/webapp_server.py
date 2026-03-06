# ============================================================
# SERVER: Runs on Render — serves UI, stores jobs + results
# ============================================================
# Deploy this to Render with start command: python src/webapp_server.py
# Set env var: WORKER_SECRET=some-random-secret

import json
import os
import uuid
import base64
import zipfile
import io
from pathlib import Path
from flask import Flask, jsonify, render_template_string, request, send_file
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
WORKER_SECRET = os.environ.get("WORKER_SECRET", "my-worker-secret-123")

# In-memory storage
jobs = {}          # job_id -> job metadata + status
screenshots = {}   # job_id -> {filename: base64_bytes}

# ------------------------------------------------------------
# HOME PAGE
# ------------------------------------------------------------

HOME_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>UX Flow Screenshot Tool</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #f5f5f7; min-height: 100vh; display: flex;
           align-items: center; justify-content: center; padding: 20px; }
    .card { background: white; border-radius: 16px; padding: 48px;
            max-width: 580px; width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.08); }
    h1 { font-size: 28px; font-weight: 700; margin-bottom: 8px; }
    .subtitle { color: #666; margin-bottom: 32px; font-size: 16px; }
    label { display: block; font-weight: 600; margin-bottom: 6px; font-size: 14px; }
    input, textarea { width: 100%; padding: 12px 16px; border: 1.5px solid #e0e0e0;
                      border-radius: 8px; font-size: 15px; margin-bottom: 20px; font-family: inherit; }
    input:focus, textarea:focus { outline: none; border-color: #0066ff; }
    textarea { height: 110px; resize: vertical; }
    button { width: 100%; padding: 14px; background: #0066ff; color: white;
             border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; }
    button:hover { background: #0052cc; }
    button:disabled { background: #aaa; cursor: not-allowed; }
    .chips { margin-top: 24px; padding-top: 24px; border-top: 1px solid #f0f0f0; }
    .chips p { font-size: 13px; color: #999; margin-bottom: 8px; }
    .chip { display: inline-block; background: #f0f5ff; color: #0066ff;
            padding: 5px 12px; border-radius: 20px; font-size: 13px; margin: 3px; cursor: pointer; }
    .chip:hover { background: #e0ecff; }
  </style>
</head>
<body>
  <div class="card">
    <h1>📸 Flow Screenshot Tool</h1>
    <p class="subtitle">Enter a URL and goal — the agent will walk through the flow and capture every step.</p>
    <form id="form">
      <label>Product URL</label>
      <input type="url" id="url" placeholder="https://cleanmymac.com" required />
      <label>What flow to capture?</label>
      <textarea id="goal" placeholder="e.g. Walk through the purchase flow from landing page to checkout. Stop before submitting payment." required></textarea>
      <button type="submit" id="btn">Capture Flow →</button>
    </form>
    <div class="chips">
      <p>Examples:</p>
      <span class="chip" onclick="fill('https://cleanmymac.com', 'Walk through the purchase flow from landing page to checkout. Stop before submitting payment.')">CleanMyMac purchase</span>
      <span class="chip" onclick="fill('https://notion.so', 'Sign up for a free account and reach the dashboard.')">Notion signup</span>
      <span class="chip" onclick="fill('https://setapp.com', 'Walk through the membership signup flow.')">Setapp signup</span>
    </div>
  </div>
  <script>
    function fill(url, goal) {
      document.getElementById('url').value = url;
      document.getElementById('goal').value = goal;
    }
    document.getElementById('form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('btn');
      btn.textContent = 'Starting...';
      btn.disabled = true;
      const res = await fetch('/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: document.getElementById('url').value,
          goal: document.getElementById('goal').value,
        })
      });
      const data = await res.json();
      if (data.job_id) window.location.href = '/status/' + data.job_id;
    });
  </script>
</body>
</html>
"""

STATUS_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Capturing... | Flow Screenshot Tool</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #f5f5f7; min-height: 100vh; display: flex;
           align-items: center; justify-content: center; padding: 20px; }
    .card { background: white; border-radius: 16px; padding: 48px; max-width: 560px;
            width: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.08); text-align: center; }
    h1 { font-size: 24px; font-weight: 700; margin-bottom: 8px; }
    .msg { color: #666; margin-bottom: 24px; }
    .spinner { width: 48px; height: 48px; border: 4px solid #f0f0f0;
               border-top-color: #0066ff; border-radius: 50%;
               animation: spin 0.8s linear infinite; margin: 0 auto 24px; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .log { text-align: left; background: #f8f8f8; border-radius: 8px; padding: 16px;
           font-family: monospace; font-size: 13px; max-height: 200px;
           overflow-y: auto; color: #444; margin-top: 16px; }
    .btn { display: inline-block; margin: 8px; padding: 12px 28px;
           border-radius: 8px; font-size: 15px; font-weight: 600; text-decoration: none; }
    .btn-primary { background: #0066ff; color: white; }
    .btn-secondary { background: #f0f0f0; color: #333; }
  </style>
</head>
<body>
  <div class="card" id="card">
    <div class="spinner"></div>
    <h1>Capturing flow...</h1>
    <p class="msg" id="msg">Waiting for worker...</p>
    <div class="log" id="log"></div>
  </div>
  <script>
    const jobId = "{{ job_id }}";
    let lastLog = 0;
    async function poll() {
      const res = await fetch('/job/' + jobId);
      const data = await res.json();
      document.getElementById('msg').textContent = data.message || '';
      if (data.log && data.log.length > lastLog) {
        const logEl = document.getElementById('log');
        data.log.slice(lastLog).forEach(line => { logEl.innerHTML += line + '<br>'; });
        logEl.scrollTop = logEl.scrollHeight;
        lastLog = data.log.length;
      }
      if (data.status === 'done') {
        document.getElementById('card').innerHTML = `
          <div style="font-size:56px;margin-bottom:16px">✅</div>
          <h1>Flow Captured!</h1>
          <p class="msg" style="margin-bottom:24px">${data.step_count} screenshot(s) captured</p>
          <a href="/gallery/${jobId}" class="btn btn-primary">🖼️ View Gallery</a>
          <a href="/download/${jobId}" class="btn btn-secondary">⬇️ Download ZIP</a>
          <p style="margin-top:20px;font-size:13px;color:#999">
            <a href="/" style="color:#0066ff">← Capture another flow</a>
          </p>`;
      } else if (data.status === 'error') {
        document.getElementById('card').innerHTML = `
          <div style="font-size:56px;margin-bottom:16px">❌</div>
          <h1>Something went wrong</h1>
          <p class="msg">${data.message}</p>
          <a href="/" class="btn btn-primary">← Try again</a>`;
      } else {
        setTimeout(poll, 3000);
      }
    }
    poll();
  </script>
</body>
</html>
"""

GALLERY_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Flow Gallery</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: #f5f5f7; padding: 32px 20px; }
    .header { max-width: 1100px; margin: 0 auto 32px;
              display: flex; justify-content: space-between; align-items: center; }
    h1 { font-size: 24px; font-weight: 700; }
    .grid { max-width: 1100px; margin: 0 auto;
            display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; }
    .step-card { background: white; border-radius: 12px; overflow: hidden;
                 box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
    .step-card img { width: 100%; display: block; cursor: pointer; }
    .step-info { padding: 14px 16px; border-top: 1px solid #f0f0f0; }
    .step-num { font-size: 12px; color: #999; margin-bottom: 2px; }
    .step-label { font-size: 15px; font-weight: 600; }
    .step-url { font-size: 12px; color: #999; margin-top: 2px;
                white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .btn { display: inline-block; padding: 10px 20px; border-radius: 8px;
           font-size: 14px; font-weight: 600; text-decoration: none; margin-left: 8px; }
    .btn-primary { background: #0066ff; color: white; }
    .btn-secondary { background: white; color: #333; border: 1px solid #ddd; }
    .lightbox { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85);
                z-index: 1000; align-items: center; justify-content: center; }
    .lightbox.active { display: flex; }
    .lightbox img { max-width: 90vw; max-height: 90vh; border-radius: 8px; }
    .lightbox-close { position: fixed; top: 20px; right: 24px; color: white;
                      font-size: 32px; cursor: pointer; }
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h1>📸 {{ name }}</h1>
      <p style="color:#666;margin-top:4px;font-size:14px">{{ step_count }} steps captured</p>
    </div>
    <div>
      <a href="/download/{{ job_id }}" class="btn btn-primary">⬇️ Download ZIP</a>
      <a href="/" class="btn btn-secondary">← New capture</a>
    </div>
  </div>
  <div class="grid">
    {% for step in steps %}
    <div class="step-card">
      <img src="/screenshot/{{ job_id }}/{{ step.filename }}"
           onclick="openLightbox(this.src)" alt="{{ step.label }}" />
      <div class="step-info">
        <div class="step-num">Step {{ step.index + 1 }}</div>
        <div class="step-label">{{ step.label }}</div>
        <div class="step-url">{{ step.url }}</div>
      </div>
    </div>
    {% endfor %}
  </div>
  <div class="lightbox" id="lightbox" onclick="closeLightbox()">
    <span class="lightbox-close">✕</span>
    <img id="lightbox-img" src="" />
  </div>
  <script>
    function openLightbox(src) {
      document.getElementById('lightbox-img').src = src;
      document.getElementById('lightbox').classList.add('active');
    }
    function closeLightbox() {
      document.getElementById('lightbox').classList.remove('active');
    }
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeLightbox(); });
  </script>
</body>
</html>
"""

# ------------------------------------------------------------
# PUBLIC ROUTES
# ------------------------------------------------------------

@app.route("/")
def home():
    return render_template_string(HOME_HTML)

@app.route("/start", methods=["POST"])
def start():
    data = request.json or {}
    url = data.get("url", "").strip()
    goal = data.get("goal", "").strip()
    if not url or not goal:
        return jsonify({"error": "URL and goal required"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "status": "pending",
        "message": "Waiting for worker...",
        "log": [],
        "url": url,
        "goal": goal,
        "step_count": 0,
    }
    screenshots[job_id] = {}
    return jsonify({"job_id": job_id})

@app.route("/status/<job_id>")
def status(job_id):
    return render_template_string(STATUS_HTML, job_id=job_id)

@app.route("/job/<job_id>")
def job_status(job_id):
    return jsonify(jobs.get(job_id, {"status": "error", "message": "Job not found"}))

@app.route("/gallery/<job_id>")
def gallery(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return "Not ready", 404
    steps = job.get("steps", [])
    return render_template_string(
        GALLERY_HTML,
        job_id=job_id,
        name=job.get("name", "Flow"),
        step_count=len(steps),
        steps=steps,
    )

@app.route("/screenshot/<job_id>/<filename>")
def screenshot(job_id, filename):
    job_screenshots = screenshots.get(job_id, {})
    img_b64 = job_screenshots.get(filename)
    if not img_b64:
        return "Not found", 404
    img_bytes = base64.b64decode(img_b64)
    return send_file(io.BytesIO(img_bytes), mimetype="image/png")

@app.route("/download/<job_id>")
def download(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return "Not ready", 404
    job_screenshots = screenshots.get(job_id, {})
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for filename, img_b64 in sorted(job_screenshots.items()):
            zf.writestr(filename, base64.b64decode(img_b64))
    zip_buffer.seek(0)
    return send_file(zip_buffer, as_attachment=True, download_name="flow-screenshots.zip")

# ------------------------------------------------------------
# WORKER API ROUTES (called by your Mac)
# ------------------------------------------------------------

def check_secret():
    secret = request.headers.get("X-Worker-Secret", "")
    return secret == WORKER_SECRET

@app.route("/worker/jobs/pending", methods=["GET"])
def get_pending_jobs():
    """Worker polls this to get the next pending job."""
    if not check_secret():
        return jsonify({"error": "Unauthorized"}), 401
    pending = [
        {"job_id": jid, "url": j["url"], "goal": j["goal"]}
        for jid, j in jobs.items()
        if j["status"] == "pending"
    ]
    return jsonify({"jobs": pending})

@app.route("/worker/jobs/<job_id>/update", methods=["POST"])
def update_job(job_id):
    """Worker sends progress updates."""
    if not check_secret():
        return jsonify({"error": "Unauthorized"}), 401
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    data = request.json or {}
    jobs[job_id].update({
        "status": data.get("status", jobs[job_id]["status"]),
        "message": data.get("message", ""),
    })
    if data.get("log_line"):
        jobs[job_id]["log"].append(data["log_line"])
    return jsonify({"ok": True})

@app.route("/worker/jobs/<job_id>/complete", methods=["POST"])
def complete_job(job_id):
    """Worker posts final results including all screenshots."""
    if not check_secret():
        return jsonify({"error": "Unauthorized"}), 401
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    data = request.json or {}
    steps = data.get("steps", [])
    imgs = data.get("screenshots", {})  # {filename: base64}

    screenshots[job_id] = imgs
    jobs[job_id].update({
        "status": "done",
        "message": f"Done! {len(steps)} steps captured.",
        "step_count": len(steps),
        "steps": steps,
        "name": data.get("name", f"Flow: {jobs[job_id]['url']}"),
    })
    return jsonify({"ok": True})

@app.route("/worker/jobs/<job_id>/error", methods=["POST"])
def error_job(job_id):
    """Worker reports an error."""
    if not check_secret():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json or {}
    jobs[job_id].update({
        "status": "error",
        "message": data.get("message", "Unknown error"),
    })
    return jsonify({"ok": True})

# ------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"🌐 Server running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)