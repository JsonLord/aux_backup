Working behaviour and prompt context for Jules. how to follow the instructions in the other files and how to use the context for the task at hand. 
Add: to never delete a hf_upload.py file once created. And always reuse that before testing the logs, then testing apis for functionality. Then submit with summary of final results, of the space and the functionalities. 

Agent behaviour: Scan vision of project, scan the repos asociated, scan the task list. Build component by component. Test components. Identify where components interact. Test the internal interaction. Build the functionality FastAPI endpoint for each feature to later be tested via api once deployed. Then test the overall app from start to finish. Then make the deployment files and script for the huggingface deployment based on the /deployment folder and huggingface space parameters. Then expose the FASTAPis in the way it is recommended. Gradio=gradio endpoints. Docker= space url endpoints /health etc. Then deploy. Then check the build logs, then the run logs. Fix failures until successfully running. Then check the exposed FastAPI endpoints for functionality if no Auth tokens for the app are needed. If they are needed. Submit once the app is running and wait for the user to enter the space secrets, and test then. 


## Project Specific Instructions
Here’s a structured `AGENTS.md` file with specific instructions for your project, formatted in Markdown:

```markdown
# AGENTS.md

## Working Behavior for This Project

### Core Functionality
1. **Deployment**:
   - The eyeson application must be deployed to Hugging Face Spaces (`harvesthealth/tinytroupe-alpha`) using Gradio.
   - Ensure the Gradio interface is responsive and user-friendly, with clear task input fields and model selection (alias-large, alias-fast, alias-code).

2. **LLM Integration**:
   - Connect to the Helmholtz Blablador API (`https://api.helmholtz-blablador.fz-juelich.de/v1`) using the `BLABLADOR_API_KEY` stored in Hugging Face Space Secrets.
   - Implement intelligent task routing:
     - **alias-large**: For complex tasks (e.g., planning, multi-step reasoning).
     - **alias-fast**: For quick queries (e.g., simple Q&A, utility operations).
     - **alias-code**: For code-related tasks (e.g., debugging, generation).

3. **Security**:
   - Never expose the `BLABLADOR_API_KEY` in logs or frontend code. Use Hugging Face’s Secrets management.

4. **Extensibility**:
   - Design the LLM client modularly to support future model aliases or APIs (e.g., multi-modal models).

---

## Key Project-Specific Context

### Technical Stack
- **Frontend**: Gradio (default for HF Spaces).
- **Backend**: Python (Flask/FastAPI if needed for custom routing).
- **LLM API**: OpenAI-compatible format (Blablador API).
- **Authentication**: Hugging Face Secrets (`BLABLADOR_API_KEY`).

### Deployment Notes
- The space is publicly accessible but restrict API key exposure.
- Monitor HF Spaces logs for errors (e.g., API rate limits, key invalidation).

### Task Routing Logic
- Use a mapping (e.g., `task_type: model_alias`) to route inputs dynamically.
- Fallback to `alias-fast` for unclassified tasks.

---

## Tips for Best Results

### 1. Testing
- **Local Testing**: Use `gradio app.py` to test locally before deploying to HF Spaces.
- **API Key Validation**: Test the Blablador API with a minimal script:
  ```python
  import requests
  headers = {"Authorization": f"Bearer {os.getenv('BLABLADOR_API_KEY')}"}
  response = requests.post("https://api.helmholtz-blablador.fz-juelich.de/v1/chat/completions", headers=headers, json={"model": "alias-fast", "messages": [{"role": "user", "content": "test"}]})
  print(response.json())
  ```

### 2. Performance
- Cache frequent queries (e.g., simple utility tasks) to reduce API calls.
- Optimize Gradio UI for mobile devices if needed.

### 3. Debugging
- Check HF Spaces logs for:
  - `401 Unauthorized`: Invalid API key.
  - `429 Too Many Requests`: Rate limit issues.
  - `500 Internal Error`: Backend routing failures.

### 4. Future-Proofing
- Add logging for model usage (e.g., task type, latency, tokens).
- Document new model aliases in a `MODELS.md` file.

---

### Example Workflow
1. User submits a task via Gradio.
2. The app routes to `alias-large` if the task contains keywords like "plan" or "analyze."
3. The request is sent to Blablador with the correct alias and API key.
4. The response is displayed in Gradio with metadata (e.g., model used).

For questions, refer to:
- [Hugging Face Spaces Docs](https://huggingface.co/docs/hub/spaces)
- [Blablador API Docs](https://api.helmholtz-blablador.fz-juelich.de/docs)
```

This file provides clear guidance for developers/maintainers while addressing security, scalability, and debugging.