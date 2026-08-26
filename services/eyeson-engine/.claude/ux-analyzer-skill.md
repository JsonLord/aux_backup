# UX Analyzer Skill

Analyze websites for UX issues, accessibility compliance, and generate implementation code to fix problems.

## Usage

### Analyze a Website

```bash
# Quick analysis
ux-analyze https://example.com --quick

# Comprehensive analysis with all checks
ux-analyze https://example.com --comprehensive --code --accessibility

# Mobile-specific analysis
ux-analyze https://example.com --mobile-only

# Custom viewports
ux-analyze https://example.com --viewports desktop,mobile
```

## Features

- **Multi-viewport screenshots** (desktop, tablet, mobile)
- **Visual design analysis** (color, layout, typography)
- **Accessibility compliance** (WCAG standards with Axe-core)
- **AI-powered UX critique** (using Gemini vision)
- **Implementation code generation** (HTML, CSS, JavaScript)
- **Performance scoring** (usability, responsiveness)

## Output

### Quick Output
- UX score and grade
- Top 5 recommendations
- Accessibility summary
- Screenshots (embedded)

### Comprehensive Output
- Full analysis report
- Detailed recommendations with priorities
- Accessibility violations and fixes
- Generated implementation code
- HTML report with interactive elements

## Examples

### Example 1: Analyze Landing Page
```bash
ux-analyze https://my-startup.com --comprehensive --code
```

**Claude Code will:**
1. Capture screenshots across 3 viewports
2. Analyze visual hierarchy and design
3. Check accessibility compliance
4. Generate code to fix issues
5. Save full HTML report

### Example 2: Mobile UX Audit
```bash
ux-analyze https://store.example.com --mobile-only --accessibility
```

**Claude Code will:**
1. Focus on mobile viewport (375px)
2. Identify mobile-specific UX issues
3. Highlight accessibility barriers
4. Suggest touch-friendly improvements

### Example 3: Continuous Integration
```bash
ux-analyze https://staging.company.com --quick --json > report.json
```

**Use case:** Integrate into your CI/CD to catch UX regressions before deployment.

## Environment Variables

```bash
# Backend configuration
UX_BACKEND_URL=http://localhost:3005
GEMINI_API_KEY=your-gemini-api-key-here

# Optional
UX_TIMEOUT=300000  # 5 minutes max analysis time
UX_STORAGE_PATH=./data/screenshots
```

## Integration with Claude Code

Once installed, use in Claude Code workflows:

```javascript
// In Claude Code scripts
const { analyzeUX } = require('ux-analyzer-skill');

const result = await analyzeUX('https://example.com', {
  comprehensive: true,
  includeAccessibility: true,
  includeCodeGeneration: true
});

console.log(`Score: ${result.score}/100`);
console.log(`Issues found: ${result.issues.length}`);
console.log(`Accessibility violations: ${result.accessibility.violations.length}`);
```

## Installation

```bash
# Install the skill
npm install ux-analyzer-skill

# Or use with npx
npx ux-analyzer-skill https://example.com
```

## API Reference

### analyzeUX(url, options)

**Parameters:**
- `url` (string, required): Website URL to analyze
- `options` (object, optional):
  - `comprehensive` (boolean): Full analysis vs quick
  - `viewports` (array): ['desktop', 'tablet', 'mobile']
  - `includeAccessibility` (boolean): Enable a11y checking
  - `includeCodeGeneration` (boolean): Generate code fixes
  - `timeout` (number): Max time in ms

**Returns:**
```javascript
{
  analysisId: "uuid",
  status: "completed",
  score: 85,
  grade: "B+",
  issues: [...],
  accessibility: {...},
  code: {...},
  screenshots: [...],
  completedAt: "2024-01-15T10:30:00Z"
}
```

## Real-World Scenarios

### Redesign QA
```bash
ux-analyze https://new-design.company.com --comprehensive --code
# Gets full audit before launch
```

### Competitor Analysis
```bash
ux-analyze https://competitor.com --quick
# Understand their UX approach quickly
```

### Accessibility Compliance
```bash
ux-analyze https://mysite.com --accessibility
# Ensure WCAG compliance across viewports
```

### Code Generation
```bash
ux-analyze https://example.com --code
# Get implementation code for improvements
```

## Troubleshooting

### Backend Not Running
```bash
# Start backend first
cd ux-analyst-ai/backend
npm start
```

### Missing Screenshots
- Check `UX_STORAGE_PATH` directory permissions
- Verify target URL is accessible
- Ensure Puppeteer can render the page

### Slow Analysis
- Use `--quick` flag for faster results
- Reduce viewports: `--viewports desktop,mobile`
- Check backend system resources

## Next Steps

1. **Start the backend**: `npm run start:backend`
2. **Try a quick analysis**: `ux-analyze https://example.com`
3. **Review generated code**: Check implementation suggestions
4. **Integrate into CI/CD**: Automate UX regression detection
5. **Set up MCP server**: For Claude desktop integration

## More Information

- Full documentation: `ux-analyst-ai/README.md`
- MCP Server docs: `ux-analyst-ai/mcp-server/README.md`
- Backend API: `ux-analyst-ai/backend/README.md`
