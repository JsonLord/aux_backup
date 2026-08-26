"""Create/update a Docker Space from a local folder and print its build/runtime logs."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from huggingface_hub import HfApi


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_id", help="Hugging Face Space ID, for example organization/aux-demo")
    parser.add_argument("--folder", default="spaces/aux-demo")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN or HUGGING_FACE_HUB_TOKEN is required")
    folder = Path(args.folder).resolve()
    if not (folder / "README.md").is_file() or not (folder / "Dockerfile").is_file():
        raise SystemExit(f"{folder} is not a Docker Space folder")
    api = HfApi(token=token)
    url = api.create_repo(args.repo_id, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)
    commit = api.upload_folder(repo_id=args.repo_id, repo_type="space", folder_path=folder,
                               commit_message="Deploy AUX local-folder contract demo")
    print(f"Space: {url}")
    print(f"Commit: {commit.oid}")
    print("\n--- build logs ---")
    for line in api.fetch_space_logs(args.repo_id, build=True, follow=False, token=token):
        print(line, end="" if line.endswith("\n") else "\n")
    runtime = api.wait_for_space(args.repo_id, timeout=args.timeout, token=token)
    print(f"\nRuntime stage: {runtime.stage}")
    print("\n--- runtime logs ---")
    for line in api.fetch_space_logs(args.repo_id, build=False, follow=False, token=token):
        print(line, end="" if line.endswith("\n") else "\n")


if __name__ == "__main__":
    main()
