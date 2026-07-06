import os
import re

def verify_app_logic():
    with open("app.py", "r") as f:
        content = f.read()

    # Check IFrame src
    iframe_match = re.search(r'iframe src="/file=\{abspath\}"', content)
    if iframe_match:
        print("PASS: IFrame src format is correct.")
    else:
        print("FAIL: IFrame src format is incorrect.")

    # Check allowed_paths
    allowed_paths_match = re.search(r'allowed_paths=\["/app"\]', content)
    if allowed_paths_match:
        print("PASS: allowed_paths is restricted to /app.")
    else:
        print("FAIL: allowed_paths is not restricted correctly.")

    # Check branch name
    branch_match = re.search(r'fix/jules-final-submission-branch', content)
    if branch_match:
        print("PASS: Branch name includes 'jules' as requested.")
    else:
        print("FAIL: Branch name does not include 'jules'.")

if __name__ == "__main__":
    verify_app_logic()
