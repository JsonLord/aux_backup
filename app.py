import os
import sys

import subprocess
import re
import time
import json
import concurrent.futures
import uuid
import shutil
from gradio_client import Client
from datetime import datetime
from apps.gradio.api_client import ControlPlaneClient, PersonaRuntimeClient

import gradio as gr
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
from github import Github, Auth
import requests
from openai import OpenAI
import logging

# Configuration from environment variables
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_API_TOKEN") or os.environ.get("GITHUB_API_KEY")
BLABLADOR_API_KEY = os.environ.get("BLABLADOR_API_KEY")
BLABLADOR_BASE_URL = "https://api.helmholtz-blablador.fz-juelich.de/v1"
control_plane = ControlPlaneClient()
persona_runtime = PersonaRuntimeClient()

# GitHub Client
gh = Github(auth=Auth.Token(GITHUB_TOKEN)) if GITHUB_TOKEN else None
REPO_NAME = "JsonLord/tiny_web"
POOL_REPO_NAME = "JsonLord/agent-notes"
POOL_PATH = "PersonaPool"

# Better summaries for example personas
BETTER_SUMMARIES = {
    "Friedrich_Wolf.agent.json": "A meticulous German architect at Awesome Inc. He focuses on standardizing apartment designs, favoring quality over cost, and can be confrontational when challenged.",
    "Lila.agent.json": "A freelance linguist from Paris specializing in NLP. She is highly analytical, creative, and excels at anticipating user behavior from ambiguous data.",
    "Oscar.agent.json": "A German architect at Awesome Inc. who balances professional excellence with a witty sense of humor. He is detail-oriented and dedicated to sustainable design.",
    "Sophie_Lefevre.agent.json": "A creative professional likely focused on the aesthetic and emotional aspects of design and user experience.",
    "Marcos.agent.json": "A technically-minded individual who prioritizes efficiency and robust, logical solutions in the products he uses.",
    "Lisa.agent.json": "A standard user persona interested in efficiency and clear communication.",
    "Jane_Smith.md": "Standard, versatile persona representing a broad range of consumer behaviors and expectations.",
    "John_Doe.md": "Standard, versatile persona representing a broad range of consumer behaviors and expectations."
}

# Global state for processed reports
processed_prs = set()
all_discovered_reports = ""
github_logs = []

# Slide rendering configuration
SLIDES_OUTPUT_ROOT = os.path.join(os.getcwd(), "rendered_slides_output")
os.makedirs(SLIDES_OUTPUT_ROOT, exist_ok=True)

def add_log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    github_logs.append(log_entry)
    print(log_entry)
    return "\n".join(github_logs[-20:])

# Helper for parallel LLM calls
def call_llm_parallel(client, model_names, messages, **kwargs):
    def make_call(model_name):
        try:
            print(f"Parallel call attempting: {model_name}")
            return client.chat.completions.create(
                model=model_name,
                messages=messages,
                **kwargs
            )
        except Exception as e:
            print(f"Parallel call error from {model_name}: {e}")
            return e

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(model_names)) as executor:
        futures = {executor.submit(make_call, m): m for m in model_names}
        # Wait for the first success that isn't a 502/Proxy Error
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if not isinstance(res, Exception):
                print(f"Parallel call success from: {futures[future]}")
                # Try to cancel others (not always possible but good practice)
                return res
            else:
                # If it's an error, check if we should keep waiting or if all failed
                pass

    return Exception("All parallel calls failed")

# BLABLADOR Client for task generation
def get_blablador_client():
    if not BLABLADOR_API_KEY:
        return None
    return OpenAI(
        api_key=BLABLADOR_API_KEY,
        base_url=BLABLADOR_BASE_URL
    )

def get_user_repos(github_client=None):
    client = github_client or gh
    add_log("Fetching user repositories...")
    if not client:
        add_log("ERROR: GitHub client not initialized.")
        return ["JsonLord/tiny_web"]
    try:
        user = client.get_user()
        repos = [repo.full_name for repo in user.get_repos()]
        add_log(f"Found {len(repos)} repositories.")
        if "JsonLord/tiny_web" not in repos:
            repos.append("JsonLord/tiny_web")
        return sorted(repos)
    except Exception as e:
        add_log(f"ERROR fetching repos: {e}")
        return ["JsonLord/tiny_web"]

def get_repo_branches(repo_full_name, github_client=None):
    client = github_client or gh
    add_log(f"Fetching branches for {repo_full_name}...")
    if not client:
        add_log("ERROR: GitHub client is None.")
        return ["main"]
    if not repo_full_name:
        return ["main"]
    try:
        repo = client.get_repo(repo_full_name)
        # Fetch branches
        branches = list(repo.get_branches())
        add_log(f"Discovered {len(branches)} branches.")
        
        # Use ThreadPool to fetch commit dates in parallel to be MUCH faster
        branch_info = []
        
        def fetch_branch_date(b):
            try:
                commit = repo.get_commit(b.commit.sha)
                # Try multiple ways to get the date
                date = None
                if commit.commit and commit.commit.author:
                    date = commit.commit.author.date
                elif commit.commit and commit.commit.committer:
                    date = commit.commit.committer.date
                
                if not date:
                    date = datetime.min
                return (b.name, date)
            except Exception as e:
                return (b.name, datetime.min)

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            branch_info = list(executor.map(fetch_branch_date, branches))
        
        # Sort by date descending
        branch_info.sort(key=lambda x: x[1], reverse=True)
        result = [b[0] for b in branch_info]
        
        if result:
            add_log(f"Successfully sorted {len(result)} branches. Latest: {result[0]}")
        
        return result
    except Exception as e:
        add_log(f"ERROR fetching branches: {e}")
        import traceback
        traceback.print_exc()
        return ["main"]

def get_persona_pool():
    if not gh:
        return []
    try:
        repo = gh.get_repo(POOL_REPO_NAME)
        contents = repo.get_contents(POOL_PATH)
        pool = []
        for content_file in contents:
            if content_file.name.endswith(".json"):
                file_content = content_file.decoded_content.decode("utf-8")
                pool.append(json.loads(file_content))
        return pool
    except Exception as e:
        print(f"Error fetching persona pool: {e}")
        return []

def get_example_personas():
    example_path = "external/TinyTroupe/examples/agents/"
    if not os.path.exists(example_path):
        return []
    try:
        files = [f for f in os.listdir(example_path) if f.endswith(".json") or f.endswith(".md")]
        return sorted(files)
    except Exception as e:
        print(f"Error listing example personas: {e}")
        return []

def upload_persona_to_pool(persona_data):
    if not gh:
        return
    try:
        repo = gh.get_repo(POOL_REPO_NAME)
        name = persona_data.get("name", "unknown").replace(" ", "_")
        file_path = f"{POOL_PATH}/{name}.json"
        content = json.dumps(persona_data, indent=4)

        try:
            # Check if file exists to get its sha
            existing_file = repo.get_contents(file_path)
            repo.update_file(file_path, f"Update persona: {name}", content, existing_file.sha)
        except:
            # Create new file
            repo.create_file(file_path, f"Add persona: {name}", content)
        print(f"Uploaded persona {name} to pool.")
    except Exception as e:
        print(f"Error uploading persona to pool: {e}")

def select_or_create_personas(theme, customer_profile, num_personas, force_method=None, example_file=None):
    if force_method == "Example Persona" and example_file:
        add_log(f"Loading example persona from {example_file}...")
        try:
            path = os.path.join("external/TinyTroupe/examples/agents/", example_file)
            if example_file.endswith(".json"):
                with open(path, "r") as f:
                    data = json.load(f)
                
                name = data.get("name") or data.get("persona", {}).get("name") or "Unknown"
                bio = BETTER_SUMMARIES.get(example_file)
                if not bio:
                    bio = data.get("mental_faculties", [{}])[0].get("context") if "mental_faculties" in data else "An example persona."
                
                # Adapt TinyTroupe format to our internal format
                persona = {
                    "name": name,
                    "minibio": bio,
                    "persona": data
                }
            else: # .md
                with open(path, "r") as f:
                    content = f.read()
                name = example_file.replace(".md", "").replace("_", " ")
                bio = BETTER_SUMMARIES.get(example_file) or content
                persona = {
                    "name": name,
                    "minibio": bio,
                    "persona": {"name": name, "background": content}
                }
            return [persona] * int(num_personas)
        except Exception as e:
            add_log(f"Failed to load example persona: {e}")

    if force_method == "DeepPersona":
        add_log("Forcing DeepPersona generation...")
        personas = []
        for i in range(int(num_personas)):
            p = generate_persona_from_deeppersona(theme, customer_profile)
            if p: personas.append(p)
        if len(personas) >= int(num_personas): return personas[:int(num_personas)]
        # fallback if some failed
        num_personas = int(num_personas) - len(personas)
    elif force_method == "TinyTroupe":
        add_log("Forcing TinyTroupe generation...")
        return persona_runtime.generate(theme, customer_profile, num_personas, scenario=theme)

    client = get_blablador_client()
    if not client:
        return generate_personas(theme, customer_profile, num_personas)

    pool = get_persona_pool()
    if not pool:
        print("Pool is empty, generating new personas.")
        new_personas = generate_personas(theme, customer_profile, num_personas)
        for p in new_personas:
            upload_persona_to_pool(p)
        return new_personas

    # Ask LLM to judge
    pool_summaries = [{"index": i, "name": p["name"], "minibio": p.get("minibio", "")} for i, p in enumerate(pool)]

    prompt = f"""
    You are an expert in user experience research and persona management.
    We need {num_personas} persona(s) for a UX analysis task with the following theme: {theme}
    And target customer profile: {customer_profile}

    Here is a pool of existing personas:
    {json.dumps(pool_summaries, indent=2)}

    For each of the {num_personas} required personas, decide if one from the pool is an appropriate match or if we should create a new one.
    An appropriate match is a persona whose background, interests, and characteristics align well with the target customer profile and theme.

    Return your decision as a JSON object with the following format:
    {{
        "decisions": [
            {{ "action": "use_pool", "pool_index": 0 }},
            {{ "action": "create_new" }},
            ... (up to {num_personas})
        ]
    }}
    """

    try:
        response = client.chat.completions.create(
            model="alias-huge",
            messages=[{"role": "user", "content": prompt}]
        )
        content = response.choices[0].message.content
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            decisions_json = json.loads(json_match.group())
            decisions = decisions_json.get("decisions", [])
        else:
            print("Could not parse LLM decision, creating new personas.")
            decisions = [{"action": "create_new"}] * num_personas
    except Exception as e:
        print(f"Error getting LLM decision: {e}, creating new personas.")
        decisions = [{"action": "create_new"}] * num_personas

    final_personas = []
    to_create_count = 0
    for d in decisions:
        if d["action"] == "use_pool" and 0 <= d["pool_index"] < len(pool):
            print(f"Using persona from pool: {pool[d['pool_index']]['name']}")
            final_personas.append(pool[d['pool_index']])
        else:
            to_create_count += 1

    if to_create_count > 0:
        print(f"Creating {to_create_count} new personas.")
        newly_created = generate_personas(theme, customer_profile, to_create_count)
        for p in newly_created:
            upload_persona_to_pool(p)
            final_personas.append(p)

    return final_personas

def generate_persona_from_deeppersona(theme, customer_profile):
    add_log("Attempting persona generation from THzva/deeppersona-experience...")
    client = get_blablador_client()
    if not client:
        return None

    # Step 1: Breakdown profile into parameters using LLM alias-huge
    prompt = f"""
    You are an expert in persona creation. 
    Break down the following business theme and customer profile into detailed attributes for a persona.
    Business Theme: {theme}
    Target Customer Profile: {customer_profile}

    Return a JSON object with exactly these fields:
    - age (int)
    - gender (string)
    - occupation (string)
    - city (string)
    - country (string)
    - custom_values (string, e.g., "Sustainability, Innovation")
    - custom_life_attitude (string, e.g., "Optimistic and forward-thinking")
    - life_story (string, a brief background)
    - interests_hobbies (string, comma separated)
    - name (string, full name)

    CRITICAL: Return ONLY the JSON object.
    """

    try:
        response = client.chat.completions.create(
            model="alias-huge",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        params = json.loads(response.choices[0].message.content)
        add_log(f"Profile breakdown complete for {params.get('name')}")

        # Step 2: Call the DeepPersona generation endpoint
        gr_client = Client("THzva/deeppersona-experience")
        result = gr_client.predict(
                age=float(params.get("age", 30)),
                gender=params.get("gender", "Unknown"),
                occupation=params.get("occupation", theme),
                city=params.get("city", "Unknown"),
                country=params.get("country", "Unknown"),
                custom_values=params.get("custom_values", "Efficiency"),
                custom_life_attitude=params.get("custom_life_attitude", "Neutral"),
                life_story=params.get("life_story", "A brief life story."),
                interests_hobbies=params.get("interests_hobbies", "None"),
                attribute_count=200,
                api_name="/generate_persona"
        )

        name = params.get("name")
        if not name:
            name_match = re.search(r"I am ([^,\.]+)", result)
            name = name_match.group(1) if name_match else f"User_{uuid.uuid4().hex[:4]}"
        
        return {
            "name": name,
            "minibio": result,
            "persona": params
        }
    except Exception as e:
        add_log(f"DeepPersona generation failed: {e}")
        return None

def generate_personas_from_tiny_factory(theme, customer_profile, num_personas):
    """Compatibility wrapper; persona generation belongs to persona-runtime."""
    return persona_runtime.generate(theme, customer_profile, num_personas, scenario=theme)

def generate_personas(theme, customer_profile, num_personas):
    """Compatibility wrapper for legacy callbacks during tab migration."""
    return persona_runtime.generate(theme, customer_profile, num_personas, scenario=theme)

def generate_tasks(theme, customer_profile, url):
    client = get_blablador_client()
    if not client:
        return [f"Task {i+1} for {theme} (BLABLADOR_API_KEY not set)" for i in range(10)]

    prompt = f"""
    Generate EXACTLY 10 sequential tasks for a user to perform on the website: {url}
    The theme of the analysis is: {theme}.
    The user persona profile is: {customer_profile}.

    The tasks should cover:
    1. Communication
    2. Purchase decisions
    3. Custom Search / Information gathering
    4. Emotional connection to the persona and content/styling

    The tasks must be in sequential order and specific to the website {url}.

    CRITICAL: Skip all internal monologue or thinking process. Return ONLY a JSON object with a "tasks" key containing a list of exactly 10 strings.
    Example: {{"tasks": ["task 1", "task 2", ..., "task 10"]}}
    Do not include any other text in your response.
    """

    models_to_try = ["alias-huge", "alias-fast", "alias-large"]

    for attempt in range(5):
        try:
            print(f"Attempt {attempt+1} for task generation...")
            if attempt > 0:
                print(f"Retrying in parallel with {models_to_try}")
                # Wait 35s if it's a retry (likely Proxy Error or Rate Limit)
                time.sleep(35)
                response = call_llm_parallel(client, models_to_try, [{"role": "user", "content": prompt}], response_format={"type": "json_object"})
            else:
                response = client.chat.completions.create(
                    model="alias-huge",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"}
                )

            if response and not isinstance(response, Exception):
                content = response.choices[0].message.content
                # Robust extraction
                json_match = re.search(r"\{.*\}", content, re.DOTALL)
                if json_match:
                    try:
                        tasks_json = json.loads(json_match.group())
                        tasks = tasks_json.get("tasks", [])
                        if tasks and isinstance(tasks, list) and len(tasks) >= 5:
                            return tasks[:10]
                    except:
                        pass

                # Fallback: try to extract lines that look like tasks
                lines = [re.sub(r'^\d+[\.\)]\s*', '', l).strip() for l in content.split('\n') if l.strip()]
                tasks = [l for l in lines if len(l) > 20 and not l.startswith('{') and not l.startswith('`')]
                if len(tasks) >= 5:
                    return tasks[:10]

            print(f"Attempt {attempt+1} failed to yield valid tasks.")
        except Exception as e:
            print(f"Error in attempt {attempt+1}: {e}")

    return [f"Task {i+1} for {theme} (Manual fallback)" for i in range(10)]

def handle_generate(theme, customer_profile, num_personas, method, example_file, url):
    try:
        current_profile = customer_profile
        if method == "Example Persona" and example_file:
            # Fetch example persona info to use as profile context for task generation
            ex_personas = select_or_create_personas("", "", 1, "Example Persona", example_file)
            if ex_personas:
                current_profile = ex_personas[0].get('minibio', customer_profile)

        yield "Thinking...", None, None, None
        tasks = generate_tasks(theme, current_profile, url)
        tasks_text = "\n".join(tasks) if isinstance(tasks, list) else str(tasks)

        yield "Selecting or creating personas...", tasks_text, None, tasks
        if method == "TinyTroupe":
            personas = persona_runtime.generate(theme, customer_profile, num_personas, scenario=f"Test {url}")
        else:
            personas = select_or_create_personas(theme, customer_profile, num_personas, force_method=method, example_file=example_file)

        yield "Generation complete!", tasks_text, personas, tasks
    except Exception as e:
        yield f"Error during generation: {str(e)}", None, None, None

def check_branch_exists(repo_full_name, branch_name):
    if not gh: return False
    try:
        repo = gh.get_repo(repo_full_name)
        repo.get_branch(branch_name)
        return True
    except:
        return False

def start_and_monitor_sessions(personas, tasks, url, session_id):
    if not personas or not tasks:
        yield "Error: Personas or Tasks missing. Please generate them first.", "", "", ""
        return
    try:
        session = control_plane.create_session({"legacy_session_id": session_id})
        persona_artifacts = []
        for profile in personas:
            profile = dict(profile)
            profile.setdefault("id", f"legacy_persona_{uuid.uuid4().hex}")
            artifact = control_plane.create_artifact(
                session["session_id"], "persona.profile", profile,
                metadata={"schema_version": "1.0", "persona_id": profile["id"], "immutable_run_snapshot": True},
            )
            persona_artifacts.append(artifact["artifact_id"])
        job = control_plane.create_job({"session_id": session["session_id"], "type": "combined_test", "input_artifacts": persona_artifacts, "metadata": {"persona_artifacts": persona_artifacts, "tasks": tasks, "url": url}})
        yield f"Analysis queued: {job['job_id']}", "", session["session_id"], job["job_id"]
        job = control_plane.wait_for_job(job["job_id"])
        if job["status"] != "succeeded":
            yield f"Analysis failed: {job.get('error')}", "", session["session_id"], job["job_id"]
            return
        report = control_plane.get_artifact_content(job["output_artifacts"][0])
        yield "Analysis complete.", f"```json\n{report}\n```", session["session_id"], job["job_id"]
    except Exception as exc:
        yield f"Control-plane error: {exc}", "", "", ""

def get_reports_in_branch(repo_full_name, branch_name, filter_type=None):
    if not gh or not repo_full_name or not branch_name:
        return []
    try:
        repo = gh.get_repo(repo_full_name)
        add_log(f"Scanning branch {branch_name} for reports (filter: {filter_type})...")
        
        exclude_files = {"analysis_template.md", "readme.md", "contributing.md", "license.md"}
        
        # Method 1: Check user_experience_reports directory
        reports = []

        # Check for merged slides folder first if we are looking for slides
        if filter_type == "slides":
            try:
                repo.get_contents("user_experience_reports/slides", ref=branch_name)
                reports.append("user_experience_reports/slides")
                add_log("Detected 'user_experience_reports/slides' directory. Added as merged presentation option.")
            except:
                pass

        try:
            contents = repo.get_contents("user_experience_reports", ref=branch_name)
            for content_file in contents:
                name = content_file.name
                if name.endswith(".md"):
                    filename = name.lower()
                    if filename in exclude_files: continue
                    
                    # Optional filtering
                    if filter_type == "report" and "slide" in filename: continue
                    if filter_type == "slides" and "report" in filename: continue
                    
                    path = f"user_experience_reports/{name}"
                    reports.append(path)
        except:
            pass
            
        # Method 2: Recursive scan for ALL Markdown files
        add_log("Deep scanning repository for all Markdown files...")
        tree = repo.get_git_tree(branch_name, recursive=True).tree
        for element in tree:
            if element.type == "blob" and element.path.endswith(".md"):
                path = element.path
                filename = os.path.basename(path).lower()
                if filename in exclude_files:
                    continue
                
                # Optional filtering
                if filter_type == "report" and "slide" in filename: continue
                if filter_type == "slides" and "report" in filename: continue

                if path not in reports:
                    reports.append(path)
        
        # Filter out individual slides if they are inside a slides folder
        if filter_type == "slides":
            folders = [r for r in reports if not r.endswith(".md")]
            if folders:
                reports = [r for r in reports if not any(r.startswith(f + "/") for f in folders)]

        # Sort by relevance
        def sort_key(path):
            p_lower = path.lower()
            score = 0
            # Highest priority: specific report.md and slides.md in user_experience_reports
            if filter_type == "report" and p_lower == "user_experience_reports/report.md": score -= 1000
            if filter_type == "slides" and p_lower == "user_experience_reports/slides.md": score -= 1000
            if filter_type == "slides" and p_lower == "user_experience_reports/slides": score -= 2000
            
            # High priority: other files in user_experience_reports
            if "user_experience_reports" in p_lower: score -= 100
            
            # Medium priority: keywords in filename
            filename = os.path.basename(p_lower)
            if "report" in filename: score -= 50
            if "slide" in filename: score -= 30
            if "ux" in filename: score -= 20
            
            return (score, p_lower)

        reports.sort(key=sort_key)
        
        add_log(f"Discovered {len(reports)} entries.")
        return reports
    except Exception as e:
        add_log(f"Error fetching reports in branch {branch_name}: {e}")
        return []

def get_report_content(repo_full_name, branch_name, report_path):
    if not gh:
        return "Error: GitHub client not initialized. Check your token."
    if not repo_full_name or not branch_name or not report_path:
        return "Please select a repository, branch, and report."
    try:
        repo = gh.get_repo(repo_full_name)
        add_log(f"Fetching content from branch '{branch_name}' at path: {report_path}")
        file_content = repo.get_contents(report_path, ref=branch_name)
        return file_content.decoded_content.decode("utf-8")
    except Exception as e:
        msg = str(e)
        if "404" in msg:
            add_log(f"ERROR: File not found: {report_path} in branch {branch_name}")
            return f"Error: File '{report_path}' not found in branch '{branch_name}'. Please verify the path and branch."
        add_log(f"Error fetching {report_path}: {e}")
        return f"Error fetching report: {str(e)}"

def pull_report_from_pr(pr_url):
    if not gh:
        return "Error: GITHUB_TOKEN not set."

    try:
        # Extract repo and PR number from URL
        match = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", pr_url)
        if not match:
            return "Error: Could not parse PR URL."

        repo_full_name = match.group(1)
        pr_number = int(match.group(2))

        repo = gh.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)
        branch_name = pr.head.ref

        # Fetch the report files
        reports = get_reports_in_branch(repo_full_name, branch_name)
        if not reports:
            # Try legacy name
            try:
                file_content = repo.get_contents("user_experience_reports/report.md", ref=branch_name)
                content = file_content.decoded_content.decode("utf-8")
                processed_prs.add(pr_number)
                return content
            except:
                return "Report not found yet in this branch."
        
        # Get the first report found
        content = get_report_content(repo_full_name, branch_name, reports[0])
        processed_prs.add(pr_number)
        return content

    except Exception as e:
        print(f"Error pulling report: {e}")
        return f"Error pulling report: {str(e)}"

def render_slides(repo_full_name, branch_name, report_path):
    if not gh:
        return "Error: GitHub client not initialized. Check your token."
    if not repo_full_name or not branch_name or not report_path:
        return "Please select a repository, branch, and report."
    
    try:
        repo = gh.get_repo(repo_full_name)
        content = None
        
        # Check if the path is a directory or points to a slide folder
        is_slides_dir = report_path.endswith("/slides") or report_path.endswith("/slides/")

        if is_slides_dir or "user_experience_reports/slides" in report_path:
            slides_folder = report_path if is_slides_dir else "user_experience_reports/slides"
            try:
                folder_contents = repo.get_contents(slides_folder, ref=branch_name)
                if isinstance(folder_contents, list):
                    add_log(f"Merging multi-file slides from {slides_folder} in branch {branch_name}...")
                    slide_files = [c for c in folder_contents if c.name.endswith(".md")]
                    slide_files.sort(key=lambda x: x.name)
                    
                    merged_content = ""
                    for i, sf in enumerate(slide_files):
                        file_data = repo.get_contents(sf.path, ref=branch_name)
                        slide_text = file_data.decoded_content.decode("utf-8")
                        if i > 0:
                            merged_content += "\n\n---\n\n"
                        merged_content += slide_text
                    
                    content = merged_content
                    add_log(f"Successfully merged {len(slide_files)} slides.")
            except Exception as e:
                add_log(f"Failed to fetch slides from folder: {e}")

        if content is None:
            # Fallback to single file logic
            add_log(f"Attempting to fetch single-file slides from branch '{branch_name}' at path: {report_path}")
            try:
                file_content = repo.get_contents(report_path, ref=branch_name)
                content = file_content.decoded_content.decode("utf-8")
            except Exception as e:
                return f"Error fetching slides: {str(e)}"
            
        # Generate a unique ID for this rendering
        render_id = str(uuid.uuid4())[:8]
        work_dir = f"slides_work_{render_id}"
        os.makedirs(work_dir, exist_ok=True)
        with open(os.path.join(work_dir, "index.md"), "w") as f:
            f.write(content)
        
        # Set output directory in the SLIDES_OUTPUT_ROOT
        site_name = f"site_{render_id}"
        output_dir = os.path.join(SLIDES_OUTPUT_ROOT, site_name)
            
        subprocess.run(["mkslides", "build", work_dir, "--site-dir", output_dir])
        
        # Cleanup work dir
        shutil.rmtree(work_dir)

        if os.path.exists(os.path.join(output_dir, "index.html")):
            # Return IFrame pointing to the static route
            add_log(f"Slides rendered successfully in {site_name}")
            return f'<iframe src="/static_slides/{site_name}/index.html" width="100%" height="600px" frameborder="0"></iframe>'
        else:
            add_log(f"ERROR: mkslides finished but index.html not found.")
            return "Failed to render slides: index.html not found."
            
    except Exception as e:
        print(f"Error rendering slides: {e}")
        return f"Error rendering slides: {str(e)}"

def get_heatmaps_from_repo(repo_full_name, branch_name):
    if not gh or not repo_full_name or not branch_name:
        return []
    try:
        repo = gh.get_repo(repo_full_name)
        add_log(f"Scanning branch {branch_name} for heatmaps...")
        try:
            contents = repo.get_contents("user_experience_reports/heatmaps", ref=branch_name)
            heatmaps = []
            for c in contents:
                if c.name.endswith(".png"):
                    # Categorize by filename - Extract problem category
                    # Expected format: heatmap_problem_category_id.png
                    raw_name = c.name.replace(".png", "").replace("heatmap_", "")
                    parts = raw_name.split("_")
                    if len(parts) > 1:
                        category = parts[0].title()
                        desc = " ".join(parts[1:]).title()
                        name = f"[{category}] {desc}"
                    else:
                        name = raw_name.replace("_", " ").title()
                    
                    heatmaps.append((c.download_url, name))
            
            # Sort by name to group categories together
            heatmaps.sort(key=lambda x: x[1])
            return heatmaps
        except:
            return []
    except Exception as e:
        add_log(f"Error fetching heatmaps: {e}")
        return []

def deploy_to_hf():
    hf_token = os.environ.get("HF_TOKEN")
    hf_space_dest = os.environ.get("HF_SPACE_DEST", "harvesthealth/aux_backup")
    if not hf_token:
        return "❌ Error: HF_TOKEN environment variable not set."
    
    add_log(f"Deploying to HF Space: {hf_space_dest}...")
    try:
        # Use provided token and revision
        cmd = f"hf upload {hf_space_dest} . --repo-type=space --token {hf_token} --revision main"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            add_log("Deployment successful.")
            return "✅ Deployment successful."
        else:
            add_log(f"Deployment failed: {result.stderr}")
            return f"❌ Deployment failed: {result.stderr}"
    except Exception as e:
        add_log(f"Error during deployment: {e}")
        return f"❌ Error: {str(e)}"

def get_solutions_from_repo(repo_full_name, branch_name):
    if not gh or not repo_full_name or not branch_name:
        return []
    try:
        repo = gh.get_repo(repo_full_name)
        add_log(f"Scanning branch {branch_name} for solutions...")
        try:
            contents = repo.get_contents("user_experience_reports/solutions", ref=branch_name)
            solutions = []
            for c in contents:
                if c.name.endswith(".md"):
                    text = c.decoded_content.decode("utf-8")
                    solutions.append({"name": c.name, "content": text, "path": c.path})
            return solutions
        except:
            return []
    except Exception as e:
        add_log(f"Error fetching solutions: {e}")
        return []

def get_thought_logs_from_repo(repo_full_name, branch_name):
    if not gh or not repo_full_name or not branch_name:
        return []
    try:
        repo = gh.get_repo(repo_full_name)
        add_log(f"Scanning branch {branch_name} for thought logs...")
        try:
            contents = repo.get_contents("user_experience_reports/thought_logs", ref=branch_name)
            logs = []
            for c in contents:
                if c.name.endswith(".md"):
                    logs.append(c.path)
            return logs
        except:
            return []
    except Exception as e:
        add_log(f"Error fetching thought logs: {e}")
        return []

def generate_agents_prompt(selected_solutions_json):
    if not selected_solutions_json:
        return "No solutions selected."
    try:
        selected_solutions = json.loads(selected_solutions_json)
    except:
        return f"Error parsing solutions: {selected_solutions_json}"

    prompt = """# Coding Agent Prompt: Implement UX Solutions

You are an expert Frontend Developer. Your task is to implement the following "Liked" UX solutions into the project.

## Selected Solutions to Implement:
"""
    for sol in selected_solutions:
        prompt += f"\n### {sol['name']}\n{sol['content']}\n"
        
    prompt += """
## Instructions:
1. Review the existing UI components.
2. Replace or enhance them using the provided code snippets.
3. Ensure the implementation is responsive and adheres to the project's design system.
4. Verify accessibility and performance after implementation.
"""
    return prompt

def generate_full_ui_call(repo, branch, session_id, selected_solutions_json, url):
    if not session_id:
        return "Error: Job ID missing. Start an analysis first."
    try:
        parent = control_plane.get_job(session_id)
        job = control_plane.run_job("ui_adaptation", {"title": "UX solution prototype", "request": generate_agents_prompt(selected_solutions_json), "url": url}, session_id=parent["session_id"])
        if job["status"] != "succeeded":
            return f"❌ Prototype generation failed: {job.get('error')}"
        html = control_plane.get_artifact_content(job["output_artifacts"][0])
        return f'<iframe srcdoc="{html.replace(chr(34), "&quot;")}" width="100%" height="800" frameborder="0"></iframe>'
    except Exception as exc:
        add_log(f"Control-plane error: {exc}")
        return f"❌ Error: {exc}"

def poll_for_generated_ui(repo_full_name, branch_name, session_id):
    if not gh or not repo_full_name or not branch_name or not session_id:
        return None
    try:
        repo = gh.get_repo(repo_full_name)
        path = f"user_experience_reports/generated_ui_{session_id[:8]}.html"
        file_content = repo.get_contents(path, ref=branch_name)
        return f'<iframe src="{file_content.download_url}" width="100%" height="800px" frameborder="0"></iframe>'
    except:
        return "UI not generated yet. Please wait..."

def blablador_chat_adaptation(message="", history=[], jules_uuid=""):
    print(f"DEBUG: blablador_chat_adaptation called with message='{message}', history='{history}', jules_uuid='{jules_uuid}'")
    if not jules_uuid:
        return history + [("System", "Error: Analysis job ID missing.")], ""
    
    # This should call sendMessage to the same session_id for real-time adaptation
    # but also use alias-code for the chat experience if desired.
    # The user asked to call alias-code model on blablador endpoint.
    
    prompt = f"User request for UI adaptation: {message}\n\nPlease update the generated UI and save it."
    
    try:
        parent = control_plane.get_job(jules_uuid)
        job = control_plane.run_job("ui_adaptation", {"title": "Interactive UI adaptation", "request": prompt}, session_id=parent["session_id"])
        if job["status"] != "succeeded":
            raise RuntimeError(job.get("error"))
        agent_msg = f"Adaptation completed as job {job['job_id']}. The responsive prototype is stored as artifact {job['output_artifacts'][0]}."
        
        history.append((message, agent_msg))
        return history, ""
    except Exception as e:
        history.append((message, f"Error: {str(e)}"))
        return history, ""

def monitor_repo_for_reports():
    global all_discovered_reports
    if not gh:
        return all_discovered_reports

    add_log("Monitoring repository for new reports across branches...")
    try:
        branches = get_repo_branches(REPO_NAME)
        repo = gh.get_repo(REPO_NAME)

        new_content_found = False
        for branch_name in branches[:25]: # Check top 25 recent branches
            reports = get_reports_in_branch(REPO_NAME, branch_name, filter_type="report")
            
            for report_file in reports:
                report_key = f"{branch_name}/{report_file}"
                if report_key not in processed_prs:
                    try:
                        content = get_report_content(REPO_NAME, branch_name, report_file)
                        report_header = f"\n\n## Discovered Report: {report_file} (Branch: {branch_name})\n\n"
                        all_discovered_reports = report_header + content + "\n\n---\n\n" + all_discovered_reports
                        processed_prs.add(report_key)
                        new_content_found = True
                        add_log(f"New report found: {report_file} in {branch_name}")
                    except:
                        continue
        
        if not new_content_found:
            add_log("No new reports found in recent branches.")

        return all_discovered_reports
    except Exception as e:
        add_log(f"Error monitoring repo: {e}")
        return all_discovered_reports

# Gradio UI
with gr.Blocks(title="UX Analysis Orchestrator") as demo:
    gr.Markdown("# UX Analysis Orchestrator")

    active_session_state = gr.State("")
    active_jules_uuid_state = gr.State("")
    last_generated_tasks_state = gr.State([])
    session_id_sync_list = []
    all_solutions_state = gr.State([])
    selected_solutions_json_state = gr.State("[]")

    with gr.Tabs():
        with gr.Tab("Analysis Orchestrator"):
            gr.Markdown("### Start New Analysis Sessions")
            with gr.Row():
                with gr.Column():
                    theme_input = gr.Textbox(label="Theme", placeholder="e.g., Communication, Purchase decisions, Information gathering")
                    profile_input = gr.Textbox(label="Customer Profile Description", placeholder="Describe the target customer...")
                    num_personas_input = gr.Number(label="Number of Personas", value=1, precision=0)
                    url_input = gr.Textbox(label="Target URL", value="https://example.com")
                    persona_method = gr.Radio(["Example Persona", "TinyTroupe", "DeepPersona"], label="Persona Generation Method", value="TinyTroupe")
                    
                    with gr.Column(visible=False) as example_persona_col:
                        gr.Markdown("#### Pre-configured Personas")
                        
                        def update_persona_preview(file):
                            if not file: return ""
                            personas = select_or_create_personas("", "", 1, "Example Persona", file)
                            if personas:
                                p = personas[0]
                                name = p.get('name', 'Unknown')
                                bio = p.get('minibio', '')
                                
                                # Better summary logic
                                summary = f"### Persona: {name}\n"
                                
                                if isinstance(p.get('persona'), dict):
                                    pd = p['persona']
                                    age = pd.get('age', pd.get('persona', {}).get('age', 'N/A'))
                                    occ = pd.get('occupation', {}).get('title', pd.get('persona', {}).get('occupation', {}).get('title', 'N/A'))
                                    summary += f"**Age**: {age} | **Occupation**: {occ}\n\n"
                                
                                summary += f"**Summary**: {bio}"
                                return summary
                            return "Error loading preview."
                        
                        example_personas = get_example_personas()
                        initial_persona = example_personas[0] if example_personas else None
                        example_persona_select = gr.Dropdown(
                            label="Select Example Persona", 
                            choices=example_personas,
                            value=initial_persona
                        )
                        example_persona_preview = gr.Markdown(
                            label="Persona Preview", 
                            value=update_persona_preview(initial_persona) if initial_persona else ""
                        )
                        
                        example_persona_select.change(fn=update_persona_preview, inputs=[example_persona_select], outputs=[example_persona_preview])

                    def update_method_visibility(method):
                        return gr.update(visible=(method == "Example Persona"))
                    
                    persona_method.change(fn=update_method_visibility, inputs=[persona_method], outputs=[example_persona_col])

                    generate_btn = gr.Button("Generate Personas & Tasks")

                with gr.Column():
                    status_output = gr.Textbox(label="Status", interactive=False)
                    with gr.Row():
                        task_list_display = gr.TextArea(label="Tasks", lines=10, interactive=True, scale=4)
                        with gr.Column(min_width=40, scale=1):
                            save_tasks_btn = gr.Button("✅")
                            cancel_tasks_btn = gr.Button("❌")
                    
                    persona_display = gr.JSON(label="Personas")

                    def save_tasks(tasks_text):
                        tasks = [t.strip() for t in tasks_text.split("\n") if t.strip()]
                        return tasks, "Tasks saved."

                    def cancel_tasks(last_tasks):
                        return "\n".join(last_tasks), "Changes reverted."

                    save_tasks_btn.click(fn=save_tasks, inputs=[task_list_display], outputs=[last_generated_tasks_state, status_output])
                    cancel_tasks_btn.click(fn=cancel_tasks, inputs=[last_generated_tasks_state], outputs=[task_list_display, status_output])

            start_session_btn = gr.Button("Start Analysis Session", variant="primary")
            session_id_orch = gr.Textbox(label="Session ID (GitHub Branch Name)", interactive=True, placeholder="Enter a GitHub branch name to start analysis on...")
            session_id_sync_list.append(session_id_orch)
            report_output = gr.Markdown(label="Active Session Reports")

        with gr.Tab("Persona Studio"):
            gr.Markdown("## Persona Studio\nInspect identity, functional restrictions, behavioral characteristics, and generation provenance. Changes are explicit and persisted through the persona runtime.")
            with gr.Row():
                persona_index = gr.Dropdown(label="Persona", choices=[], interactive=True)
                refresh_personas_btn = gr.Button("Refresh generated personas")
            persona_view = gr.JSON(label="Complete synthetic-user profile")
            persona_editor = gr.Code(label="Manual JSON editor", language="json", interactive=True, lines=24)
            with gr.Accordion("Behavior characteristics (0–1)", open=True):
                behavior_sliders = {}
                for trait in ["patience", "persistence", "irritability", "angerReactivity", "angerRecovery", "impulsivity", "ambiguityTolerance", "failureTolerance", "repeatFailureTolerance", "selfEfficacy", "digitalConfidence", "helpSeeking", "exploration", "verificationTendency", "riskTolerance"]:
                    behavior_sliders[trait] = gr.Slider(0, 1, value=.5, step=.01, label=trait)
            with gr.Accordion("Functional restrictions and abilities", open=False):
                color_vision = gr.Dropdown(["typical", "protanopia", "deuteranopia", "tritanopia", "custom"], value="typical", label="Color vision")
                visual_acuity = gr.Slider(0, 1, value=1, step=.01, label="Visual acuity")
                contrast_sensitivity = gr.Slider(0, 1, value=1, step=.01, label="Contrast sensitivity")
                pointer_precision = gr.Slider(0, 1, value=.9, step=.01, label="Pointer precision")
                processing_speed = gr.Slider(0, 1, value=.8, step=.01, label="Processing speed")
                working_memory = gr.Slider(1, 12, value=5, step=1, label="Working-memory items")
                reading_speed = gr.Slider(60, 500, value=220, step=5, label="Reading speed (words/minute)")
            with gr.Row():
                apply_tweaks_btn = gr.Button("Apply tweak controls", variant="secondary")
                save_persona_btn = gr.Button("Save manual profile", variant="primary")
            persona_studio_status = gr.Markdown()

        with gr.Tab("Presentation Carousel"):
            gr.Markdown("### View Presentation Slides")
            with gr.Row(visible=False):
                sl_repo_select = gr.Dropdown(label="Repository", choices=[REPO_NAME], value=REPO_NAME, interactive=False)
                sl_branch_select = gr.Dropdown(label="Branch", choices=get_repo_branches(REPO_NAME))
            
            with gr.Row():
                session_id_carousel = gr.Textbox(label="Session ID", placeholder="Enter Session ID to pull results...")
                session_id_sync_list.append(session_id_carousel)
                sl_refresh_branches_btn = gr.Button("Pull latest results")
            
            sl_terminal_log = gr.Code(label="Connection Log", language="shell", value=f"[SYSTEM] Connected to {REPO_NAME}\n[SYSTEM] Ready to pull results.")

            with gr.Row():
                sl_status_display = gr.Markdown("Click 'Pull latest results' to discover slides.")
                sl_render_all_btn = gr.Button("Start Carousel", variant="primary")

            with gr.Row(visible=False) as carousel_controls:
                prev_deck_btn = gr.Button("< Previous Deck")
                deck_counter = gr.Markdown("Deck 0 of 0")
                next_deck_btn = gr.Button("Next Deck >")

            slideshow_display = gr.HTML(label="Slideshow")

            all_decks_state = gr.State([])
            current_deck_idx = gr.State(0)

            def sl_update_branches(repo_name, session_id=None):
                if session_id:
                    if not check_branch_exists(repo_name, session_id):
                        return gr.update(), f"[ERROR] Branch '{session_id}' not found. Please wait 30 minutes if newly created."
                
                branches = get_repo_branches(repo_name)
                latest = session_id if session_id and session_id in branches else (branches[0] if branches else "main")
                log = f"[SYSTEM] Pulled latest branches from {repo_name}\n[SYSTEM] Target branch: {latest}\n[SYSTEM] Found {len(branches)} branches."
                return gr.update(choices=branches, value=latest), log

            def sl_auto_render(repo, branch):
                reports = get_reports_in_branch(repo, branch, filter_type="slides")
                default_val = None
                # Prioritize the standard slides folder
                if "user_experience_reports/slides" in reports:
                    default_val = "user_experience_reports/slides"
                elif reports:
                    default_val = reports[0]

                html = ""
                carousel_visible = gr.update(visible=False)
                status_text = "No slide decks discovered."
                counter_text = ""
                idx = 0

                if default_val:
                    html = render_slides(repo, branch, default_val)
                    status_text = f"✅ Found and loaded slides folder: `{default_val}`"
                    if len(reports) > 1:
                        carousel_visible = gr.update(visible=True)
                        counter_text = f"Deck 1 of {len(reports)}: {default_val}"

                return status_text, reports, html, carousel_visible, idx, counter_text

            sl_repo_select.change(fn=sl_update_branches, inputs=[sl_repo_select], outputs=[sl_branch_select, sl_terminal_log])

            def start_carousel(repo, branch, decks):
                if not decks:
                    return "No slide decks found.", gr.update(visible=False), 0, "No decks."

                # Render first deck
                html = render_slides(repo, branch, decks[0])
                counter_text = f"Deck 1 of {len(decks)}: {decks[0]}"
                return html, gr.update(visible=True), 0, counter_text

            def navigate_carousel(repo, branch, decks, current_idx, direction):
                if not decks: return "", 0, "No decks."
                new_idx = (current_idx + direction) % len(decks)
                html = render_slides(repo, branch, decks[new_idx])
                counter_text = f"Deck {new_idx + 1} of {len(decks)}: {decks[new_idx]}"
                return html, new_idx, counter_text

            sl_refresh_branches_btn.click(fn=sl_update_branches, inputs=[sl_repo_select, session_id_carousel], outputs=[sl_branch_select, sl_terminal_log])

            sl_branch_select.change(
                fn=sl_auto_render,
                inputs=[sl_repo_select, sl_branch_select],
                outputs=[sl_status_display, all_decks_state, slideshow_display, carousel_controls, current_deck_idx, deck_counter]
            )

            sl_render_all_btn.click(fn=start_carousel, inputs=[sl_repo_select, sl_branch_select, all_decks_state], outputs=[slideshow_display, carousel_controls, current_deck_idx, deck_counter])

            # Use small helper components for navigation direction
            prev_val = gr.Number(-1, visible=False)
            next_val = gr.Number(1, visible=False)

            prev_deck_btn.click(fn=navigate_carousel, inputs=[sl_repo_select, sl_branch_select, all_decks_state, current_deck_idx, prev_val], outputs=[slideshow_display, current_deck_idx, deck_counter])
            next_deck_btn.click(fn=navigate_carousel, inputs=[sl_repo_select, sl_branch_select, all_decks_state, current_deck_idx, next_val], outputs=[slideshow_display, current_deck_idx, deck_counter])

        with gr.Tab("Report Viewer"):
            gr.Markdown("### View UX Reports & Solutions")
            with gr.Row(visible=False):
                rv_repo_select = gr.Dropdown(label="Repository", choices=[REPO_NAME], value=REPO_NAME, interactive=False)
                rv_branch_select = gr.Dropdown(label="Imported legacy session", choices=[])
            
            with gr.Row():
                session_id_rv = gr.Textbox(label="Session ID", placeholder="Enter Session ID to pull results...")
                session_id_sync_list.append(session_id_rv)
                rv_refresh_branches_btn = gr.Button("Pull latest results")
            
            rv_terminal_log = gr.Code(label="Connection Log", language="shell", value=f"[SYSTEM] Connected to {REPO_NAME}\n[SYSTEM] Ready to pull results.")
            
            with gr.Row():
                rv_report_select = gr.Dropdown(label="Select Report", choices=[], allow_custom_value=True)
                rv_load_report_btn = gr.Button("Load Report")
            
            rv_manual_path = gr.Textbox(label="Or enter manual path (e.g. docs/my_report.md)", placeholder="docs/my_report.md")

            with gr.Tabs():
                with gr.Tab("Report"):
                    rv_report_viewer = gr.Markdown(label="Report Content")
                with gr.Tab("Better UI Solutions"):
                    gr.Markdown("Select the solutions you want to include in the full UI generation.")
                    solutions_checkboxes = gr.CheckboxGroup(label="Identified UI Improvements", choices=[])
                    refresh_solutions_btn = gr.Button("Scan for Solutions")
                    
                    def refresh_solutions_ui(repo, branch):
                        sols = get_solutions_from_repo(repo, branch)
                        choices = [s["name"] for s in sols]
                        return gr.update(choices=choices), sols
                    
                    refresh_solutions_btn.click(fn=refresh_solutions_ui, inputs=[rv_repo_select, rv_branch_select], outputs=[solutions_checkboxes, all_solutions_state])
                    
                    def update_selected_solutions(selected_names, all_sols):
                        selected = [s for s in all_sols if s["name"] in selected_names]
                        return json.dumps(selected)
                    
                    solutions_checkboxes.change(fn=update_selected_solutions, inputs=[solutions_checkboxes, all_solutions_state], outputs=[selected_solutions_json_state])

            def rv_update_branches(repo_name, session_id=None):
                branches = control_plane.discover_legacy(repo_name)
                names = [item["name"] for item in branches]
                latest = session_id if session_id in names else (names[0] if names else None)
                return gr.update(choices=names, value=latest), f"[CONTROL PLANE] Discovered {len(names)} read-only legacy sessions. Import creates tenant-owned artifacts."

            def rv_update_reports(repo_name, branch_name):
                imported = control_plane.import_legacy(repo_name, branch_name)
                artifacts = control_plane.list_artifacts(imported["session"]["session_id"])
                choices = [(item["metadata"].get("legacy_path", item["artifact_id"]), item["artifact_id"]) for item in artifacts if item["kind"] == "legacy.report"]
                return gr.update(choices=choices, value=choices[0][1] if choices else None)

            rv_repo_select.change(fn=rv_update_branches, inputs=[rv_repo_select], outputs=[rv_branch_select, rv_terminal_log])
            def rv_load_wrapper(repo, branch, selected, manual):
                del repo, branch, manual
                return control_plane.get_artifact_content(selected) if selected else "Select an imported report."

            rv_refresh_branches_btn.click(fn=rv_update_branches, inputs=[rv_repo_select, session_id_rv], outputs=[rv_branch_select, rv_terminal_log])
            rv_branch_select.change(fn=rv_update_reports, inputs=[rv_repo_select, rv_branch_select], outputs=[rv_report_select])
            rv_load_report_btn.click(fn=rv_load_wrapper, inputs=[rv_repo_select, rv_branch_select, rv_report_select, rv_manual_path], outputs=[rv_report_viewer])

        with gr.Tab("Persona Thought Logs"):
            gr.Markdown("### Persona Internal Monologue & Analysis")
            with gr.Row(visible=False):
                tl_repo_select = gr.Dropdown(label="Repository", choices=[REPO_NAME], value=REPO_NAME, interactive=False)
                tl_branch_select = gr.Dropdown(label="Branch", choices=get_repo_branches(REPO_NAME))
            
            with gr.Row():
                session_id_tl = gr.Textbox(label="Session ID", placeholder="Enter Session ID to pull results...")
                session_id_sync_list.append(session_id_tl)
                tl_refresh_btn = gr.Button("Pull latest results")
            
            tl_terminal_log = gr.Code(label="Connection Log", language="shell", value=f"[SYSTEM] Connected to {REPO_NAME}\n[SYSTEM] Ready to pull results.")
            
            with gr.Row():
                tl_log_select = gr.Dropdown(label="Select Thought Log", choices=[])
                tl_load_btn = gr.Button("Load Log")
            
            tl_viewer = gr.Markdown(label="Thought Log Content")

            def tl_update_logs(repo, branch, session_id=None):
                if session_id:
                    if not check_branch_exists(repo, session_id):
                        return gr.update(), f"[ERROR] Branch '{session_id}' not found. Please wait 30 minutes if newly created."
                
                branches = get_repo_branches(repo)
                latest = session_id if session_id and session_id in branches else (branch if branch else (branches[0] if branches else "main"))
                log = f"[SYSTEM] Pulled latest branches from {repo}\n[SYSTEM] Target branch: {latest}"
                logs = get_thought_logs_from_repo(repo, latest)
                return gr.update(choices=logs, value=logs[0] if logs else None), log
            
            tl_refresh_btn.click(fn=tl_update_logs, inputs=[tl_repo_select, tl_branch_select, session_id_tl], outputs=[tl_log_select, tl_terminal_log])
            tl_load_btn.click(fn=get_report_content, inputs=[tl_repo_select, tl_branch_select, tl_log_select], outputs=[tl_viewer])

        with gr.Tab("Average User Journey Heatmaps"):
            gr.Markdown("### Heatmaps")
            with gr.Row():
                session_id_hm = gr.Textbox(label="Session ID", placeholder="Enter Session ID...")
                session_id_sync_list.append(session_id_hm)
            refresh_heatmaps_btn = gr.Button("Refresh Heatmaps")
            heatmap_gallery = gr.Gallery(label="User Interaction Heatmaps", columns=2)
            
            refresh_heatmaps_btn.click(fn=get_heatmaps_from_repo, inputs=[rv_repo_select, rv_branch_select], outputs=[heatmap_gallery])

        with gr.Tab("Agents.txt"):
            gr.Markdown("### Coding Agent Prompt")
            with gr.Row():
                session_id_at = gr.Textbox(label="Session ID", placeholder="Enter Session ID...")
                session_id_sync_list.append(session_id_at)
            refresh_agent_prompt_btn = gr.Button("Generate Prompt for Agent")
            agent_prompt_display = gr.Code(label="Prompt for Coding Agent", language="markdown")
            
            refresh_agent_prompt_btn.click(fn=generate_agents_prompt, inputs=[selected_solutions_json_state], outputs=[agent_prompt_display])

        with gr.Tab("Full New UI"):
            with gr.Row():
                session_id_ui = gr.Textbox(label="Session ID", placeholder="Enter Session ID (GitHub Branch Name)...")
                session_id_sync_list.append(session_id_ui)
                jules_uuid_ui = gr.Textbox(label="System UUID", placeholder="Automatically filled after analysis...")
            with gr.Row():
                with gr.Column(scale=3):
                    gr.Markdown("### Generated Landing Page")
                    generate_full_ui_btn = gr.Button("Generate Full New UI from Selected Solutions", variant="primary")
                    refresh_ui_btn = gr.Button("Refresh UI Display")
                    full_ui_iframe = gr.HTML(label="Generated UI", value="Click Generate to start.")
                
                with gr.Column(scale=1):
                    gr.Markdown("### Real-time Adaptation")
                    ui_chatbot = gr.Chatbot(label="Design Chat")
                    ui_chat_msg = gr.Textbox(label="Request Modification", placeholder="e.g. Change primary color to emerald...")
                    ui_chat_send = gr.Button("Send Request")

            generate_full_ui_btn.click(fn=generate_full_ui_call, inputs=[rv_repo_select, rv_branch_select, jules_uuid_ui, selected_solutions_json_state, url_input], outputs=[full_ui_iframe])
            refresh_ui_btn.click(fn=poll_for_generated_ui, inputs=[rv_repo_select, rv_branch_select, session_id_ui], outputs=[full_ui_iframe])
            ui_chat_send.click(fn=blablador_chat_adaptation, inputs=[ui_chat_msg, ui_chatbot, jules_uuid_ui], outputs=[ui_chatbot, ui_chat_msg])


        with gr.Tab("System"):
            gr.Markdown("### System Diagnostics & Manual Connection")
            with gr.Row():
                session_id_sys = gr.Textbox(label="Session ID", placeholder="Enter Session ID...")
                session_id_sync_list.append(session_id_sys)
            with gr.Row():
                sys_token_input = gr.Textbox(label="GitHub Token (Leave blank for default)", type="password")
                sys_repo_input = gr.Textbox(label="Repository (e.g., JsonLord/tiny_web)", value=REPO_NAME, interactive=False)
                sys_test_btn = gr.Button("Test Connection & Fetch Branches")
            
            sys_status = gr.Textbox(label="Connection Status", interactive=False)
            sys_branch_output = gr.JSON(label="Connection Log")

            def system_test(token, repo_name):
                global gh, GITHUB_TOKEN
                try:
                    if token:
                        add_log(f"Testing connection with provided token...")
                        test_gh = Github(auth=Auth.Token(token))
                    elif gh:
                        add_log(f"Testing connection with existing client...")
                        test_gh = gh
                    else:
                        add_log("ERROR: No token provided and default client is missing.")
                        return "Error: No GitHub client available. Please provide a token.", None
                    
                    user = test_gh.get_user().login
                    add_log(f"Successfully authenticated as {user}")
                    
                    # Update global client if token was provided
                    if token:
                        gh = test_gh
                        GITHUB_TOKEN = token
                        add_log("Global GitHub client updated with new token.")
                    
                    status = f"Success: Connected as {user} to {repo_name}"
                    
                    # Use existing optimized logic
                    branches = get_repo_branches(repo_name, github_client=test_gh)
                    
                    return status, {"status": "Connection established successfully", "user": user, "branches_count": len(branches)}
                except Exception as e:
                    add_log(f"System Test Error: {str(e)}")
                    return f"Error: {str(e)}", {"status": "Connection failed", "error": str(e)}

            sys_test_btn.click(fn=system_test, inputs=[sys_token_input, sys_repo_input], outputs=[sys_status, sys_branch_output])

        with gr.Tab("Live Monitoring"):
            gr.Markdown("### Live Monitoring of JsonLord/tiny_web for new UX reports")
            with gr.Row():
                session_id_live = gr.Textbox(label="Session ID", placeholder="Enter Session ID...")
                session_id_sync_list.append(session_id_live)
            live_log = gr.Textbox(label="GitHub Connection Logs", lines=5, interactive=False)
            refresh_feed_btn = gr.Button("Refresh Feed Now")
            global_feed = gr.Markdown(value="Waiting for new reports...")
            
            def monitor_and_log():
                sessions = control_plane.list_sessions()
                rows, logs, snapshots = [], [], []
                for session in sessions[:20]:
                    jobs = control_plane.list_jobs(session["session_id"])
                    rows.extend(f"- `{job['job_id']}` — **{job['status']}** ({job['type']})" for job in jobs)
                    for artifact in control_plane.list_artifacts(session["session_id"]):
                        if artifact["kind"] == "persona.profile":
                            profile = json.loads(control_plane.get_artifact_content(artifact["artifact_id"]))
                            snapshots.append(f"### {profile.get('persona', {}).get('name', profile['id'])}\n```json\n{json.dumps(profile, indent=2)}\n```")
                    logs.append(f"{session['session_id']}: {len(jobs)} persisted jobs")
                feed = "## Jobs\n" + ("\n".join(rows) or "No persisted jobs yet.")
                if snapshots: feed += "\n\n## Immutable persona snapshots\n" + "\n\n".join(snapshots)
                return feed, "\n".join(logs)

            # Use a Timer to poll every 60 seconds
            timer = gr.Timer(value=60)
            timer.tick(fn=monitor_and_log, outputs=[global_feed, live_log])
            refresh_feed_btn.click(fn=monitor_and_log, outputs=[global_feed, live_log])


        with gr.Tab("Alternative Styling"):
            gr.Markdown("### Design Automation & Iteration")
            gr.Markdown("We are working with the team behind https://github.com/onlook-dev/onlook to automate fast design iterations based on the user test reports. Stay updated on changes to the Github Page by following it.")
            
            gr.Markdown("---")
            gr.Markdown("### 🚀 Recommendations for Customer-Facing Application")
            gr.Markdown("""
            To transform this prototype into a production-ready customer application, we recommend the following enhancements:
            
            1. **Multi-Tenant Authentication**: Implement Clerk or NextAuth for secure user logins and project isolation, ensuring customers only see their own analysis branches.
            2. **Real-Time Step Visualization**: Replace the static status logs with a real-time progress bar and a "Live View" tab showing Jules' browser interactions as they happen.
            3. **Figma/Design Integration**: Develop a plugin to export the "Identified UI Improvements" directly into Figma as annotated design layers.
            4. **Guided Onboarding Flow**: Add a "Wizard" mode for first-time users to help them define their Theme and Customer Profile through guided questions.
            5. **Result Comparison (A/B Testing)**: Add a feature to view the original landing page side-by-side with the Generated UI, including a "Scorecard" of UX metrics (Accessibility, Conversion, Clarity).
            6. **Automated Deployment Previews**: Integrate with Vercel/Netlify APIs to automatically deploy the 'Full New UI' to a shareable preview URL upon generation.
            """)

            gr.Markdown("---")
            gr.Markdown("### 🛠️ Manual Deployment")
            manual_deploy_btn = gr.Button("Push App Changes to Hugging Face Space")
            deploy_status = gr.Markdown()
            manual_deploy_btn.click(fn=deploy_to_hf, outputs=[deploy_status])

    # Persona Preview Handler (moved to a safe place if not already there)
    # Actually it's inside the Tab block in previous edit.

    # Event handlers
    studio_outputs = [persona_view, persona_editor, *behavior_sliders.values(), color_vision, visual_acuity, contrast_sensitivity, pointer_precision, processing_speed, working_memory, reading_speed]

    def persona_choices(personas):
        personas = personas or []
        choices = [(item.get("persona", {}).get("name", item.get("name", item.get("id", "Persona"))), str(index)) for index, item in enumerate(personas)]
        return gr.update(choices=choices, value=choices[0][1] if choices else None)

    def load_persona(personas, index):
        profile = (personas or [])[int(index or 0)]
        behavior, abilities = profile.get("behavior", {}), profile.get("abilities", {})
        vision, motor = abilities.get("vision", {}), abilities.get("motor", {})
        cognition, reading = abilities.get("cognition", {}), abilities.get("reading", {})
        return [profile, json.dumps(profile, indent=2), *[behavior.get(trait, .5) for trait in behavior_sliders], vision.get("colorVision", "typical"), vision.get("acuity", 1), vision.get("contrastSensitivity", 1), motor.get("pointerPrecision", .9), cognition.get("processingSpeed", .8), cognition.get("workingMemoryItems", 5), reading.get("wordsPerMinute", 220)]

    def apply_persona_tweaks(profile_json, *values):
        profile = json.loads(profile_json)
        trait_values, ability_values = values[:len(behavior_sliders)], values[len(behavior_sliders):]
        profile.setdefault("behavior", {}).update(dict(zip(behavior_sliders, trait_values)))
        color, acuity, contrast, pointer, processing, memory, reading = ability_values
        abilities = profile.setdefault("abilities", {})
        abilities.setdefault("vision", {}).update(colorVision=color, acuity=acuity, contrastSensitivity=contrast)
        abilities.setdefault("motor", {})["pointerPrecision"] = pointer
        abilities.setdefault("cognition", {}).update(processingSpeed=processing, workingMemoryItems=int(memory))
        abilities.setdefault("reading", {})["wordsPerMinute"] = int(reading)
        return profile, json.dumps(profile, indent=2), "Tweaks applied locally. Save to persist them."

    def save_manual_persona(profile_json, personas, index):
        profile = json.loads(profile_json)
        saved = persona_runtime.update(profile)
        updated = list(personas or [])
        updated[int(index or 0)] = saved
        return saved, json.dumps(saved, indent=2), updated, f"Saved `{saved['id']}` as a manually edited profile."

    generate_btn.click(
        fn=handle_generate,
        inputs=[theme_input, profile_input, num_personas_input, persona_method, example_persona_select, url_input],
        outputs=[status_output, task_list_display, persona_display, last_generated_tasks_state]
    ).then(fn=persona_choices, inputs=[persona_display], outputs=[persona_index])

    refresh_personas_btn.click(fn=persona_choices, inputs=[persona_display], outputs=[persona_index])
    persona_index.change(fn=load_persona, inputs=[persona_display, persona_index], outputs=studio_outputs)
    apply_tweaks_btn.click(fn=apply_persona_tweaks, inputs=[persona_editor, *behavior_sliders.values(), color_vision, visual_acuity, contrast_sensitivity, pointer_precision, processing_speed, working_memory, reading_speed], outputs=[persona_view, persona_editor, persona_studio_status])
    save_persona_btn.click(fn=save_manual_persona, inputs=[persona_editor, persona_display, persona_index], outputs=[persona_view, persona_editor, persona_display, persona_studio_status])

    start_session_btn.click(
        fn=start_and_monitor_sessions,
        inputs=[persona_display, last_generated_tasks_state, url_input, session_id_orch],
        outputs=[status_output, report_output, active_session_state, active_jules_uuid_state]
    ).then(
        fn=lambda x: [x] * len(session_id_sync_list),
        inputs=[active_session_state],
        outputs=session_id_sync_list
    ).then(
        fn=lambda x: x,
        inputs=[active_jules_uuid_state],
        outputs=[jules_uuid_ui]
    )

    # Session ID Sync
    def sync_session_ids(val):
        return [val] * len(session_id_sync_list)
    
    for sid in session_id_sync_list:
        if sid.interactive:
            sid.change(fn=sync_session_ids, inputs=[sid], outputs=session_id_sync_list)
            sid.change(fn=lambda x: x, inputs=[sid], outputs=[active_session_state])

if __name__ == "__main__":
    # Startup connectivity check
    print("--- STARTUP GITHUB CONNECTIVITY CHECK ---")
    token_source = "None"
    if os.environ.get("GITHUB_TOKEN"):
        token_source = "GITHUB_TOKEN"
    elif os.environ.get("GITHUB_API_TOKEN"):
        token_source = "GITHUB_API_TOKEN"
    
    print(f"Token Source: {token_source}")

    if gh is None:
        print(f"ERROR: No GitHub token found in GITHUB_TOKEN or GITHUB_API_TOKEN.")
    else:
        try:
            user = gh.get_user().login
            print(f"SUCCESS: Logged in to GitHub as: {user}")
            
            # Test branch fetching for REPO_NAME
            print(f"Testing branch fetch for {REPO_NAME}...")
            test_branches = get_repo_branches(REPO_NAME)
            print(f"Test branch fetch successful. Found {len(test_branches)} branches.")
        except Exception as startup_err:
            print(f"ERROR: GitHub connectivity test failed: {startup_err}")
    print("-----------------------------------------")

    # Wrap with FastAPI for health check and API endpoints
    fastapi_app = FastAPI()

    @fastapi_app.get("/health")
    def health():
        return {"status": "ok"}

    @fastapi_app.get("/api/info")
    def info():
        return {"app": "UX Analysis Orchestrator", "version": "1.0.0"}

    @fastapi_app.get("/api-docs")
    def api_docs():
        return {
            "endpoints": [
                {
                    "path": "/health",
                    "method": "GET",
                    "purpose": "Health check"
                },
                {
                    "path": "/api/info",
                    "method": "GET",
                    "purpose": "App information"
                },
                {
                    "path": "/api-docs",
                    "method": "GET",
                    "purpose": "API documentation"
                },
                {
                    "path": "/",
                    "method": "GET",
                    "purpose": "Gradio UI"
                },
                {
                    "path": "/static_slides/{path}",
                    "method": "GET",
                    "purpose": "Static slide deck files"
                }
            ]
        }

    # Mount static files for slides
    fastapi_app.mount("/static_slides", StaticFiles(directory=SLIDES_OUTPUT_ROOT), name="static_slides")

    # Mount Gradio
    # Restrict allowed_paths for better security
    demo_app = gr.mount_gradio_app(fastapi_app, demo, path="/", allowed_paths=["/app"])

    # Run uvicorn
    uvicorn.run(demo_app, host="0.0.0.0", port=7860)
