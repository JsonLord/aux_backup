#!/usr/bin/env node

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ToolSchema,
} from '@modelcontextprotocol/sdk/types.js';
import fetch from 'node-fetch';

// Configuration
const BACKEND_URL = process.env.UX_BACKEND_URL || 'http://localhost:3005';
const API_KEY = process.env.GEMINI_API_KEY;

class UXAnalystMCPServer {
  constructor() {
    this.server = new Server(
      {
        name: 'ux-analyst-ai',
        version: '1.0.0',
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );

    this.setupToolHandlers();
    this.setupErrorHandling();
  }

  setupErrorHandling() {
    this.server.onerror = (error) => console.error('[MCP Error]', error);
    process.on('SIGINT', async () => {
      await this.server.close();
      process.exit(0);
    });
  }

  setupToolHandlers() {
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [
        {
          name: 'ux_analyze_start',
          description: 'Start a comprehensive UX analysis of a website',
          inputSchema: {
            type: 'object',
            properties: {
              url: {
                type: 'string',
                description: 'The website URL to analyze',
              },
              options: {
                type: 'object',
                properties: {
                  viewports: {
                    type: 'array',
                    items: { type: 'string' },
                    description: 'Viewports to analyze: desktop, tablet, mobile',
                    default: ['desktop', 'tablet', 'mobile'],
                  },
                  analysisType: {
                    type: 'string',
                    enum: ['quick', 'comprehensive'],
                    description: 'Type of analysis to perform',
                    default: 'comprehensive',
                  },
                  includeAccessibility: {
                    type: 'boolean',
                    description: 'Include accessibility analysis',
                    default: true,
                  },
                  includeCodeGeneration: {
                    type: 'boolean',
                    description: 'Generate implementation code for improvements',
                    default: true,
                  },
                },
              },
            },
            required: ['url'],
          },
        },
        {
          name: 'ux_analyze_status',
          description: 'Check the status and progress of a running UX analysis',
          inputSchema: {
            type: 'object',
            properties: {
              analysisId: {
                type: 'string',
                description: 'The analysis ID returned from ux_analyze_start',
              },
            },
            required: ['analysisId'],
          },
        },
        {
          name: 'ux_analyze_results',
          description: 'Get the complete results of a finished UX analysis',
          inputSchema: {
            type: 'object',
            properties: {
              analysisId: {
                type: 'string',
                description: 'The analysis ID',
              },
            },
            required: ['analysisId'],
          },
        },
        {
          name: 'ux_analyze_screenshots',
          description: 'Get screenshot URLs from the analysis for visual inspection',
          inputSchema: {
            type: 'object',
            properties: {
              analysisId: {
                type: 'string',
                description: 'The analysis ID',
              },
            },
            required: ['analysisId'],
          },
        },
        {
          name: 'ux_analyze_code',
          description: 'Get the generated implementation code for UX improvements',
          inputSchema: {
            type: 'object',
            properties: {
              analysisId: {
                type: 'string',
                description: 'The analysis ID',
              },
            },
            required: ['analysisId'],
          },
        },
        {
          name: 'ux_health_check',
          description: 'Check if the UX analysis backend is running and healthy',
          inputSchema: {
            type: 'object',
            properties: {},
          },
        },
      ],
    }));

    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const { name, arguments: args } = request.params;

      try {
        switch (name) {
          case 'ux_analyze_start':
            return await this.startAnalysis(args.url, args.options || {});

          case 'ux_analyze_status':
            return await this.getAnalysisStatus(args.analysisId);

          case 'ux_analyze_results':
            return await this.getAnalysisResults(args.analysisId);

          case 'ux_analyze_screenshots':
            return await this.getAnalysisScreenshots(args.analysisId);

          case 'ux_analyze_code':
            return await this.getAnalysisCode(args.analysisId);

          case 'ux_health_check':
            return await this.healthCheck();

          default:
            throw new Error(`Unknown tool: ${name}`);
        }
      } catch (error) {
        return {
          content: [
            {
              type: 'text',
              text: `Error: ${error.message}`,
            },
          ],
        };
      }
    });
  }

  async makeBackendRequest(endpoint, options = {}) {
    const url = `${BACKEND_URL}/api/${endpoint}`;

    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`Backend request failed: ${response.status} ${errorText}`);
    }

    return response.json();
  }

  async startAnalysis(url, options) {
    try {
      // Validate URL
      new URL(url);
    } catch (error) {
      throw new Error(`Invalid URL: ${url}`);
    }

    const requestBody = {
      url,
      options: {
        viewports: options.viewports || ['desktop', 'tablet', 'mobile'],
        analysisType: options.analysisType || 'comprehensive',
        includeAccessibility: options.includeAccessibility !== false,
        includeCodeGeneration: options.includeCodeGeneration !== false,
      },
    };

    const result = await this.makeBackendRequest('analyze', {
      method: 'POST',
      body: JSON.stringify(requestBody),
    });

    return {
      content: [
        {
          type: 'text',
          text: `🚀 UX Analysis started for ${url}\\n\\nAnalysis ID: ${result.analysisId}\\nStatus: ${result.status}\\n\\nI'll monitor the progress and let you know when it's complete. This typically takes 2-5 minutes depending on the analysis type.`,
        },
      ],
    };
  }

  async getAnalysisStatus(analysisId) {
    const result = await this.makeBackendRequest(`analyze/${analysisId}`);

    const progressText = this.formatProgressStatus(result);

    return {
      content: [
        {
          type: 'text',
          text: progressText,
        },
      ],
    };
  }

  formatProgressStatus(result) {
    const { status, progress, stage, url } = result;

    let statusEmoji = '⏳';
    if (status === 'completed') statusEmoji = '✅';
    if (status === 'failed') statusEmoji = '❌';

    let text = `${statusEmoji} **UX Analysis Status**\\n\\n`;
    text += `URL: ${url}\\n`;
    text += `Status: ${status}\\n`;

    if (progress !== undefined) {
      text += `Progress: ${progress}%\\n`;
    }

    if (stage) {
      text += `Current Stage: ${stage}\\n`;
    }

    if (status === 'completed') {
      text += '\\n🎉 Analysis complete! Use ux_analyze_results to see the findings.';
    } else if (status === 'failed') {
      text += `\\n❌ Analysis failed: ${result.errorMessage || 'Unknown error'}`;
    } else {
      text += '\\n⏳ Analysis in progress... I can check again in a moment.';
    }

    return text;
  }

  async getAnalysisResults(analysisId) {
    const result = await this.makeBackendRequest(`analyze/${analysisId}`);

    if (result.status !== 'completed') {
      return {
        content: [
          {
            type: 'text',
            text: `Analysis not yet complete. Status: ${result.status}. Use ux_analyze_status to monitor progress.`,
          },
        ],
      };
    }

    const analysis = result.results;
    let text = `# 📊 UX Analysis Results\\n\\n`;
    text += `**Website:** ${result.url}\\n`;
    text += `**Completed:** ${new Date(result.completedAt).toLocaleString()}\\n\\n`;

    // Summary
    if (analysis.final_report?.summary) {
      const summary = analysis.final_report.summary;
      text += `## 🎯 Overall Assessment\\n\\n`;
      text += `**Grade:** ${summary.overallGrade || 'N/A'}\\n`;
      text += `**UX Score:** ${summary.uxScore || 'N/A'}/100\\n`;
      text += `**Total Issues:** ${summary.totalIssues || 0}\\n\\n`;
    }

    // Key Findings
    if (analysis.ux_critique?.recommendations) {
      text += `## 🔍 Key Recommendations\\n\\n`;
      analysis.ux_critique.recommendations.slice(0, 5).forEach((rec, i) => {
        text += `${i + 1}. **${rec.title || rec.category}**\\n`;
        text += `   ${rec.description || rec.recommendation}\\n`;
        text += `   *Priority: ${rec.priority || 'Medium'}*\\n\\n`;
      });
    }

    // Accessibility
    if (analysis.accessibility) {
      text += `## ♿ Accessibility\\n\\n`;
      text += `**Score:** ${analysis.accessibility.score}/100\\n`;
      text += `**Violations:** ${analysis.accessibility.totalViolations || 0}\\n\\n`;
    }

    text += `\\n💡 Use ux_analyze_screenshots to see the captured screens, or ux_analyze_code to get implementation suggestions.`;

    return {
      content: [
        {
          type: 'text',
          text: text,
        },
      ],
    };
  }

  async getAnalysisScreenshots(analysisId) {
    const result = await this.makeBackendRequest(`analyze/${analysisId}`);

    if (result.status !== 'completed') {
      return {
        content: [
          {
            type: 'text',
            text: `Analysis not yet complete. Status: ${result.status}`,
          },
        ],
      };
    }

    const screenshots = result.screenshots || [];

    if (screenshots.length === 0) {
      return {
        content: [
          {
            type: 'text',
            text: 'No screenshots available for this analysis.',
          },
        ],
      };
    }

    const content = [
      {
        type: 'text',
        text: `📸 **Screenshots from UX Analysis**\\n\\nCaptured ${screenshots.length} screenshots across different viewports:\\n\\n`,
      },
    ];

    // Add each screenshot as an image
    screenshots.forEach((screenshot, i) => {
      content.push({
        type: 'image',
        data: `${BACKEND_URL}${screenshot.url}`,
        mimeType: 'image/png',
      });

      content.push({
        type: 'text',
        text: `**${screenshot.viewport || 'Unknown'} Viewport** (${screenshot.width}x${screenshot.height})\\n\\n`,
      });
    });

    return { content };
  }

  async getAnalysisCode(analysisId) {
    const result = await this.makeBackendRequest(`analyze/${analysisId}/code`);

    if (!result.success || !result.code) {
      return {
        content: [
          {
            type: 'text',
            text: 'No implementation code available for this analysis.',
          },
        ],
      };
    }

    const code = result.code;
    let text = `# 💻 Implementation Code\\n\\n`;
    text += `Generated implementation suggestions for improving the UX of your website.\\n\\n`;

    // HTML improvements
    if (code.html && code.html.length > 0) {
      text += `## HTML Improvements\\n\\n`;
      code.html.forEach((item, i) => {
        text += `### ${item.title}\\n\\n`;
        text += `\`\`\`html\\n${item.code}\\n\`\`\`\\n\\n`;
        text += `**Instructions:** ${item.instructions}\\n\\n`;
      });
    }

    // CSS improvements
    if (code.css && code.css.length > 0) {
      text += `## CSS Improvements\\n\\n`;
      code.css.forEach((item, i) => {
        text += `### ${item.title}\\n\\n`;
        text += `\`\`\`css\\n${item.code}\\n\`\`\`\\n\\n`;
        text += `**Instructions:** ${item.instructions}\\n\\n`;
      });
    }

    // JavaScript improvements
    if (code.javascript && code.javascript.length > 0) {
      text += `## JavaScript Improvements\\n\\n`;
      code.javascript.forEach((item, i) => {
        text += `### ${item.title}\\n\\n`;
        text += `\`\`\`javascript\\n${item.code}\\n\`\`\`\\n\\n`;
        text += `**Instructions:** ${item.instructions}\\n\\n`;
      });
    }

    return {
      content: [
        {
          type: 'text',
          text: text,
        },
      ],
    };
  }

  async healthCheck() {
    try {
      const result = await this.makeBackendRequest('health');

      return {
        content: [
          {
            type: 'text',
            text: `✅ UX Analysis backend is healthy\\n\\nStatus: ${result.status}\\nUptime: ${result.uptime}\\nVersion: ${result.version || 'Unknown'}`,
          },
        ],
      };
    } catch (error) {
      return {
        content: [
          {
            type: 'text',
            text: `❌ UX Analysis backend is not available\\n\\nError: ${error.message}\\n\\nMake sure the backend is running at ${BACKEND_URL}`,
          },
        ],
      };
    }
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error('UX Analyst MCP server running on stdio');
  }
}

const server = new UXAnalystMCPServer();
server.run().catch(console.error);