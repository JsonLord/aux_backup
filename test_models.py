import asyncio
import os
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch
import sys

# Mock modules
sys.modules['gradio'] = MagicMock()
sys.modules['git'] = MagicMock()

import app
from langchain_core.messages import AIMessage

async def test_persona_models():
    # Reset model mocks if they were set
    # In app.py:
    # extraction_llm = large_llm if persona == "mentor" else fast_llm

    app.huge_llm = MagicMock()
    app.get_ideation_logs = MagicMock(return_value=[])

    # Mock ainvoke_with_retry to check which LLM is called
    called_llms = []
    async def mock_invoke(llm, prompt, **kwargs):
        called_llms.append(llm)
        return AIMessage(content="Extracted")

    with patch("app.ainvoke_with_retry", side_effect=mock_invoke), \
         patch("os.makedirs"), patch("builtins.open", MagicMock()):

        # Mentor Persona
        print("Testing Mentor extraction (should use huge_llm)...")
        await app.handle_close_ideate([{"role": "user", "content": "hi"}], persona="mentor")
        # In handle_close_ideate, it makes 8 calls
        assert all(l == app.huge_llm for l in called_llms[:8])

        called_llms.clear()

        # Planning Persona
        print("Testing Planning extraction (should use huge_llm)...")
        await app.handle_close_ideate([{"role": "user", "content": "hi"}], persona="planning")
        assert all(l == app.huge_llm for l in called_llms[:8])

    print("Persona model selection test PASSED!")

if __name__ == "__main__":
    asyncio.run(test_persona_models())
