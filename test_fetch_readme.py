import asyncio
import os
import requests

def parse_github_repo_id(input_str):
    if not input_str: return "", ""
    input_str = input_str.strip().strip("/")
    if "github.com/" in input_str:
        import re
        match = re.search(r'github\.com/([^/\s]+)/([^/\s.]+)', input_str)
        if match:
            repo = match.group(2)
            if repo.endswith(".git"): repo = repo[:-4]
            return match.group(1), repo
    if "/" in input_str:
        parts = input_str.split("/")
        if len(parts) >= 2:
            repo = parts[-1]
            if repo.endswith(".git"): repo = repo[:-4]
            return parts[-2], repo
    return "", input_str.replace(".git", "")

async def fetch_readme(repo_url_input, branch="main"):
    owner, repo = parse_github_repo_id(repo_url_input)
    headers = {"Accept": "application/vnd.github.v3.raw"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/README.md?ref={branch}"
    print(f"Fetching {url}...")
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.text
    else:
        print(f"Status: {response.status_code}, Text: {response.text[:100]}")
    return ""

async def main():
    content = await fetch_readme("langchain-ai/langchain", branch="master")
    if content:
        print("Success!")
    else:
        print("Failed.")

if __name__ == "__main__":
    asyncio.run(main())
