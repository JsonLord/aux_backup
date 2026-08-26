# UX Analyst AI - MCP Server

This is a Model Context Protocol (MCP) server that provides UX analysis capabilities to Large Language Models. It allows LLMs to analyze websites, monitor progress, and present results in a natural conversational interface.

## What is MCP?

The Model Context Protocol (MCP) enables LLMs to securely access external data and tools. This MCP server exposes UX analysis capabilities as tools that Claude and other LLMs can use.

## How It Works

1. **LLM Request**: User asks LLM to analyze a website
2. **Tool Invocation**: LLM calls MCP tools to start analysis
3. **Progress Monitoring**: LLM polls for progress and updates user
4. **Results Presentation**: LLM formats and explains the results naturally
5. **Visual Analysis**: LLM can view and discuss screenshots
6. **Code Generation**: LLM explains generated implementation code

## Available Tools

### `ux_analyze_start`
Start a comprehensive UX analysis of a website.

**Parameters:**
- `url` (required): Website URL to analyze
- `options` (optional): Analysis configuration
  - `viewports`: Array of viewports (desktop, tablet, mobile)
  - `analysisType`: "quick" or "comprehensive"
  - `includeAccessibility`: Boolean for accessibility analysis
  - `includeCodeGeneration`: Boolean for code generation

**Returns:** Analysis ID and status

### `ux_analyze_status`
Check the progress of a running analysis.

**Parameters:**
- `analysisId` (required): The analysis ID from start command

**Returns:** Current status, progress percentage, and stage

### `ux_analyze_results`
Get the complete results of a finished analysis.

**Parameters:**
- `analysisId` (required): The analysis ID

**Returns:** Formatted analysis results with scores, recommendations, and findings

### `ux_analyze_screenshots`
Get screenshot images from the analysis.

**Parameters:**
- `analysisId` (required): The analysis ID

**Returns:** Array of screenshot images for each viewport

### `ux_analyze_code`
Get generated implementation code for improvements.

**Parameters:**
- `analysisId` (required): The analysis ID

**Returns:** HTML, CSS, and JavaScript code with implementation instructions

### `ux_health_check`
Check if the UX analysis backend is running.

**Returns:** Health status and backend information

## Setup

### Prerequisites

1. **UX Analyst Backend**: The main backend server must be running
2. **Environment Variables**:
   - `UX_BACKEND_URL` (default: http://localhost:3005)
   - `GEMINI_API_KEY` (required for backend)

### Installation

```bash
cd mcp-server
npm install
```

### Configuration

#### For Claude Desktop

Add to your Claude Desktop config file:

**Windows:** `%APPDATA%/Claude/claude_desktop_config.json`
**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ux-analyst": {
      "command": "node",
      "args": ["/path/to/ux-analyst-ai/mcp-server/index.js"],
      "env": {
        "UX_BACKEND_URL": "http://localhost:3005"
      }
    }
  }
}
```

#### For Other LLM Clients

The server follows the standard MCP stdio protocol. Refer to your LLM client's documentation for MCP server configuration.

### Starting the Server

#### Development Mode
```bash
npm run dev
```

#### Production Mode
```bash
npm start
```

## Usage Examples

Once configured, you can ask Claude:

### Basic Analysis
```
"Please analyze the UX of https://example.com"
```

### Detailed Analysis
```
"Can you do a comprehensive UX analysis of https://mysite.com including accessibility and code generation?"
```

### Mobile-Specific Analysis
```
"Analyze https://example.com but focus only on mobile viewport"
```

### Progress Monitoring
```
"Check the status of my UX analysis"
```

### Code Implementation
```
"Show me the implementation code for the UX improvements you found"
```

## Workflow

Here's what happens when you ask Claude to analyze a website:

1. **User**: "Analyze the UX of https://example.com"

2. **Claude**: Calls `ux_analyze_start` and responds:
   > "I'm starting a UX analysis of https://example.com. This will include screenshots across desktop, tablet, and mobile viewports, plus accessibility checking and code generation. Let me monitor the progress..."

3. **Claude**: Periodically calls `ux_analyze_status` and updates:
   > "📸 Currently capturing screenshots (40% complete)..."
   > "🤖 Running AI analysis on visual design (70% complete)..."

4. **Claude**: When complete, calls `ux_analyze_results` and presents:
   > "✅ Analysis complete! Here are the key findings:
   >
   > **Overall Grade:** Good (78/100)
   > **Key Issues:**
   > 1. Low contrast ratio on call-to-action buttons
   > 2. Text too small on mobile viewport
   > 3. Missing alt text on hero images
   >
   > Would you like to see the screenshots or the implementation code to fix these issues?"

5. **User**: "Show me the screenshots"

6. **Claude**: Calls `ux_analyze_screenshots` and displays the images with commentary.

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Claude LLM    │◄──►│   MCP Server    │◄──►│  UX Backend     │
│                 │    │   (This)        │    │  (Express API)  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

- **Claude LLM**: Converses with user and calls MCP tools
- **MCP Server**: Translates between LLM and UX backend
- **UX Backend**: Performs actual analysis, screenshots, AI critique

## Benefits Over CLI/Web Interface

### Natural Conversation
- **CLI**: `ux-analyze https://example.com --format html --output ./results`
- **MCP**: "Can you analyze example.com and explain the main UX issues?"

### Intelligent Presentation
- **Web UI**: Fixed dashboard layout with raw data
- **MCP**: Claude adapts presentation to user's specific questions

### Progressive Updates
- **CLI**: Shows spinner until complete
- **MCP**: "I'm currently analyzing the color palette and found some contrast issues..."

### Visual Understanding
- **CLI/Web**: Shows screenshot files
- **MCP**: Claude can see and discuss the actual visual content

### Contextual Code Explanation
- **CLI/Web**: Raw code snippets
- **MCP**: "Here's the CSS to fix the contrast issue I mentioned, and why it works..."

## Troubleshooting

### "Backend not available"
- Ensure UX backend is running on the configured port
- Check `UX_BACKEND_URL` environment variable
- Verify backend health with: `curl http://localhost:3005/api/health`

### "Analysis failed"
- Check backend logs for errors
- Ensure `GEMINI_API_KEY` is set in backend environment
- Verify the target URL is accessible

### "No screenshots available"
- Screenshots may not have been captured if analysis failed
- Check backend screenshot storage permissions
- Verify Puppeteer can access the target URL

## Development

### Adding New Tools

1. Add tool definition to `ListToolsRequestSchema` handler
2. Add tool handler to `CallToolRequestSchema` switch statement
3. Implement the tool method
4. Update this README

### Testing

Test individual tools:

```bash
# Start backend
cd ../backend && npm run dev

# In another terminal, start MCP server
cd mcp-server && npm run dev
```

Then configure and test with Claude Desktop or another MCP client.

## License

MIT License - see LICENSE file for details.