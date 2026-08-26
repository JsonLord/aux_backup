# UX Analyzer - Quick Start for AI Tools

Get UX Analyst AI working in 5 minutes.

## 🎯 Choose Your Integration

### Option 1: Claude Desktop (MCP Server) - 3 minutes

Natural language interface for Claude Desktop.

```bash
# 1. Start backend
cd ux-analyst-ai/backend
npm install && npm start

# 2. Update Claude config file
# Windows: %APPDATA%/Claude/claude_desktop_config.json
# macOS: ~/Library/Application Support/Claude/claude_desktop_config.json

# Add to mcpServers section:
{
  "ux-analyst": {
    "command": "node",
    "args": ["/absolute/path/to/eyeson/ux-analyst-ai/mcp-server/index.js"],
    "env": {
      "UX_BACKEND_URL": "http://localhost:3005",
      "GEMINI_API_KEY": "your-key-here"
    }
  }
}

# 3. Restart Claude Desktop

# 4. Ask Claude: "Analyze https://example.com for UX issues"
```

**That's it!** Claude can now analyze any website.

---

### Option 2: Claude Code Skill - 2 minutes

Programmatic integration for CI/CD and workflows.

```bash
# 1. Start backend (same as above)
cd ux-analyst-ai/backend
npm start

# 2. Copy the integration script
cp ux-analyst-ai/examples/claude-code-integration.js ./

# 3. Run it
node claude-code-integration.js https://example.com

# Output:
# 🚀 UX Analyzer for Claude Code
# 📍 Target: https://example.com
# ✅ Backend healthy
# ✅ Analysis started
# ⏳ [████████░░░░░░░░░░] 45% - Running AI analysis...
# ✨ Analysis Complete!
# 📊 Grade: A-, UX Score: 89/100
# 💡 Issues found: 3
```

**Use in your scripts:**

```javascript
const { analyzeWebsite } = require('./claude-code-integration');

const result = await analyzeWebsite('https://example.com', {
  analysisType: 'comprehensive',
  showCode: true
});

console.log(`Score: ${result.results.final_report.summary.uxScore}/100`);
```

---

### Option 3: GitHub Actions CI/CD - 5 minutes

Automatic UX regression testing on every PR.

```yaml
# .github/workflows/ux-audit.yml
name: UX Audit

on: [pull_request, push]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-node@v2
        with:
          node-version: 18

      - name: Install dependencies
        run: npm install

      - name: Run UX analysis
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: |
          docker-compose -f ux-analyst-ai/docker-compose.yml up -d
          sleep 5
          node ux-analyst-ai/examples/claude-code-integration.js ${{ secrets.STAGING_URL }}

      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v2
        with:
          name: ux-audit-report
          path: ux-report.html
```

---

## 📊 What You Can Do

Once set up:

### With Claude Desktop
```
"Analyze https://airbnb.com and tell me the top 3 UX issues"
"Show me the accessibility violations on https://mysite.com"
"Generate code to fix the mobile layout issues"
"Compare UX of my site vs competitor.com"
```

### With Claude Code
```javascript
// Audit your staging site before deployment
await analyzeWebsite(process.env.STAGING_URL, { analysisType: 'quick' });

// Generate reports for stakeholders
const report = await generateReport(analysisId);
await uploadToCloud(report);

// Fail build if score drops below threshold
if (result.score < 75) process.exit(1);
```

### With CI/CD
- Every PR: Quick UX audit
- Before deployment: Comprehensive accessibility check
- Weekly: Monitor UX score trends
- On-demand: Deep analysis for specific pages

---

## 🛠️ Troubleshooting

**"Backend not available"**
```bash
# Make sure backend is running
curl http://localhost:3005/api/health

# If not, start it
cd ux-analyst-ai/backend && npm start
```

**"No GEMINI_API_KEY"**
```bash
# Get free API key at https://aistudio.google.com/
# Add to .env or export as environment variable
export GEMINI_API_KEY=your-key-here
```

**"Path not found in config"**
```bash
# Use absolute path in claude_desktop_config.json
# ❌ "args": ["./mcp-server/index.js"]
# ✅ "args": ["/Users/name/eyeson/ux-analyst-ai/mcp-server/index.js"]
```

---

## 📚 Full Documentation

- **Setup Guide**: `UX_ANALYZER_INTEGRATION.md` (comprehensive)
- **Skill Docs**: `.claude/ux-analyzer-skill.md`
- **Code Example**: `ux-analyst-ai/examples/claude-code-integration.js`
- **MCP Server**: `ux-analyst-ai/mcp-server/README.md`

---

## 🚀 Next Steps

**Ready to try?**

1. Pick your integration (Claude Desktop, Code, or CI/CD)
2. Follow the 2-5 minute setup above
3. Run your first analysis
4. Check the docs for advanced features

**Want to extend it?**

- Add custom rules for your industry
- Integrate with your design system
- Create industry-specific reports
- Build your own analysis tools on top

---

## 💡 Real-World Examples

### E-Commerce Site QA
```bash
node claude-code-integration.js https://store.example.com \
  --comprehensive --code
# Get full audit before launch
```

### Accessibility Compliance
```bash
node claude-code-integration.js https://nonprofit.org \
  --accessibility
# Ensure WCAG compliance across all viewports
```

### Mobile-First Development
```bash
node claude-code-integration.js https://app.example.com \
  --mobile-only --quick
# Fast feedback loop while developing
```

### Competitive Analysis
```
(In Claude) "How does example.com compare to competitor.com for UX?"
```

---

## ✨ Features

- ✅ Multi-viewport analysis (desktop, tablet, mobile)
- ✅ Accessibility checking (WCAG standards)
- ✅ Visual design analysis (color, typography, layout)
- ✅ AI-powered recommendations (Gemini vision)
- ✅ Code generation (HTML, CSS, JavaScript)
- ✅ Screenshots (all viewports)
- ✅ Performance scoring
- ✅ HTML reports
- ✅ CI/CD ready
- ✅ MCP protocol compatible

---

**Questions?** Check `UX_ANALYZER_INTEGRATION.md` or ask Claude to explain the analysis! 🎉
