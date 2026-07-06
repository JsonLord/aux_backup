# Agent.md - Deployment Manager Notes

This file informs future agents about ongoing deployment best practices and tricks for the UX Analysis Orchestrator.

## 1. Deployment Configuration

### Target Space
- **Profile:** `Leon4gr45`  
- **Space:** `aux_backup`  
- **Full Identifier:** `Leon4gr45/aux_backup`  
- **Frontend Port:** `7860`

### Deployment Method
- **Docker SDK** is used for maximum flexibility and to handle the complex dependencies (TinyTroupe, mkslides).

### HF Token
- The environment variable **`HF_TOKEN_INTERNAL`** (placeholder name for the provided secret) is used for deployment and log monitoring.
- Never hardcode the token.

### Required Files
- `Dockerfile`
- `README.md` (with HF YAML frontmatter)
- `.hfignore`
- `Agent.md`

---

## 2. API Exposure and Documentation

### Mandatory Endpoints

- **`/health`**  
  - Method: GET
  - Purpose: Returns HTTP 200 when the app is ready.
  - Required for Hugging Face.

- **`/api-docs`**  
  - Method: GET
  - Purpose: Documents all available API endpoints.
  - Reachable at: `https://Leon4gr45-aux_backup.hf.space/api-docs`

### Functional Endpoints

- **`/api/info`**
  - Method: GET
  - Purpose: Returns application information and version.
  - Response: `{"app": "UX Analysis Orchestrator", "version": "1.0.0"}`

- **`/static_slides/{path}`**
  - Method: GET
  - Purpose: Serves rendered slide decks.

---

## 3. Deployment Workflow

### Standard Deployment Command
```bash
# Use the provided token variable
hf upload Leon4gr45/aux_backup --repo-type=space --token $HF_TOKEN_INTERNAL
```

### Log Monitoring
- **Build Logs:**
  ```bash
  curl -N -H "Authorization: Bearer $HF_TOKEN_INTERNAL" "https://huggingface.co/api/spaces/Leon4gr45/aux_backup/logs/build"
  ```
- **Run Logs:**
  ```bash
  curl -N -H "Authorization: Bearer $HF_TOKEN_INTERNAL" "https://huggingface.co/api/spaces/Leon4gr45/aux_backup/logs/run"
  ```

### Deployment Best Practices
- Ensure `Dockerfile` correctly installs all dependencies (e.g., `uv`, `mkslides`, `TinyTroupe`).
- Always verify `/health` after deployment.
- Check build logs if deployment stays in "Building" for more than 5 minutes.
- If 502 errors occur during LLM calls, the application has built-in retry logic with a 35s wait.
