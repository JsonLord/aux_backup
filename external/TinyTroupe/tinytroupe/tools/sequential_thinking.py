import requests
import json
from tinytroupe.agent.mental_faculty import TinyToolUse
from tinytroupe.utils.logger import get_logger

class SequentialThinkingTool(TinyToolUse):
    def __init__(self):
        super().__init__(tools=[self])
        self.url = "https://harvesthealth-sequential-thinking-mcp.hf.space/run"

    def process_action(self, agent, action: dict) -> bool:
        if action['type'] == 'SEQUENTIAL_THINKING':
            logger = get_logger(agent.name)

            try:
                arguments = json.loads(action['content'])
            except json.JSONDecodeError as e:
                logger.error(f"MCP Interaction - Invalid JSON in action content: {action['content']}. Error: {e}")
                return False

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "sequentialthinking",
                    "arguments": arguments
                }
            }

            logger.info(f"MCP Interaction - Request: {json.dumps(payload, indent=2)}")
            response_json = self.send_thought(payload)
            logger.info(f"MCP Interaction - Response: {json.dumps(response_json, indent=2)}")

            if response_json and 'result' in response_json and 'content' in response_json['result']:
                content_text = response_json['result']['content'][0]['text']
                try:
                    response_data = json.loads(content_text)
                    agent.think(f"Thought processed. History length: {response_data.get('thoughtHistoryLength')}")
                except json.JSONDecodeError:
                    logger.error(f"MCP Interaction - Could not decode response content: {content_text}")
                    agent.think("Received a response from the sequential thinking server, but it was not in the expected format.")

            return True
        return False

    def send_thought(self, thought_data: dict):
        headers = {'Content-Type': 'application/json'}
        try:
            response = requests.post(self.url, headers=headers, json=thought_data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            # Get the logger for the agent that is making the call
            # This is a bit of a hack, as we don't have the agent object here.
            # We will rely on the caller to log the error.
            return {"error": str(e)}

    def actions_definitions_prompt(self) -> str:
        return ""

    def actions_constraints_prompt(self) -> str:
        return ""
