import asyncio
import os
import shutil
from unittest.mock import MagicMock
import sys

# Mock gradio
sys.modules['gradio'] = MagicMock()
import gradio as gr

# Mock other modules not needed for this test
sys.modules['git'] = MagicMock()

import app

async def test_log_refresh():
    # Setup a temporary log directory
    test_log_dir = "/tmp/test_ideation_logs"
    if os.path.exists(test_log_dir):
        shutil.rmtree(test_log_dir)
    os.makedirs(test_log_dir)
    
    app.LOG_DIR = test_log_dir
    
    # Create some dummy log folders
    os.makedirs(os.path.join(test_log_dir, "log_1"))
    os.makedirs(os.path.join(test_log_dir, "log_2"))
    
    # Run refresh_logs_ui
    update1, update2 = await app.refresh_logs_ui()
    
    # Check choices (Gradio update object stores choices in a dict or as an attribute)
    # In recent Gradio versions, it might be a dict or a dataclass-like object
    print(f"Update 1: {update1}")
    
    # Since we mocked gr.update, it returns a MagicMock
    # We should actually check what get_ideation_logs returns
    logs = app.get_ideation_logs()
    print(f"Logs found: {logs}")
    
    assert "log_1" in logs
    assert "log_2" in logs
    assert len(logs) == 2
    
    # Add a third log and refresh again
    os.makedirs(os.path.join(test_log_dir, "log_3"))
    logs = app.get_ideation_logs()
    print(f"Logs found after update: {logs}")
    assert "log_3" in logs
    assert len(logs) == 3
    
    print("\nLog refresh test PASSED!")

if __name__ == "__main__":
    asyncio.run(test_log_refresh())
