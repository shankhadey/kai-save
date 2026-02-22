"""
Kai Save - Minimal memory write endpoint
Decodes base64 JSON from URL, appends to GitHub memory.jsonl
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import httpx
import base64
import json
import os

app = FastAPI(title="Kai Save")

GITHUB_REPO = "shankhadey/kai-memory"
GITHUB_FILE = "memory.jsonl"
GITHUB_BRANCH = "main"


def decode_base64(data: str) -> str:
    padding = (4 - len(data) % 4) % 4
    return base64.urlsafe_b64decode(data + "=" * padding).decode()


def get_github_token():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise HTTPException(500, "GitHub token not configured")
    return token


def return_page(title_line: str, subtitle: str = "") -> str:
    """Success page: tries Claude app deep link, falls back to claude.ai."""
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Saved</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            background: #0d0d0d;
            color: #e5e5e5;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }}
        .card {{ text-align: center; padding: 40px; }}
        .check {{ font-size: 64px; margin-bottom: 16px; }}
        .title {{ color: #6366f1; font-size: 18px; margin-bottom: 8px; }}
        .sub {{ color: #888; font-size: 14px; max-width: 280px; margin: 0 auto; word-break: break-word; }}
        .status {{ margin-top: 20px; font-size: 12px; color: #555; }}
    </style>
    <script>
        (function() {{
            var appOpened = false;

            // Cancel fallback if app opened (page loses visibility)
            function onHide() {{
                appOpened = true;
            }}
            document.addEventListener('visibilitychange', function() {{
                if (document.hidden) onHide();
            }});
            window.addEventListener('blur', onHide);
            window.addEventListener('pagehide', onHide);

            function tryOpen() {{
                var ua = navigator.userAgent || '';
                var isAndroid = /Android/i.test(ua);
                var isIOS = /iPhone|iPad|iPod/i.test(ua);

                // Try app deep link
                if (isAndroid) {{
                    // Intent URI — opens app if installed, silently fails if not
                    window.location = 'intent://open#Intent;scheme=claude;package=com.anthropic.claude;S.browser_fallback_url=https://claude.ai;end';
                }} else if (isIOS) {{
                    window.location = 'claude://';
                }}

                // Fallback: if app didn't open within 1.5s, go to web
                setTimeout(function() {{
                    if (!appOpened) {{
                        window.location.href = 'https://claude.ai';
                    }}
                }}, 1500);
            }}

            // Small delay so the page renders first
            setTimeout(tryOpen, 400);
        }})();
    </script>
</head>
<body>
    <div class="card">
        <div class="check">&#10003;</div>
        <div class="title">{title_line}</div>
        {f'<div class="sub">{subtitle}</div>' if subtitle else ''}
        <div class="status">Returning to Claude&hellip;</div>
    </div>
</body>
</html>"""


async def get_file_sha():
    token = get_github_token()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}?ref={GITHUB_BRANCH}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        })
    if response.status_code == 200:
        return response.json()["sha"], base64.b64decode(response.json()["content"]).decode()
    elif response.status_code == 404:
        return None, ""
    else:
        raise HTTPException(response.status_code, "Failed to fetch file from GitHub")


async def append_to_github(new_content: str):
    token = get_github_token()
    sha, existing = await get_file_sha()
    if existing and not existing.endswith("\n"):
        existing += "\n"
    updated = existing + new_content + "\n"

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    payload = {
        "message": "kai-save: memory update",
        "content": base64.b64encode(updated.encode()).decode(),
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha

    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }, json=payload)

    if response.status_code not in [200, 201]:
        raise HTTPException(response.status_code, f"GitHub commit failed: {response.text}")


@app.get("/")
def health():
    return {"status": "ok", "service": "kai-save"}


@app.get("/s/{data}", response_class=HTMLResponse)
async def save(data: str):
    try:
        decoded = decode_base64(data)
        record = json.loads(decoded)
        if "id" not in record or "type" not in record:
            raise ValueError("Missing id or type")
        await append_to_github(json.dumps(record, separators=(",", ":")))
        snippet = record.get("content", record.get("name", record.get("id")))[:80]
        return return_page(f"{record['type'].upper()} SAVED", snippet)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/b/{data}", response_class=HTMLResponse)
async def batch_save(data: str):
    try:
        decoded = decode_base64(data)
        lines = [l.strip() for l in decoded.strip().split("\n") if l.strip()]
        saved = []
        for line in lines:
            record = json.loads(line)
            if "id" in record and "type" in record:
                saved.append(json.dumps(record, separators=(",", ":")))
        if saved:
            await append_to_github("\n".join(saved))
        return return_page(f"{len(saved)} items saved")
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/save")
async def ai_save(data: str):
    """AI-initiated save via fetch. Returns JSON."""
    try:
        decoded = decode_base64(data)
        items = json.loads(decoded)
        if not isinstance(items, list):
            items = [items]
        lines = [json.dumps(i, separators=(",", ":")) for i in items if "id" in i and "type" in i]
        if lines:
            await append_to_github("\n".join(lines))
        return {"status": "saved", "count": len(lines)}
    except json.JSONDecodeError:
        return {"status": "error", "message": "Invalid JSON"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
