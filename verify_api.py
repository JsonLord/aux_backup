import requests
import time
import subprocess
import os

def test_api_endpoints():
    print("Starting application in background...")
    env = os.environ.copy()
    env["GITHUB_TOKEN"] = "mock_token"
    # Run app.py in background
    process = subprocess.Popen(["python3", "app.py"], env=env)

    # Wait for startup
    time.sleep(10)

    try:
        print("Testing /health endpoint...")
        res = requests.get("http://localhost:7860/health")
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        print("Testing /api/info endpoint...")
        res = requests.get("http://localhost:7860/api/info")
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.status_code == 200
        assert "UX Analysis Orchestrator" in res.json()["app"]

        print("API tests PASSED!")
    finally:
        print("Killing application...")
        process.terminate()

if __name__ == "__main__":
    test_api_endpoints()
