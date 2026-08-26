#!/usr/bin/env node

/**
 * Claude Code Integration Example
 * Shows how to use UX Analyst AI within Claude Code workflows
 *
 * Usage:
 *   node claude-code-integration.js <url> [options]
 *   node claude-code-integration.js https://example.com --comprehensive
 *   node claude-code-integration.js https://example.com --quick --mobile-only
 */

const http = require('http');
const https = require('https');

class UXAnalyzerClient {
  constructor(backendUrl = process.env.UX_BACKEND_URL || 'http://localhost:3005') {
    this.backendUrl = backendUrl;
    this.isHttps = backendUrl.startsWith('https');
  }

  async request(endpoint, options = {}) {
    return new Promise((resolve, reject) => {
      const url = new URL(`${this.backendUrl}/api/${endpoint}`);
      const protocol = this.isHttps ? https : http;

      const reqOptions = {
        method: options.method || 'GET',
        headers: {
          'Content-Type': 'application/json',
          ...options.headers
        }
      };

      const req = protocol.request(url, reqOptions, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          if (res.statusCode >= 400) {
            reject(new Error(`HTTP ${res.statusCode}: ${data}`));
          } else {
            try {
              resolve(JSON.parse(data));
            } catch {
              resolve(data);
            }
          }
        });
      });

      req.on('error', reject);
      if (options.body) req.write(JSON.stringify(options.body));
      req.end();
    });
  }

  async startAnalysis(url, options = {}) {
    const result = await this.request('analyze', {
      method: 'POST',
      body: {
        url,
        options: {
          viewports: options.viewports || ['desktop', 'tablet', 'mobile'],
          analysisType: options.analysisType || 'comprehensive',
          includeAccessibility: options.includeAccessibility !== false,
          includeCodeGeneration: options.includeCodeGeneration !== false
        }
      }
    });
    return result.analysisId;
  }

  async getStatus(analysisId) {
    return this.request(`analyze/${analysisId}`);
  }

  async getResults(analysisId) {
    return this.request(`analyze/${analysisId}`);
  }

  async getCode(analysisId) {
    return this.request(`analyze/${analysisId}/code`);
  }

  async waitForCompletion(analysisId, onProgress, maxWaitTime = 600000) {
    const startTime = Date.now();
    const pollInterval = 3000; // 3 seconds

    while (Date.now() - startTime < maxWaitTime) {
      const status = await this.getStatus(analysisId);

      if (onProgress) {
        onProgress({
          status: status.status,
          percent: status.progress || 0,
          stage: status.stage || 'initializing'
        });
      }

      if (status.status === 'completed') {
        return status;
      } else if (status.status === 'failed') {
        throw new Error(`Analysis failed: ${status.errorMessage || 'Unknown error'}`);
      }

      // Wait before next poll
      await new Promise(resolve => setTimeout(resolve, pollInterval));
    }

    throw new Error(`Analysis timeout after ${maxWaitTime}ms`);
  }
}

/**
 * Main analysis function - use this in your Claude Code workflows
 */
async function analyzeWebsite(url, options = {}) {
  const client = new UXAnalyzerClient();

  console.log('\n🚀 UX Analyzer for Claude Code');
  console.log('='.repeat(50));
  console.log(`📍 Target: ${url}`);
  console.log(`⚙️  Mode: ${options.analysisType || 'comprehensive'}`);

  try {
    // Check backend health
    console.log('\n🔍 Checking backend...');
    try {
      const health = await client.request('health');
      console.log(`✅ Backend healthy (${health.uptime})`);
    } catch (error) {
      console.error(`❌ Backend not available: ${error.message}`);
      console.error(`   Make sure UX_BACKEND_URL is set correctly`);
      process.exit(1);
    }

    // Start analysis
    console.log('\n🎬 Starting analysis...');
    const analysisId = await client.startAnalysis(url, {
      analysisType: options.analysisType || 'comprehensive',
      viewports: options.viewports,
      includeAccessibility: options.accessibility !== false,
      includeCodeGeneration: true
    });
    console.log(`✅ Analysis started (ID: ${analysisId})`);

    // Wait for completion with progress
    console.log('\n⏳ Monitoring progress...');
    const result = await client.waitForCompletion(analysisId, (progress) => {
      const bar = '█'.repeat(Math.floor(progress.percent / 5)) +
                  '░'.repeat(20 - Math.floor(progress.percent / 5));
      console.log(`   [${bar}] ${progress.percent}% - ${progress.stage}`);
    });

    // Display results
    console.log('\n✨ Analysis Complete!');
    console.log('-'.repeat(50));

    if (result.results?.final_report?.summary) {
      const summary = result.results.final_report.summary;
      console.log(`\n📊 Overall Assessment:`);
      console.log(`   Grade: ${summary.overallGrade || 'N/A'}`);
      console.log(`   UX Score: ${summary.uxScore || 'N/A'}/100`);
      console.log(`   Total Issues: ${summary.totalIssues || 0}`);
    }

    // Accessibility summary
    if (result.results?.accessibility) {
      const a11y = result.results.accessibility;
      console.log(`\n♿ Accessibility:`);
      console.log(`   Score: ${a11y.score}/100`);
      console.log(`   Violations: ${a11y.totalViolations || 0}`);
    }

    // Key recommendations
    if (result.results?.ux_critique?.recommendations) {
      const recs = result.results.ux_critique.recommendations;
      console.log(`\n💡 Top Recommendations:`);
      recs.slice(0, 5).forEach((rec, i) => {
        console.log(`   ${i + 1}. ${rec.title || rec.category}`);
        if (rec.priority) console.log(`      Priority: ${rec.priority}`);
      });
    }

    // Code generation summary
    if (options.showCode) {
      console.log('\n💻 Fetching implementation code...');
      const code = await client.getCode(analysisId);
      if (code.code) {
        const { html = [], css = [], javascript = [] } = code.code;
        console.log(`   HTML improvements: ${html.length}`);
        console.log(`   CSS improvements: ${css.length}`);
        console.log(`   JavaScript improvements: ${javascript.length}`);
      }
    }

    console.log('\n' + '='.repeat(50));
    console.log('✅ Analysis complete!\n');

    return result;
  } catch (error) {
    console.error(`\n❌ Error: ${error.message}`);
    process.exit(1);
  }
}

/**
 * Parse command line arguments
 */
function parseArgs() {
  const args = process.argv.slice(2);

  if (args.length === 0) {
    console.log('Usage: node claude-code-integration.js <url> [options]');
    console.log('\nOptions:');
    console.log('  --quick              Fast analysis (skip some checks)');
    console.log('  --comprehensive      Full analysis (default)');
    console.log('  --mobile-only        Only analyze mobile viewport');
    console.log('  --desktop-only       Only analyze desktop viewport');
    console.log('  --code               Show generated code');
    console.log('  --no-accessibility   Skip accessibility checks');
    console.log('\nExamples:');
    console.log('  node claude-code-integration.js https://example.com');
    console.log('  node claude-code-integration.js https://example.com --quick --code');
    process.exit(0);
  }

  const url = args[0];
  const options = {
    analysisType: args.includes('--quick') ? 'quick' : 'comprehensive',
    showCode: args.includes('--code'),
    accessibility: !args.includes('--no-accessibility')
  };

  // Viewport selection
  if (args.includes('--mobile-only')) {
    options.viewports = ['mobile'];
  } else if (args.includes('--desktop-only')) {
    options.viewports = ['desktop'];
  }

  return { url, options };
}

// Run if called directly
if (require.main === module) {
  const { url, options } = parseArgs();
  analyzeWebsite(url, options).catch(console.error);
}

module.exports = { UXAnalyzerClient, analyzeWebsite };
