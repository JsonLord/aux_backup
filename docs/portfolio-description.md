# UX Analyst AI - Portfolio Project Description

## UX Analyst AI

I built an **AI-powered UX analysis platform** that combines computer vision, accessibility scanning, and code generation to provide comprehensive website critiques with implementation-ready solutions.

The challenge was creating a tool that could **analyze websites as humans do** - considering visual hierarchy, accessibility, and user experience patterns - while generating actionable code fixes. Most existing tools either provide surface-level metrics or require manual interpretation of results.

My solution integrates **Google Gemini's vision capabilities** with systematic UX evaluation frameworks. The system captures multi-viewport screenshots (desktop, tablet, mobile), runs accessibility scans, and uses AI to identify both technical issues and **design anti-patterns common in AI-generated websites** - like excessive emoji use, generic layouts, and robotic copy.

**Key technical challenges solved:**
- Browser pool management with circuit breaker patterns for reliable screenshot capture
- Structured AI prompting to generate consistent, actionable UX critiques
- Code generation that produces framework-agnostic implementation solutions
- Multiple interface patterns: web dashboard, CLI tool, and **MCP server integration with Claude**

The MCP server integration was particularly interesting - it allows natural language UX analysis through Claude, where you can ask "analyze this website's mobile experience" and get progressive updates, visual analysis, and code recommendations in conversation format.

**Architecture includes:**
- Express backend with dependency injection
- React frontend with real-time progress tracking
- CLI tool with interactive prompts and multiple output formats
- SQLite for analysis storage with comprehensive reporting

**Tools used:** Node.js, React, Puppeteer, Google Gemini AI, Axe accessibility engine, Commander.js, Model Context Protocol

[View Repository](https://github.com/grzetich/eyeson)