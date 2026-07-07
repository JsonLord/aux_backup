import os
import subprocess
import time
import requests

def test_gitmcp():
    """Tests the connectivity of the GitMCP server."""
    url = "https://gitmcp.io/"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            print("GitMCP server is reachable.")
        else:
            print(f"GitMCP server returned status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to GitMCP server: {e}")

def test_hf_mcp_server():
    """Tests the connectivity of the Hugging Face MCP server."""
    # This test requires npx to be installed.
    server_command = "npx @llmindset/hf-mcp-server-http"
    process = None
    try:
        # Check if npx is installed
        subprocess.run(["npx", "-v"], check=True, capture_output=True)

        # Start the server in the background
        process = subprocess.Popen(server_command.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("Starting Hugging Face MCP server...")

        # Poll the server to see if it's running
        for _ in range(20): # Poll for 20 seconds
            try:
                response = requests.get("http://localhost:3000", timeout=1)
                if response.status_code == 200:
                    print("Hugging Face MCP server is running.")
                    return
            except requests.exceptions.RequestException:
                time.sleep(1)

        print("Hugging Face MCP server failed to start.")

    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"Error with Hugging Face MCP server: npx is likely not installed or the package is not found. {e}")
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Hugging Face MCP server: {e}")
    finally:
        if process:
            stdout, stderr = process.communicate()
            print("Hugging Face MCP server stdout:")
            print(stdout.decode())
            print("Hugging Face MCP server stderr:")
            print(stderr.decode())
            process.kill()
            print("Hugging Face MCP server stopped.")

def test_jules_api():
    """Tests the connectivity of the Jules API."""
    api_key = os.environ.get("JULES_API_KEY")
    if not api_key:
        print("JULES_API_KEY environment variable not set.")
        return

    url = "https://jules.googleapis.com/v1alpha/sources"
    headers = {"x-goog-api-key": api_key}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            print("Jules API is reachable.")
        elif response.status_code == 401:
            print("Jules API returned 401 Unauthorized. The API key may be invalid or expired.")
            print("This may also indicate that the API no longer supports API key authentication.")
        else:
            print(f"Jules API returned status code: {response.status_code}")
            print(f"Response content: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Jules API: {e}")

if __name__ == "__main__":
    test_gitmcp()
    test_hf_mcp_server()
    test_jules_api()
