# UX Analyst AI

<p align="center">
  <img src="https://img.shields.io/badge/AI%20Powered-Gemini%201.5-blue?style=for-the-badge&logo=google" alt="AI Powered by Gemini">
  <img src="https://img.shields.io/badge/Node.js-18+-green?style=for-the-badge&logo=node.js" alt="Node.js">
  <img src="https://img.shields.io/badge/React-18+-blue?style=for-the-badge&logo=react" alt="React">
  <img src="https://img.shields.io/badge/CLI-Ready-orange?style=for-the-badge&logo=terminal" alt="CLI Ready">
  <img src="https://img.shields.io/badge/MCP-Compatible-purple?style=for-the-badge&logo=claude" alt="MCP Compatible">
</p>

<p align="center">
  <strong>Transform your website's user experience with AI-powered analysis, actionable insights, and ready-to-implement code solutions.</strong>
</p>

<p align="center">
  🎯 <strong>Comprehensive UX Analysis</strong> •
  💻 <strong>Implementation Code Generation</strong> •
  🗣️ <strong>Natural Language Interface</strong> •
  ⚡ <strong>CI/CD Integration</strong>
</p>

---

**UX Analyst AI** is an intelligent design analysis platform that examines websites across multiple viewports, identifies UX issues, checks accessibility compliance, and generates implementation-ready code to fix problems. With support for web dashboard, command-line interface, and natural language interaction through Claude, it's the complete solution for UX optimization.

## Features

### 🎯 **Comprehensive UX Analysis**
- Multi-viewport screenshot capture (desktop, tablet, mobile)
- Visual design analysis with color, layout, and typography insights
- AI-powered UX critique with actionable recommendations
- Accessibility compliance checking
- Performance and usability scoring

### 💻 **Implementation Ready**
- Generates HTML, CSS, JavaScript code for recommended improvements
- Step-by-step implementation guides
- Copy-paste ready code snippets
- Framework-agnostic solutions

### 🤖 **AI Design Detection**
- Identifies generic, template-like appearances
- Flags excessive buzzwords and robotic copy
- Suggests authentic human elements to improve brand personality
- Helps avoid common AI design pitfalls

### 🚀 **Multiple Interfaces**
- **Web Interface**: Full-featured dashboard with real-time progress
- **Command Line Tool**: Perfect for CI/CD integration and automation
- **MCP Server**: Natural language UX analysis with Claude and other LLMs
- **Programmatic API**: Integrate into your own tools and workflows

### ⚙️ **Developer Friendly**
- Circuit breaker pattern for fault tolerance
- Browser pool management for resource efficiency
- Dependency injection architecture
- Comprehensive error handling and logging

## ⚡ Quick Demo

```bash
# Install and analyze any website in 30 seconds
git clone https://github.com/grzetich/eyeson.git
cd eyeson/ux-analyst-ai/cli && npm install && npm link
ux-analyze https://example.com --quick --code --accessibility
```

**What you get:**
- 📊 Comprehensive UX score and grading
- 📱 **Embedded screenshots** across desktop, tablet, and mobile viewports
- ♿ Accessibility compliance report with WCAG guidelines
- 🤖 AI design pattern detection and authenticity recommendations
- 💻 **Syntax-highlighted implementation code** (HTML, CSS, JavaScript)
- 📄 **Professional HTML reports** with responsive design and interactive elements

## Tech Stack

### Backend
- Node.js with Express
- Puppeteer for screenshot capture
- @axe-core/puppeteer for accessibility scanning
- Google Gemini AI for UX critique generation with vision analysis
- SQLite for data storage

### Frontend
- React with Vite
- Tailwind CSS for styling
- React Query for state management
- React Router for navigation

## Quick Start

### Prerequisites

1. **Node.js 18+** and npm
2. **Google Gemini API Key** - Get one from [Google AI Studio](https://aistudio.google.com/)

### Installation & Setup

```bash
# Clone the repository
git clone https://github.com/grzetich/eyeson.git
cd eyeson/ux-analyst-ai

# Install dependencies for all components
npm run install:all

# Set up your API key
export GEMINI_API_KEY="your-api-key-here"
# Or create a .env file in the backend directory
echo "GEMINI_API_KEY=your-api-key-here" > backend/.env
```

## Usage Options

### 1. Command Line Interface (Recommended for CI/CD)

```bash
# Install CLI globally
cd cli && npm link

# Basic analysis
ux-analyze https://example.com

# Quick analysis with code generation
ux-analyze https://example.com --quick --code --accessibility

# Interactive mode with guided prompts
ux-analyze interactive

# Custom output format and location
ux-analyze https://example.com --format html --output ./my-analysis

# CI/CD friendly JSON output
ux-analyze https://example.com --format json --quick
```

#### CLI Options
- `-o, --output <dir>` - Output directory (default: `./ux-analysis`)
- `-f, --format <format>` - Output format: `json`, `html`, `markdown` (default: `json`)
- `-v, --viewports <list>` - Comma-separated viewports (default: `desktop,tablet,mobile`)
- `--quick` - Run quick analysis (faster, less detailed)
- `--code` - Generate implementation code
- `--accessibility` - Include accessibility analysis
- `--api-key <key>` - Gemini API key (or set `GEMINI_API_KEY` env var)

### 2. Web Interface

```bash
# Start the backend server
cd backend && npm run dev

# Start the frontend (in another terminal)
cd frontend && npm run dev

# Open http://localhost:3000 in your browser
```

### 3. Programmatic Usage

```javascript
const { UXAnalyzer } = require('./cli/lib/UXAnalyzer');

const analyzer = new UXAnalyzer({
  ai: { geminiApiKey: process.env.GEMINI_API_KEY }
});

const result = await analyzer.analyze('https://example.com', {
  viewports: ['desktop', 'mobile'],
  includeCodeGeneration: true,
  includeAccessibility: true
});

console.log('UX Score:', result.report.summary.uxScore);
console.log('Implementation Code:', result.implementationCode);
```

### 4. MCP Server (Natural Language Interface)

The MCP server allows you to use natural language with Claude and other LLMs to analyze websites.

#### Setup
```bash
# Configure Claude Desktop
# Add to ~/.config/claude/claude_desktop_config.json (Linux/Mac)
# or %APPDATA%/Claude/claude_desktop_config.json (Windows)

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

#### Usage
Just ask Claude naturally:

```
"Please analyze the UX of https://example.com"

"Can you do a comprehensive UX analysis including accessibility?"

"Show me the screenshots from the mobile viewport"

"What implementation code do you recommend for the UX issues?"
```

#### Benefits
- **Natural conversation**: No command syntax to remember
- **Progressive updates**: Claude monitors progress and explains what's happening
- **Visual analysis**: Claude can see and discuss the actual screenshots
- **Intelligent presentation**: Results formatted based on your specific questions
- **Code explanations**: Claude explains generated code and why it works

## Integration Examples

### NPM Scripts

Add to your `package.json`:

```json
{
  "scripts": {
    "ux:check": "ux-analyze http://localhost:3000 --quick",
    "ux:full": "ux-analyze http://localhost:3000 --code --accessibility --format html",
    "ux:mobile": "ux-analyze http://localhost:3000 --viewports mobile --quick",
    "ux:ci": "ux-analyze $UX_TARGET_URL --format json --quick --output ./ux-reports"
  }
}
```

### GitHub Actions CI/CD

```yaml
name: UX Analysis

on:
  pull_request:
    branches: [ main ]
  push:
    branches: [ main ]

jobs:
  ux-analysis:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3

    - name: Setup Node.js
      uses: actions/setup-node@v3
      with:
        node-version: '18'

    - name: Install UX Analyzer
      run: |
        cd ux-analyst-ai/cli
        npm install
        npm link

    - name: Run UX Analysis
      env:
        GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      run: |
        ux-analyze https://your-staging-site.com \
          --format json \
          --output ./ux-reports \
          --quick \
          --accessibility

    - name: Upload UX Reports
      uses: actions/upload-artifact@v3
      with:
        name: ux-analysis-reports
        path: ./ux-reports/
```

### Pre-commit Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit

echo "Running UX analysis..."
npm run ux:check

if [ $? -ne 0 ]; then
  echo "❌ UX analysis failed. Please review and fix issues before committing."
  exit 1
fi

echo "✅ UX analysis passed!"
```

## Architecture

### Backend Services
- **AnalysisService**: Core analysis orchestration
- **ScreenshotService**: Multi-viewport screenshot capture with browser pooling
- **AICritiqueService**: AI-powered UX evaluation using Google Gemini
- **VisualDesignAnalyzer**: Color, layout, and typography analysis
- **CodeGenerationService**: AI-powered implementation code generation

### Frontend Components
- **React Dashboard**: Real-time analysis progress and results
- **AnalysisForm**: URL input and configuration
- **ProgressTracker**: Live analysis status updates
- **ResultsViewer**: Interactive report display
- **CodeImplementationSection**: Generated code display with copy/download

### CLI Tool
- **Commander.js**: Robust CLI argument parsing
- **Interactive Mode**: Guided prompts with inquirer
- **Progress Tracking**: Real-time spinners and status updates
- **Multiple Output Formats**: JSON, HTML, Markdown support

### MCP Server
- **Model Context Protocol**: Standard interface for LLM tool integration
- **Natural Language Interface**: Conversational UX analysis with Claude
- **Progressive Updates**: Real-time progress monitoring and explanations
- **Visual Content Support**: Screenshots and images for LLM analysis

## Configuration

### Environment Variables

```bash
# Required
GEMINI_API_KEY="your-gemini-api-key"

# Optional
PORT=3000
NODE_ENV=development
```

### Configuration File

Create `ux-config.json`:

```json
{
  "ai": {
    "geminiApiKey": "your-api-key"
  },
  "defaults": {
    "viewports": ["desktop", "tablet", "mobile"],
    "outputFormat": "html",
    "includeCode": true,
    "includeAccessibility": true
  },
  "analysis": {
    "timeoutMs": 300000,
    "maxConcurrentAnalyses": 3
  }
}
```

Use with: `ux-analyze https://example.com --config ux-config.json`

## Output Formats

### JSON (Machine-readable)
- Raw analysis data perfect for CI/CD integration
- Parseable by other tools and scripts
- Contains all metrics, scores, and recommendations

### HTML (Human-readable)
- **Professional visual reports** with embedded base64 screenshots (all viewports)
- **Syntax-highlighted implementation code** with HTML/CSS/JavaScript tabs
- **Responsive design** with gradient headers, cards, and color-coded severity
- **Interactive elements** including collapsible sections and code tabs
- **Self-contained files** - no external dependencies, easy sharing

### Markdown (Documentation-friendly)
- README-compatible format for documentation
- Version control friendly
- Great for team collaboration

## API Documentation

### Start Analysis
```http
POST /api/analyze
Content-Type: application/json

{
  "url": "https://example.com",
  "options": {
    "viewports": ["desktop", "tablet", "mobile"],
    "includeAccessibility": true,
    "analysisType": "comprehensive"
  }
}
```

### Get Analysis Result
```http
GET /api/analyze/{analysisId}
```

### Get HTML Report
```http
GET /api/analyze/{analysisId}/report
```

### Health Check
```http
GET /api/health
```

## Development

### Project Structure
```
ux-analyst-ai/
├── backend/                 # Express API server
│   ├── services/           # Core business logic
│   ├── routes/             # API routes
│   ├── database/           # Database setup
│   └── server.js           # Entry point
├── frontend/               # React application
│   ├── src/
│   │   ├── components/     # React components
│   │   ├── pages/          # Page components
│   │   └── api/            # API client
│   └── dist/               # Built assets
├── data/                   # Runtime data (screenshots, DB)
└── docker-compose.yml      # Production deployment
```

### Available Scripts

```bash
# Development
npm run dev                 # Start both backend and frontend
npm run dev:backend         # Start only backend
npm run dev:frontend        # Start only frontend

# Building
npm run build              # Build frontend
npm run install:all        # Install all dependencies

# Testing
npm test                   # Run backend tests
```

### Adding New Features

1. **Backend Services**: Add to `backend/services/`
2. **API Routes**: Add to `backend/routes/`
3. **Frontend Components**: Add to `frontend/src/components/`
4. **Database Changes**: Modify `backend/database/init.js`

## Troubleshooting

### Common Issues

1. **Puppeteer Chrome Issues**
   ```bash
   # Linux: Install dependencies
   sudo apt-get install -y gconf-service libasound2 libatk1.0-0 libc6 libcairo2

   # Docker: Already included in Dockerfile
   ```

2. **Gemini API Errors**
   - Verify API key is set correctly
   - Check API usage limits and quotas
   - Ensure Gemini API access is enabled

3. **Out of Memory**
   ```bash
   # Increase Node.js memory limit
   export NODE_OPTIONS="--max-old-space-size=4096"
   ```

4. **Screenshots Not Loading**
   - Check file permissions in `data/screenshots/`
   - Verify `SCREENSHOT_STORAGE_PATH` is correct
   - Ensure sufficient disk space
   - For HTML reports: Screenshots are embedded as base64, check file sizes

5. **Implementation Code Not Generated**
   - Ensure `--code` flag is used for CLI analysis
   - Verify Gemini API key has sufficient quota
   - Check debug output for code generation service errors

### Performance Optimization

- **Reduce Concurrent Analyses**: Lower `MAX_CONCURRENT_ANALYSES`
- **Optimize Screenshots**: Reduce viewport sizes or skip viewports
- **Database**: Consider PostgreSQL for production
- **Caching**: Add Redis for session caching

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Support

For issues and questions:
1. Check this README and troubleshooting section
2. Review the [docs](../docs/) for architecture details
3. Open an issue with reproduction steps

---

**Note**: This is an MVP implementation. See the roadmap in the docs for planned enhancements including Figma integration, team collaboration, and enterprise features.