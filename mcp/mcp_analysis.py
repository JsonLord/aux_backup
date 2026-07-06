from mcp.server.fastmcp import FastMCP
import httpx
import os
import logging
import json
import subprocess
import asyncio
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-analysis")

mcp = FastMCP("analysis")

API_BASE_URL = "https://analysis.googleapis.com/v1alpha"

class AnalysisClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = API_BASE_URL
        self.headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }

    async def _request(self, method: str, path: str, **kwargs):
        # Handle session_id prefixing
        if path.startswith("/sessions/sessions/"):
            path = path.replace("/sessions/sessions/", "/sessions/")

        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, headers=self.headers, **kwargs)
            if response.status_code not in (200, 204):
                logger.error(f"Jules API Error ({method} {path}): {response.status_code} - {response.text}")
            response.raise_for_status()
            return response.json() if response.text else {}

    async def list_sources(self):
        return await self._request("GET", "/sources")

    async def get_source(self, name: str):
        if not name.startswith("sources/"): name = f"sources/{name}"
        return await self._request("GET", f"/{name}")

    async def create_session(self, prompt, source, branch="main", title="API Session", automation="AUTO_CREATE_PR"):
        # Format source for API if it is just owner/repo
        if "/" in source and "sources/github/" not in source:
             source = f"sources/github/{source}"

        payload = {
            "prompt": prompt,
            "sourceContext": {
                "source": source,
                "githubRepoContext": {"startingBranch": branch}
            }
        }
        if title: payload["title"] = title
        if automation: payload["automationMode"] = automation

        logger.info(f"Creating session with payload: {json.dumps(payload)}")
        try:
            return await self._request("POST", "/sessions", json=payload)
        except Exception as e:
            err_msg = str(e).lower()
            if "maximum number of sessions" in err_msg or "max sessions reached" in err_msg or "400" in err_msg:
                logger.warning(f"Possible quota/session limit error detected: {e}. Triggering early key rotation.")
                force_rotate_key()
                return {"error": f"Session creation failed: {e}. API key has been rotated. Please retry."}

            logger.warning(f"REST API create_session failed: {e}. Falling back to CLI.")
            cli_source = source.replace("sources/github/", "")
            return await self.create_session_cli(prompt, cli_source, branch, title)

    async def create_session_cli(self, prompt, source, branch="main", title="API Session"):
        """Fallback to analysis CLI for session creation."""
        logger.info(f"Using analysis CLI to create session for {source}")
        cmd = [
            "analysis", "new",
            "--repo", source,
            prompt
        ]
        env = os.environ.copy()
        env["JULES_API_KEY"] = self.api_key
        npm_bin = subprocess.check_output(["npm", "config", "get", "prefix"]).decode().strip() + "/bin"
        env["PATH"] = f"{env.get('PATH', '')}:{npm_bin}"

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
            )
            stdout, stderr = await process.communicate()
            output = stdout.decode().strip()
            match = re.search(r'sessions/(\d+)', output)
            if match:
                s_id = match.group(0)
                return {"name": s_id, "id": match.group(1)}
            return {"output": output}
        except:
            return {"error": "CLI failed"}

    async def get_session(self, session_id):
        session_id = str(session_id).strip()
        if not session_id.startswith("sessions/"): session_id = f"sessions/{session_id}"
        return await self._request("GET", f"/{session_id}")

    async def list_sessions(self, page_size=30):
        return await self._request("GET", "/sessions", params={"pageSize": page_size})

    async def send_message(self, session_id, prompt):
        session_id = str(session_id).strip()
        if not session_id.startswith("sessions/"): session_id = f"sessions/{session_id}"
        return await self._request("POST", f"/{session_id}:sendMessage", json={"prompt": prompt})

    async def approve_plan(self, session_id):
        session_id = str(session_id).strip()
        if not session_id.startswith("sessions/"): session_id = f"sessions/{session_id}"
        return await self._request("POST", f"/{session_id}:approvePlan", json={})

    async def get_activity(self, name: str):
        name = str(name).strip()
        return await self._request("GET", f"/{name}")

    async def list_activities(self, session_id, page_size=50):
        session_id = str(session_id).strip()
        if not session_id.startswith("sessions/"): session_id = f"sessions/{session_id}"
        return await self._request("GET", f"/{session_id}/activities", params={"pageSize": page_size})

# API Key Rotation State
REQUEST_COUNT = 0
CURRENT_KEY_INDEX = 0

def force_rotate_key():
    """Immediately switch to the next available API key and reset counter."""
    global REQUEST_COUNT, CURRENT_KEY_INDEX
    keys = [os.environ.get("JULES_API_KEY"), os.environ.get("JULES_API_KEY_FALLBACK")]
    keys = [k for k in keys if k]
    if len(keys) > 1:
        CURRENT_KEY_INDEX = (CURRENT_KEY_INDEX + 1) % len(keys)
        REQUEST_COUNT = 0
        logger.info(f"FORCE ROTATION: Switched to Jules API Key index {CURRENT_KEY_INDEX}")

def get_rotated_api_key():
    global REQUEST_COUNT, CURRENT_KEY_INDEX
    keys = [os.environ.get("JULES_API_KEY"), os.environ.get("JULES_API_KEY_FALLBACK")]
    # Filter out None or empty keys
    keys = [k for k in keys if k]
    if not keys:
        logger.error("No Jules API keys found in environment.")
        return None

    key = keys[CURRENT_KEY_INDEX]

    REQUEST_COUNT += 1
    if REQUEST_COUNT >= 3:
        REQUEST_COUNT = 0
        old_index = CURRENT_KEY_INDEX
        CURRENT_KEY_INDEX = (CURRENT_KEY_INDEX + 1) % len(keys)
        if len(keys) > 1 and old_index != CURRENT_KEY_INDEX:
            logger.info(f"Requests per key reached. Rotating Jules API Key from index {old_index} to {CURRENT_KEY_INDEX}")

    return key

def get_client():
    key = get_rotated_api_key()
    return AnalysisClient(key)

@mcp.tool()
async def list_sources():
    """List all available sources (repositories)."""
    return await get_client().list_sources()

@mcp.tool()
async def get_source(name: str):
    """
    Get details about a specific source.
    :param name: The source name (e.g., 'sources/github/owner/repo').
    """
    return await get_client().get_source(name)

@mcp.tool()
async def create_session(
    prompt: str,
    source: str,
    branch: str = "main",
    title: str = "API Session",
    automation_mode: str = "AUTO_CREATE_PR"
):
    """
    Initialize a new autonomous coding session for a repository.

    Args:
        prompt: The implementation task or instructions for Jules.
        source: Source repository path (e.g., 'sources/github/owner/repo').
        branch: The branch to use.
        title: Title for the session.
        automation_mode: Defaults to 'AUTO_CREATE_PR'.
    """
    return await get_client().create_session(prompt, source, branch, title, automation_mode)

@mcp.tool()
async def get_session(session_id: str):
    """
    Get the current status and details of a session.
    :param session_id: The session ID (e.g., 'sessions/123').
    """
    return await get_client().get_session(session_id)

@mcp.tool()
async def list_sessions(page_size: int = 30):
    """List recent Jules sessions."""
    return await get_client().list_sessions(page_size)

@mcp.tool()
async def send_message(session_id: str, prompt: str):
    """
    Send a message or feedback to an existing session.
    :param session_id: The session ID (e.g., 'sessions/123').
    :param prompt: The message/instruction text.
    """
    return await get_client().send_message(session_id, prompt)

@mcp.tool()
async def approve_plan(session_id: str):
    """
    Approve the implementation plan for a session.
    :param session_id: The session ID.
    """
    return await get_client().approve_plan(session_id)

@mcp.tool()
async def get_activity(name: str):
    """
    Get details about a specific activity.
    :param name: Activity resource name (e.g., 'sessions/123/activities/456').
    """
    return await get_client().get_activity(name)

@mcp.tool()
async def list_activities(session_id: str, page_size: int = 50):
    """
    List activities for a specific session.
    :param session_id: The session ID.
    :param page_size: Number of activities to return.
    """
    return await get_client().list_activities(session_id, page_size)

if __name__ == "__main__": mcp.run()
