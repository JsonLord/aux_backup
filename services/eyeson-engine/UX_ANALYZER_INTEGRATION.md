# UX Analyzer - Integration Guide

Complete guide to integrate UX Analyst AI as an MCP server and Claude Code skill for AI tools.

## Overview

**UX Analyst AI** can be used in three ways:

1. **CLI Tool** - Command line interface for quick analysis
2. **MCP Server** - Natural language interface through Claude Desktop
3. **Claude Code Skill** - Programmatic integration into workflows

This guide covers **#2 (MCP Server)** and **#3 (Claude Code Skill)** for AI tool integration.

---

## Part 1: MCP Server Setup (for Claude Desktop & LLMs)

The MCP server allows Claude and other LLMs to analyze websites through natural conversation.

### Prerequisites

- Node.js 18+
- Google Gemini API Key ([Get one](https://aistudio.google.com/))
- UX Analyst AI backend running (or Docker)

### Step 1: Start the Backend

```bash
cd ux-analyst-ai/backend
npm install
npm start
```

Backend runs on `http://localhost:3005` by default.

Verify health:
```bash
curl http://localhost:3005/api/health
```

### Step 2: Install MCP Server Dependencies

```bash
cd ux-analyst-ai/mcp-server
npm install
```

### Step 3: Configure for Claude Desktop

**Windows:** Edit `%APPDATA%/Claude/claude_desktop_config.json`
**macOS:** Edit `~/Library/Application Support/Claude/claude_desktop_config.json`
**Linux:** Edit `~/.config/Claude/claude_desktop_config.json`

Add this server configuration:

```json
{
  "mcpServers": {
    "ux-analyst": {
      "command": "node",
      "args": ["/absolute/path/to/eyeson/ux-analyst-ai/mcp-server/index.js"],
      "env": {
        "UX_BACKEND_URL": "http://localhost:3005",
        "GEMINI_API_KEY": "your-gemini-key-here"
      }
    }
  }
}
```

**Important:** Use absolute paths, not relative paths.

### Step 4: Restart Claude Desktop

Close and reopen Claude Desktop. You should see "UX Analyst" in the tools list.

### Step 5: Test in Claude

Ask Claude:
```
Can you analyze the UX of https://example.com?
```

Claude will:
1. Call `ux_analyze_start` with the URL
2. Monitor progress with `ux_analyze_status`
3. Retrieve results with `ux_analyze_results`
4. Show screenshots with `ux_analyze_screenshots`
5. Explain implementation code with `ux_analyze_code`

### Conversation Example

**You:** "Analyze the UX of https://airbnb.com focusing on the booking flow"

**Claude:** "I'll analyze Airbnb's UX for you. Let me start a comprehensive analysis..."

*Claude calls: `ux_analyze_start` with url="https://airbnb.com"*

"Starting analysis (ID: abc123). Capturing screenshots across desktop, tablet, and mobile viewports..."

*Claude calls: `ux_analyze_status` repeatedly until complete*

"✅ Analysis complete! Here are the key findings:

**Overall Grade:** Excellent (92/100)

**Strengths:**
- Clear visual hierarchy in booking flow
- Excellent mobile responsiveness
- Accessible form controls

**Issues to Address:**
- Date picker lacks keyboard navigation
- Map doesn't have proper aria-labels
- Search box could use autocomplete suggestions

Would you like to see the screenshots or the code to implement these improvements?"

**You:** "Show me the code"

*Claude calls: `ux_analyze_code`*

**Claude:** Shows HTML, CSS, and JavaScript improvements with explanations.

---

## Part 2: Claude Code Skill Setup

The Claude Code skill allows integration into automated workflows and CI/CD pipelines.

### Installation

```bash
cd eyeson
npm install --save-dev ux-analyzer-skill
```

### Using in Claude Code

Create a script `analyze-ux.js`:

```javascript
const { UXAnalyzer } = require('ux-analyzer-skill');

async function auditWebsite() {
  const analyzer = new UXAnalyzer({
    backendUrl: process.env.UX_BACKEND_URL || 'http://localhost:3005',
    timeout: 300000 // 5 minutes
  });

  try {
    console.log('🚀 Starting UX audit of example.com...\n');

    // Start analysis
    const analysisId = await analyzer.startAnalysis('https://example.com', {
      comprehensive: true,
      includeAccessibility: true,
      includeCodeGeneration: true
    });

    console.log(`📊 Analysis ID: ${analysisId}`);
    console.log('⏳ Monitoring progress...\n');

    // Monitor progress
    const result = await analyzer.waitForCompletion(analysisId, (progress) => {
      console.log(`  ${progress.stage}: ${progress.percent}%`);
    });

    // Display results
    console.log('\n✅ Analysis Complete!\n');
    console.log(`📈 UX Score: ${result.score}/100`);
    console.log(`⭐ Grade: ${result.grade}`);
    console.log(`🚨 Issues: ${result.issues.length}`);
    console.log(`♿ A11y Violations: ${result.accessibility.violations.length}\n`);

    // Save report
    await analyzer.saveReport(analysisId, './ux-report.html');
    console.log('📄 Report saved to ux-report.html');

    // Generate code recommendations
    const code = await analyzer.getCode(analysisId);
    console.log(`\n💻 Generated ${code.improvements.length} code improvements`);

    return result;
  } catch (error) {
    console.error('❌ Analysis failed:', error.message);
    process.exit(1);
  }
}

auditWebsite();
```

Run with:
```bash
node analyze-ux.js
```

---

## Part 3: CI/CD Integration

### GitHub Actions Example

```yaml
name: UX Regression Testing

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  ux-audit:
    runs-on: ubuntu-latest

    services:
      ux-backend:
        image: ux-analyst:latest
        ports:
          - 3005:3005
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}

    steps:
      - uses: actions/checkout@v2

      - name: Setup Node.js
        uses: actions/setup-node@v2
        with:
          node-version: '18'

      - name: Install dependencies
        run: npm install ux-analyzer-skill

      - name: Run UX analysis
        env:
          UX_BACKEND_URL: http://localhost:3005
        run: |
          node scripts/ux-audit.js \
            --url ${{ secrets.STAGING_URL }} \
            --report ux-report.html \
            --fail-on-score 70

      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v2
        with:
          name: ux-report
          path: ux-report.html
```

### GitLab CI Example

```yaml
ux-audit:
  stage: test
  image: node:18
  services:
    - ux-analyst:latest
  script:
    - npm install ux-analyzer-skill
    - node scripts/ux-audit.js --url ${STAGING_URL} --fail-on-score 70
  artifacts:
    paths:
      - ux-report.html
    reports:
      performance: performance.json
  only:
    - merge_requests
    - main
```

---

## Part 4: Environment Setup

### .env Configuration

```bash
# Backend configuration
UX_BACKEND_URL=http://localhost:3005
GEMINI_API_KEY=your-actual-api-key

# Optional settings
UX_TIMEOUT=300000              # 5 minutes
UX_STORAGE_PATH=./data/screenshots
UX_LOG_LEVEL=info

# For MCP Server
NODE_ENV=production
MCP_SERVER_PORT=8000
```

### Docker Setup (Optional)

```bash
# Start backend + MCP server with Docker
docker-compose -f ux-analyst-ai/docker-compose.yml up

# Backend: http://localhost:3005
# MCP Server: stdio protocol
```

---

## Part 5: Tool Reference

### Available MCP Tools

#### `ux_analyze_start`
Start a UX analysis

```javascript
{
  "url": "https://example.com",
  "options": {
    "viewports": ["desktop", "tablet", "mobile"],
    "analysisType": "comprehensive",
    "includeAccessibility": true,
    "includeCodeGeneration": true
  }
}
```

#### `ux_analyze_status`
Check progress of running analysis

```javascript
{ "analysisId": "uuid-from-start" }
```

#### `ux_analyze_results`
Get complete analysis results (when ready)

```javascript
{ "analysisId": "uuid-from-start" }
```

#### `ux_analyze_screenshots`
Get captured screenshots

```javascript
{ "analysisId": "uuid-from-start" }
```

#### `ux_analyze_code`
Get generated implementation code

```javascript
{ "analysisId": "uuid-from-start" }
```

#### `ux_health_check`
Verify backend is healthy

```javascript
{}
```

---

## Part 6: Troubleshooting

### Backend Connection Issues

```bash
# Check backend is running
curl http://localhost:3005/api/health

# Check logs
docker-compose -f ux-analyst-ai/docker-compose.yml logs backend

# Restart backend
npm restart  # or docker-compose restart
```

### MCP Server Not Appearing in Claude

1. Verify path in `claude_desktop_config.json` is absolute
2. Check Node.js is in PATH: `which node`
3. Verify permissions: `chmod +x mcp-server/index.js`
4. Check logs: Terminal where Claude runs

### Analysis Timeouts

```bash
# Increase timeout in .env
UX_TIMEOUT=600000  # 10 minutes

# Or use quick analysis
await analyzer.startAnalysis(url, { analysisType: 'quick' });
```

### Missing Screenshots

- Check storage path exists: `mkdir -p data/screenshots`
- Verify permissions: `chmod 755 data/screenshots`
- Check disk space: `df -h`
- Verify Puppeteer can access URL

---

## Part 7: Best Practices

### For MCP Server (Claude Desktop)

✅ **Do:**
- Use absolute paths in config
- Monitor progress with status checks
- Show screenshots to discuss visual issues
- Ask Claude to explain recommendations
- Use code generation for implementation

❌ **Don't:**
- Run multiple analyses in parallel (queue them)
- Use relative paths in config
- Skip accessibility checks for production sites
- Run on untrusted URLs without review

### For Claude Code Skill

✅ **Do:**
- Set appropriate timeouts for CI/CD
- Save reports for audit trails
- Fail builds on critical accessibility issues
- Monitor score trends over time
- Use quick mode for frequent checks

❌ **Don't:**
- Ignore error handling
- Run comprehensive analysis for every PR
- Block deployments on style issues alone
- Run without proper error reporting

---

## Getting Help

- **Documentation**: `ux-analyst-ai/README.md`
- **MCP Docs**: `ux-analyst-ai/mcp-server/README.md`
- **Issues**: GitHub issues in this repo
- **Questions**: Ask Claude to explain analysis results

---

## Next Steps

1. ✅ Start backend: `npm run start:backend`
2. ✅ Configure Claude Desktop (MCP Server)
3. ✅ Test with: "Analyze https://example.com"
4. ✅ Create Claude Code skill script
5. ✅ Integrate into CI/CD pipeline
6. ✅ Set up monitoring/reports

Enjoy better UX for your websites! 🚀
