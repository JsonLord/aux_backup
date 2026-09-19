"""CAP-3: real links from the first Gradio tab into /webui.

`AUX_WEBUI_ENABLED` is read at module-import time in app.py, and Python only runs
that top-level code once per process -- so testing both the on and off state needs
two separate processes, not two calls inside one pytest run. Each assertion below
spawns app.py's import in a subprocess with the flag set the way it wants it.
"""
import subprocess
import sys

_PROBE = """
import sys
sys.argv = ["app.py"]
import app
import gradio as gr

buttons = {b.link: b for b in app.demo.blocks.values()
           if isinstance(b, gr.Button) and getattr(b, "link", None)}
webui = buttons.get("/webui")
developer = buttons.get("/webui#developer")
print("HAS_WEBUI_BUTTON", webui is not None)
print("HAS_DEVELOPER_BUTTON", developer is not None)
if webui is not None:
    print("ROW_VISIBLE", bool(webui.parent.visible))
"""


def _run(env_value):
    import os
    env = dict(os.environ)
    if env_value is None:
        env.pop("AUX_WEBUI_ENABLED", None)
    else:
        env["AUX_WEBUI_ENABLED"] = env_value
    result = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True,
                            text=True, env=env, timeout=90, cwd=".")
    assert result.returncode == 0, result.stderr[-4000:]
    return result.stdout


def test_the_links_exist_and_point_at_the_configuration_surface():
    """Real URLs, so each still works pasted to someone who isn't in this tab."""
    output = _run("1")
    assert "HAS_WEBUI_BUTTON True" in output
    assert "HAS_DEVELOPER_BUTTON True" in output


def test_the_links_are_hidden_not_disabled_when_the_surface_is_off():
    """A visible button to a 404 is worse than no button -- the same rule CAP-1's
    route registration follows, applied to what points at it."""
    enabled = _run("1")
    assert "ROW_VISIBLE True" in enabled

    disabled = _run(None)
    assert "ROW_VISIBLE False" in disabled
    # The buttons still exist in the graph -- hidden, not removed -- so a later
    # change that flips the flag at runtime would not need new wiring.
    assert "HAS_WEBUI_BUTTON True" in disabled
