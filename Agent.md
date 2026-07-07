# Agent.md - Deployment Manager Notes

This file informs future agents about ongoing deployment best practices and tricks for the UX Analysis Orchestrator.

## 1. Deployment Configuration

### Target Space
- **Profile:** `Leon4gr45`  
- **Space:** `aux_backup`  
- **Full Identifier:** `Leon4gr45/aux_backup`  
- **Frontend Port:** `7860`

### Deployment Method
- **Docker SDK** is used for maximum flexibility and to handle complex dependencies like TinyTroupe and mkslides.

### HF Token
- The environment variable **`HF_TOKEN_INTERNAL`** will always be provided at execution time.
- Never hardcode the token.

### Required Files
- `Dockerfile`
- `README.md` (with HF YAML frontmatter)
- `.hfignore`
- `Agent.md` (this file)

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

### Precondition
Use the Hugging Face Hub CLI `hf` to check that the space is empty of files and delete any which are still in there and not belonging to the project.

### Standard Deployment Command
```bash
hf upload Leon4gr45/aux_backup . --repo-type=space --token \$HF_TOKEN_INTERNAL
```

### Log Monitoring
Stream logs using the following commands:

- **Build Logs (SSE):**
  ```bash
  curl -N -H "Authorization: Bearer \$HF_TOKEN_INTERNAL" "https://huggingface.co/api/spaces/Leon4gr45/aux_backup/logs/build"
  ```
- **Run Logs (SSE):**
  ```bash
  curl -N -H "Authorization: Bearer \$HF_TOKEN_INTERNAL" "https://huggingface.co/api/spaces/Leon4gr45/aux_backup/logs/run"
  ```

Check after 300 seconds to see if the deployment has been successful. If not, fix the errors and redeploy.

### Troubleshooting
- **AttributeError: __provides__**: Usually indicates a conflict between `gradio`, `pydantic`, and `zope-interface`. Ensure `pydantic < 2.10` and `gradio >= 5.0` are used.
- **502 Errors**: The app has built-in 35s retry logic for Helmholtz Blablador API 502 errors.
- **Dependencies**: TinyTroupe and mkslides are cloned and installed during the Docker build process.
