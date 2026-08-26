# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains documentation for two AI-powered projects focused on UX analysis and documentation validation:

1. **DocuVision** - AI-powered documentation testing system that validates documentation accuracy by having AI read step-by-step instructions and use computer vision to verify applications behave as documented
2. **UX Analyst AI** - AI-powered UX analysis tool that provides instant expert-level feedback on website design and usability

## Project Architecture

### DocuVision System Components
- **Document Parser**: Claude AI integration for parsing documentation into executable steps
- **Test Executor**: Ui.Vision RPA integration for computer vision automation
- **Validation Engine**: Screenshot comparison and visual verification
- **Orchestration Service**: Node.js/Python backend coordinating all components

### UX Analyst AI Components
- **Screenshot Service**: Puppeteer-based capture across multiple viewports
- **Vision Analyzer**: OpenCV.js for visual hierarchy and UI component detection
- **AI Critique Engine**: Claude API integration for UX analysis and recommendations
- **Analysis Pipeline**: Express.js backend orchestrating analysis workflow

## Technology Stack

### DocuVision
- Backend: Node.js/Python
- AI: Claude API for document parsing
- Automation: Ui.Vision RPA browser extension
- Storage: Local filesystem (JSON/SQLite)
- Reporting: HTML/JSON output

### UX Analyst AI
- Backend: Node.js with Express
- Frontend: React with Vite, Tailwind CSS
- Computer Vision: OpenCV.js, Puppeteer
- AI: Claude API for critique generation
- Accessibility: Axe-core integration
- Database: SQLite (development), PostgreSQL (production)

## Development Commands

Since this is a documentation-only repository with no package.json or build system, there are no standard development commands. The documentation serves as specifications for implementing these systems in separate codebases.

## Key Documentation Files

- `docs/implementation_plan.md` - Technical implementation strategy with code examples and architecture details
- `docs/ui_vision_docs_tester_prd.md` - Product requirements document for DocuVision
- `docs/ux_analyst_ai_specs.md` - MVP development specification for UX Analyst AI
- `docs/gtm_plan.md` - Go-to-market strategy
- `docs/ux_accessibility_ai_opportunity.md` - Market opportunity analysis

## Implementation Notes

### DocuVision Implementation
- Uses Claude API for natural language processing of documentation
- Integrates with Ui.Vision RPA for visual automation
- Implements screenshot comparison using computer vision libraries
- Requires browser automation setup and visual recognition capabilities

### UX Analyst AI Implementation
- Puppeteer integration for multi-viewport screenshot capture
- OpenCV.js for visual analysis of UI components and hierarchy
- Claude API integration for generating UX critiques and recommendations
- Axe-core for accessibility scanning and validation

## Development Workflow

When implementing either system:
1. Start with the core AI integration (Claude API setup)
2. Implement screenshot/automation capabilities
3. Build analysis and validation engines
4. Create reporting and user interfaces
5. Add CI/CD integration and testing

Both projects are designed as MVP implementations that can be extended with additional features and enterprise capabilities.