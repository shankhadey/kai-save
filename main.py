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
                // Reset flag - events during cold-start load are stale
                appOpened = false;
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


def error_page(title: str, body: str) -> str:
    """Error page — no redirect, shows content for manual copy."""
    safe_body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Error</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            background: #0d0d0d;
            color: #e5e5e5;
            padding: 32px 24px;
            margin: 0;
        }}
        .icon {{ font-size: 48px; margin-bottom: 12px; }}
        h2 {{ color: #ef4444; margin: 0 0 16px; font-size: 18px; }}
        p {{ color: #888; font-size: 14px; margin: 0 0 16px; }}
        pre {{
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 16px;
            font-size: 13px;
            white-space: pre-wrap;
            word-break: break-word;
            color: #e5e5e5;
        }}
        .hint {{ color: #555; font-size: 12px; margin-top: 16px; }}
    </style>
</head>
<body>
    <div class="icon">&#10007;</div>
    <h2>{title}</h2>
    <p>Add this manually to <strong>instructions.md</strong> on GitHub:</p>
    <pre>{safe_body}</pre>
    <p class="hint">Do not close this page until you have copied the text.</p>
</body>
</html>"""


async def get_any_file(filename: str):
    """Fetch any file from the repo by name."""
    token = get_github_token()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}?ref={GITHUB_BRANCH}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        })
    if response.status_code == 200:
        data = response.json()
        return data["sha"], base64.b64decode(data["content"]).decode()
    elif response.status_code == 404:
        return None, ""
    else:
        raise HTTPException(response.status_code, f"Failed to fetch {filename}")


async def write_file(filename: str, sha: str, content: str, message: str):
    """Write any file to the repo."""
    token = get_github_token()
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
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


@app.get("/patch/{data}", response_class=HTMLResponse)
async def patch_file(data: str):
    """
    Find-and-replace in any repo file.
    Payload: {file, find, replace, msg?}
    - file: filename in repo (e.g. "instructions.md")
    - find: exact string to find (must match exactly once)
    - replace: string to substitute in
    - msg: optional commit message
    """
    try:
        decoded = decode_base64(data)
        payload = json.loads(decoded)

        filename = payload.get("file")
        find_str = payload.get("find")
        replace_str = payload.get("replace")
        commit_msg = payload.get("msg", f"kai-save: patch {filename}")

        if not all([filename, find_str is not None, replace_str is not None]):
            return HTMLResponse(error_page(
                "Invalid patch payload",
                "Missing required fields: file, find, replace"
            ), status_code=400)

        sha, content = await get_any_file(filename)

        if sha is None:
            return HTMLResponse(error_page(
                f"File not found: {filename}",
                replace_str
            ), status_code=404)

        count = content.count(find_str)
        if count == 0:
            return HTMLResponse(error_page(
                f"Find string not found in {filename}",
                f"CONTENT TO ADD MANUALLY:\n\n{replace_str}\n\n---\nFind string that failed:\n{find_str}"
            ), status_code=422)

        if count > 1:
            return HTMLResponse(error_page(
                f"Find string matched {count} times in {filename} (must match exactly once)",
                f"CONTENT TO ADD MANUALLY:\n\n{replace_str}\n\n---\nAmbiguous find string:\n{find_str}"
            ), status_code=422)

        updated = content.replace(find_str, replace_str, 1)
        await write_file(filename, sha, updated, commit_msg)

        # Extract just the new text for the success subtitle
        new_text = replace_str.replace(find_str, "").strip()[:80]
        return HTMLResponse(return_page(f"{filename} PATCHED", new_text))

    except json.JSONDecodeError:
        return HTMLResponse(error_page("Invalid JSON in payload", ""), status_code=400)
    except Exception as e:
        return HTMLResponse(error_page("Patch failed", str(e)), status_code=500)


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
