from gradio_client import Client
import logging

logger = logging.getLogger("tools-api")

def search_web_tool(query: str, limit: int = 4):
    """Search the web for information using victor/websearch space."""
    logger.info(f"Searching web for: {query}")
    try:
        client = Client("https://victor-websearch.hf.space/")
        result = client.predict(query, "search", limit, api_name="/search_web")
        return result
    except Exception as e:
        logger.error(f"Error searching web: {e}")
        return f"Error searching web: {str(e)}"

def search_hf_spaces_tool(query: str, limit: int = 3):
    """Search Hugging Face Spaces using john6666/testwarm space."""
    logger.info(f"Searching HF Spaces for: {query}")
    try:
        client = Client("https://john6666-testwarm.hf.space/")
        # data format for /search endpoint
        result = client.predict(
            ["model"], # Repo type
            "last_modified", # Sort
            "ascending order", # Sort method
            query, # Filter
            query, # Search
            "", # Author
            "", # Tags
            "warm", # Inference status
            "gated", # Gated status
            ["auto"], # Approval method
            ["n<1K"], # Size categories
            limit, # Limit
            ["cpu-basic"], # Specify hardware
            ["RUNNING"], # Specify stage
            ["Space Runtime"], # Fetch detail
            ["Type"], # Show items
            api_name="/search"
        )
        return result
    except Exception as e:
        logger.error(f"Error searching HF Spaces: {e}")
        return f"Error searching HF Spaces: {str(e)}"
