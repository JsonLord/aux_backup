"""Create/update a Docker Space from a local folder and print its build/runtime logs."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile

from huggingface_hub import HfApi, get_token


def resolve_token() -> str:
    """Return an environment or locally cached token without accepting secrets as CLI args."""
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN") or get_token()
    if not token:
        raise SystemExit(
            "Hugging Face authentication is required. Set HF_TOKEN or "
            "HUGGING_FACE_HUB_TOKEN, or run `hf auth login`; HF_USERNAME alone "
            "does not authenticate API requests."
        )
    return token


@contextmanager
def deployment_folder(folder: Path, full_repo: bool):
    """Build a temporary full-repository Space context with a deployment overlay."""
    if not full_repo:
        yield folder
        return
    repository = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="aux-hf-space-") as temporary:
        staged = Path(temporary)
        ignored = shutil.ignore_patterns(
            ".git", ".pytest_cache", "__pycache__", "node_modules", "external",
            "rendered_slides_output", "app.log", "*.pyc",
        )
        for source in repository.iterdir():
            if source.name in {".git", ".pytest_cache", "external", "rendered_slides_output"}:
                continue
            target = staged / source.name
            if source.is_dir():
                shutil.copytree(source, target, ignore=ignored)
            elif source.name != "app.log":
                shutil.copy2(source, target)
        for name in ("README.md", "Dockerfile", "requirements-live.txt", "start-live.sh"):
            source = folder / name
            target_name = "start-live.sh" if name == "start-live.sh" else name
            shutil.copy2(source, staged / target_name)
        yield staged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_id", help="Hugging Face Space ID, for example organization/aux-demo")
    parser.add_argument("--folder", default="spaces/aux-demo")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--full-repo", action="store_true",
                        help="stage the repository with the selected Space folder as its deployment overlay")
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    token = resolve_token()
    folder = Path(args.folder).resolve()
    if not (folder / "README.md").is_file() or not (folder / "Dockerfile").is_file():
        raise SystemExit(f"{folder} is not a Docker Space folder")
    api = HfApi(token=token)
    identity = api.whoami(token=token)
    print(f"Authenticated as: {identity['name']}")
    url = api.create_repo(args.repo_id, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)
    with deployment_folder(folder, args.full_repo) as upload_folder:
        commit = api.upload_folder(repo_id=args.repo_id, repo_type="space", folder_path=upload_folder,
                                   commit_message="Deploy AUX live application")
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
