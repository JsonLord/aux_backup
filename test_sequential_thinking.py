
import asyncio
import aiohttp
import json

async def test_sequential_thinking():
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "sequentialthinking",
            "arguments": {
                "thought": "This is a test thought to verify the endpoint functionality and formatting.",
                "nextThoughtNeeded": True,
                "thoughtNumber": 1,
                "totalThoughts": 5
            }
        }
    }
    
    url = "https://harvesthealth-sequential-thinking-mcp.hf.space/run"
    
    print(f"Testing endpoint: {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=30) as resp:
                status = resp.status
                print(f"Response Status: {status}")
                text = await resp.text()
                print(f"Raw Response Body: {text}")
                
                try:
                    res_json = await resp.json()
                    print(f"Parsed JSON: {json.dumps(res_json, indent=2)}")
                    
                    if "result" in res_json and "content" in res_json["result"]:
                        content_text = res_json["result"]["content"][0].get("text")
                        print(f"Inner Content Text: {content_text}")
                        # Try to parse the inner text as JSON if it looks like it
                        try:
                            inner_json = json.loads(content_text)
                            print(f"Parsed Inner JSON: {json.dumps(inner_json, indent=2)}")
                        except:
                            print("Inner content text is not JSON.")
                except Exception as e:
                    print(f"Failed to parse response as JSON: {e}")
                    
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_sequential_thinking())
