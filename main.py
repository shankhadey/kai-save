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

# Config
GITHUB_REPO = "shankhadey/kai-memory"
GITHUB_FILE = "memory.jsonl"
GITHUB_BRANCH = "main"


def decode_base64(data: str) -> str:
    """Decode urlsafe base64 with correct padding."""
    padding = (4 - len(data) % 4) % 4
    return base64.urlsafe_b64decode(data + "=" * padding).decode()


def get_github_token():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise HTTPException(500, "GitHub token not configured")
    return token


async def get_file_sha():
    """Get current file SHA (required for GitHub update)"""
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
    """Append content to memory.jsonl on GitHub"""
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

    return True


# Health check
@app.get("/")
def health():
    return {"status": "ok", "service": "kai-save"}


# AI-initiated save (via fetch, no user tap needed)
@app.get("/save")
async def ai_save(data: str):
    """AI calls this endpoint via fetch. Returns JSON confirmation."""
    try:
        decoded = decode_base64(data)
        items = json.loads(decoded)

        if not isinstance(items, list):
            items = [items]

        lines = []
        for item in items:
            if "id" in item and "type" in item:
                lines.append(json.dumps(item, separators=(",", ":")))

        if lines:
            await append_to_github("\n".join(lines))

        return {"status": "saved", "count": len(lines)}

    except json.JSONDecodeError:
        return {"status": "error", "message": "Invalid JSON"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# Single record save with success page
@app.get("/s/{data}", response_class=HTMLResponse)
async def save(data: str):
    try:
        decoded = decode_base64(data)
        record = json.loads(decoded)

        if "id" not in record or "type" not in record:
            raise ValueError("Missing id or type")

        await append_to_github(json.dumps(record, separators=(",", ":")))

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Saved</title>
            <style>
                body {{
                    font-family: -apple-system, sans-serif;
                    background: #0d0d0d;
                    color: #e5e5e5;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    min-height: 100vh;
                    margin: 0;
                }}
                .card {{
                    text-align: center;
                    padding: 40px;
                }}
                .check {{ font-size: 64px; margin-bottom: 16px; }}
                .type {{ color: #6366f1; font-size: 14px; margin-bottom: 8px; }}
                .content {{ color: #888; font-size: 14px; max-width: 300px; word-break: break-word; }}
                .redirect {{ margin-top: 16px; font-size: 12px; color: #666; }}
            </style>
            <script>
                setTimeout(function() {{
                    window.location.href = 'https://claude.ai';
                }}, 1200);
            </script>
        </head>
        <body>
            <div class="card">
                <div class="check">&#10003;</div>
                <div class="type">{record.get('type', 'item').upper()} SAVED</div>
                <div class="content">{record.get('content', record.get('name', record.get('id')))[:100]}</div>
                <div class="redirect">Returning to Claude...</div>
            </div>
        </body>
        </html>
        """

    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    except Exception as e:
        raise HTTPException(400, str(e))


# Batch save
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

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Saved</title>
            <style>
                body {{
                    font-family: -apple-system, sans-serif;
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
                .count {{ color: #6366f1; font-size: 18px; }}
                .redirect {{ margin-top: 16px; font-size: 12px; color: #666; }}
            </style>
            <script>
                setTimeout(function() {{
                    window.location.href = 'https://claude.ai';
                }}, 1200);
            </script>
        </head>
        <body>
            <div class="card">
                <div class="check">&#10003;</div>
                <div class="count">{len(saved)} items saved</div>
                <div class="redirect">Returning to Claude...</div>
            </div>
        </body>
        </html>
        """

    except Exception as e:
        raise HTTPException(400, str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
