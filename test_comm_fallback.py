import asyncio
import os
import json
from unittest.mock import AsyncMock, MagicMock, patch
import sys

# Mock gradio
sys.modules['gradio'] = MagicMock()
# Mock git
sys.modules['git'] = MagicMock()

import app

async def test_jules_comm_fallbacks():
    # Mocking get_all_tools and run_manual_agent
    app.get_all_tools = AsyncMock(return_value=[MagicMock(name="create_session")])
    
    async def mock_run_manual_agent(*args, **kwargs):
        # We check the prompt in messages
        messages = args[2]
        system_msg = args[3]
        
        # system_msg in handle_jules_comm is fixed, we care about prompt in messages
        prompt_content = messages[0].content
        print(f"Agent Prompt: {prompt_content}")
        
        # Check if fallback values are present in the prompt
        assert "hf upload fallback_prof/fallback_space" in prompt_content
        assert "fallback_token" in prompt_content
        
        yield "Thinking...", None
        yield "Created session sessions/123", "sessions/123"

    app.run_manual_agent = mock_run_manual_agent
    
    # Test with manual fallbacks and no log file
    await app.handle_jules_comm(
        repo_url="https://github.com/owner/repo",
        branch="main",
        log_file="",
        hf_prof_fallback="fallback_prof",
        hf_space_fallback="fallback_space",
        hf_token_fallback="fallback_token"
    )
    
    print("\nJules communication fallback test PASSED!")

if __name__ == "__main__":
    asyncio.run(test_jules_comm_fallbacks())
