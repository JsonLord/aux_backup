import os
import httpx
import asyncio
import json

async def check_jules():
    api_key = os.environ.get("JULES_API_KEY")
    if not api_key:
        print("JULES_API_KEY not set")
        return

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json"
    }
    url = "https://jules.googleapis.com/v1alpha/sources"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            print(f"Status Code: {response.status_code}")
            print(f"Response: {json.dumps(response.json(), indent=2)}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_jules())
