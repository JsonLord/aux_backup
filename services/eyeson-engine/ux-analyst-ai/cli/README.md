# UX Analyst CLI

A command-line interface for AI-powered UX analysis of websites.

## Installation

### Option 1: NPM Package (Recommended)

```bash
# Install globally
npm install -g ux-analyst-cli

# Or run directly with npx
npx ux-analyst-cli https://example.com
```

### Option 2: Local Development

```bash
# Clone and install dependencies
cd ux-analyst-ai/cli
npm install

# Link for global use
npm link

# Or run directly
node bin/ux-analyze.js https://example.com
```

## Quick Start

```bash
# Basic analysis
ux-analyze https://example.com

# Interactive mode
ux-analyze interactive

# Quick analysis with code generation
ux-analyze https://example.com --quick --code

# Full analysis with custom output
ux-analyze https://example.com --format html --output ./my-analysis
```

## Commands

### `ux-analyze <url> [options]`

Analyze a website and generate UX recommendations.

**Arguments:**
- `<url>` - Website URL to analyze

**Options:**
- `-o, --output <dir>` - Output directory (default: `./ux-analysis`)
- `-f, --format <format>` - Output format: `json`, `html`, `markdown` (default: `json`)
- `-v, --viewports <list>` - Comma-separated viewports (default: `desktop,tablet,mobile`)
- `--quick` - Run quick analysis (faster, less detailed)
- `--code` - Generate implementation code
- `--accessibility` - Include accessibility analysis
- `--config <file>` - Configuration file path
- `--api-key <key>` - Gemini API key

**Examples:**
```bash
# Comprehensive analysis
ux-analyze https://mysite.com --format html --code --accessibility

# Quick mobile-only analysis
ux-analyze https://mysite.com --quick --viewports mobile

# Custom output location
ux-analyze https://mysite.com --output /path/to/results
```

### `ux-analyze interactive`

Interactive mode with guided prompts.

```bash
ux-analyze interactive
# or
ux-analyze i
```

### `ux-analyze config`

Configure CLI settings (API key, defaults).

```bash
ux-analyze config
```

## Configuration

### Environment Variables

```bash
# Required: Gemini API key
export GEMINI_API_KEY="your-api-key-here"
```

### Configuration File

Create a `ux-config.json` file:

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
  }
}
```

Use with: `ux-analyze https://example.com --config ux-config.json`

## Output Formats

### JSON (Machine-readable)
```bash
ux-analyze https://example.com --format json
```
- Raw analysis data
- Perfect for CI/CD integration
- Parseable by other tools

### HTML (Human-readable)
```bash
ux-analyze https://example.com --format html
```
- Beautiful visual reports
- Screenshots included
- Implementation code embedded

### Markdown (Documentation-friendly)
```bash
ux-analyze https://example.com --format markdown
```
- README-compatible format
- Great for documentation
- Version control friendly

## Integration Examples

### CI/CD Pipeline

```yaml
# GitHub Actions example
- name: UX Analysis
  run: |
    npx ux-analyst-cli https://my-staging-site.com \
      --format json \
      --output ./ux-reports \
      --quick

    # Upload results as artifacts
- uses: actions/upload-artifact@v3
  with:
    name: ux-analysis
    path: ./ux-reports
```

### NPM Scripts

```json
{
  "scripts": {
    "ux-check": "ux-analyze https://localhost:3000 --quick",
    "ux-full": "ux-analyze https://localhost:3000 --code --accessibility",
    "ux-mobile": "ux-analyze https://localhost:3000 --viewports mobile --quick"
  }
}
```

### Automated Reports

```bash
#!/bin/bash
# analyze-sites.sh

sites=(
  "https://example.com"
  "https://staging.example.com"
  "https://dev.example.com"
)

for site in "${sites[@]}"; do
  echo "Analyzing $site..."
  ux-analyze "$site" --format html --output "./reports/$(basename $site)"
done
```

## Features

### 🚀 **Fast Analysis**
- Quick mode for CI/CD pipelines
- Progressive analysis with real-time updates

### 🎯 **Comprehensive Reports**
- UX recommendations with AI insights
- Accessibility compliance checking
- Multi-viewport screenshot capture

### 💻 **Implementation Ready**
- Generate HTML, CSS, JavaScript fixes
- Step-by-step implementation guides
- Copy-paste ready code snippets

### 🔧 **Developer Friendly**
- Multiple output formats
- Easy CI/CD integration
- Configurable analysis options

### 📊 **Multiple Viewports**
- Desktop, tablet, mobile analysis
- Responsive design insights
- Cross-device compatibility checking

## API Integration

The CLI can also be used programmatically:

```javascript
const { UXAnalyzer } = require('ux-analyst-cli');

const analyzer = new UXAnalyzer({
  ai: { geminiApiKey: process.env.GEMINI_API_KEY }
});

const result = await analyzer.analyze('https://example.com', {
  viewports: ['desktop', 'mobile'],
  includeCodeGeneration: true
});

console.log('UX Score:', result.report.summary.uxScore);
```

## Troubleshooting

### Common Issues

**"API key is required"**
```bash
# Set environment variable
export GEMINI_API_KEY="your-key"

# Or use --api-key flag
ux-analyze https://example.com --api-key "your-key"
```

**"Analysis timeout"**
```bash
# Use quick mode for faster analysis
ux-analyze https://example.com --quick

# Or increase timeout in config
```

**"Permission denied"**
```bash
# Make sure the CLI is executable
chmod +x bin/ux-analyze.js

# Or run with node directly
node bin/ux-analyze.js https://example.com
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License - see LICENSE file for details.