import asyncio
import os
import json
from unittest.mock import MagicMock
import sys

# Mock gradio
sys.modules['gradio'] = MagicMock()
# Mock git
sys.modules['git'] = MagicMock()

import app

def test_tool_injector():
    # We need to simulate the inner function of handle_jules_comm
    # Since tool_injector is defined inside handle_jules_comm, we can't access it directly easily.
    # However, I can create a standalone version of the logic to test it.
    
    repo_url = "sources/github/owner/repo"
    branch = "main"
    jules_task = "MANDATORY TASK"

    def tool_injector(tool_name, params):
        if tool_name == "create_session":
            # Map common hallucinations
            if "path" in params and not params.get("source"): params["source"] = params["path"]
            if "source_path" in params and not params.get("source"): params["source"] = params["source_path"]
            if "repo" in params and not params.get("source"): params["source"] = params["repo"]
            if "task" in params and not params.get("prompt"): params["prompt"] = params["task"]

            if not params.get("source"): params["source"] = repo_url
            if not params.get("branch"): params["branch"] = branch
            if not params.get("prompt"): params["prompt"] = jules_task
            
        if tool_name in ["send_message", "sendMessage"]:
             if "message" in params and not params.get("prompt"): params["prompt"] = params["message"]
             
        return params

    # Test cases for create_session
    t1 = tool_injector("create_session", {"path": "my/path", "branch": "dev"})
    assert t1["source"] == "my/path"
    assert t1["branch"] == "dev"
    assert t1["prompt"] == jules_task
    
    t2 = tool_injector("create_session", {"source_path": "other/path", "task": "custom task"})
    assert t2["source"] == "other/path"
    assert t2["prompt"] == "custom task"
    
    t3 = tool_injector("create_session", {"repo": "some/repo"})
    assert t3["source"] == "some/repo"
    
    t4 = tool_injector("create_session", {})
    assert t4["source"] == repo_url
    assert t4["prompt"] == jules_task
    
    # Test cases for send_message
    m1 = tool_injector("send_message", {"session_id": "s1", "message": "hello"})
    assert m1["prompt"] == "hello"
    
    m2 = tool_injector("sendMessage", {"session_id": "s1", "message": "world"})
    assert m2["prompt"] == "world"

    print("Tool injector logic test PASSED!")

if __name__ == "__main__":
    test_tool_injector()
