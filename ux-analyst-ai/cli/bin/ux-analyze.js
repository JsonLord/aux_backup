#!/usr/bin/env node

const { Command } = require('commander');
const chalk = require('chalk');
const ora = require('ora');
const inquirer = require('inquirer');
const fs = require('fs-extra');
const path = require('path');
require('dotenv').config();

const UXAnalyzer = require('../lib/UXAnalyzer');

const program = new Command();

program
  .name('ux-analyze')
  .description('AI-powered UX analysis for websites')
  .version('1.0.0');

program
  .argument('<url>', 'Website URL to analyze')
  .option('-o, --output <dir>', 'Output directory for results', './ux-analysis')
  .option('-f, --format <format>', 'Output format (json|html|markdown)', 'json')
  .option('-v, --viewports <viewports>', 'Comma-separated viewports (desktop,tablet,mobile)', 'desktop,tablet,mobile')
  .option('--quick', 'Run quick analysis (faster, less detailed)')
  .option('--code', 'Generate implementation code')
  .option('--accessibility', 'Include accessibility analysis')
  .option('--config <file>', 'Configuration file path')
  .option('--api-key <key>', 'Gemini API key (or set GEMINI_API_KEY env var)')
  .action(async (url, options) => {
    try {
      // Validate URL format and security
      if (!isValidUrl(url)) {
        console.error(chalk.red('❌ Invalid URL format. Please provide a valid HTTP/HTTPS URL.'));
        process.exit(1);
      }

      await runAnalysis(url, options);
    } catch (error) {
      console.error(chalk.red('Error:'), error.message);
      process.exit(1);
    }
  });

program
  .command('interactive')
  .alias('i')
  .description('Interactive mode for UX analysis')
  .action(async () => {
    try {
      await runInteractiveMode();
    } catch (error) {
      console.error(chalk.red('Error:'), error.message);
      process.exit(1);
    }
  });

program
  .command('config')
  .description('Configure UX Analyzer settings')
  .action(async () => {
    await configureSettings();
  });

async function runAnalysis(url, options) {
  console.log(chalk.blue.bold('🚀 UX Analyst AI - Command Line Interface\n'));

  // Validate URL
  try {
    new URL(url);
  } catch (error) {
    throw new Error(`Invalid URL: ${url}`);
  }

  // Load configuration
  const config = await loadConfiguration(options);

  // Initialize analyzer
  const analyzer = new UXAnalyzer(config);

  // Parse options
  const analysisOptions = {
    viewports: options.viewports.split(',').map(v => v.trim()),
    analysisType: options.quick ? 'quick' : 'comprehensive',
    includeAccessibility: options.accessibility,
    includeCodeGeneration: options.code,
    outputFormat: options.format,
    outputDir: options.output
  };

  console.log(chalk.cyan('🔍 Analysis Configuration:'));
  console.log(`  • URL: ${chalk.white(url)}`);
  console.log(`  • Viewports: ${chalk.white(analysisOptions.viewports.join(', '))}`);
  console.log(`  • Type: ${chalk.white(analysisOptions.analysisType)}`);
  console.log(`  • Output: ${chalk.white(path.resolve(analysisOptions.outputDir))}`);
  if (analysisOptions.includeAccessibility) console.log(`  • ${chalk.green('✓')} Accessibility analysis`);
  if (analysisOptions.includeCodeGeneration) console.log(`  • ${chalk.green('✓')} Code generation`);
  console.log();

  // Run analysis with progress spinner
  const spinner = ora('Starting UX analysis...').start();

  try {
    const result = await analyzer.analyze(url, analysisOptions, (progress) => {
      spinner.text = `${progress.stage} (${progress.percent}%)`;
    });

    spinner.succeed('Analysis completed!');

    // Save results
    await saveResults(result, analysisOptions);

    // Debug: Log the result structure
    console.log(chalk.yellow('\n🔍 Debug - Result structure:'));
    console.log(`Result keys: ${Object.keys(result).join(', ')}`);
    console.log(`Screenshots: ${result.screenshots ? result.screenshots.length : 0} found`);
    if (result.screenshots && result.screenshots.length > 0) {
      console.log(`Screenshot 0 keys: ${Object.keys(result.screenshots[0]).join(', ')}`);
      console.log(`Screenshot 0 filepath: ${result.screenshots[0].filepath}`);
    }
    console.log(`Implementation code: ${result.implementationCode ? 'Present' : 'Missing'}`);
    if (result.implementationCode) {
      console.log(`Implementation code keys: ${Object.keys(result.implementationCode).join(', ')}`);
    }
    console.log(`Report: ${result.report ? 'Present' : 'Missing'}`);
    if (result.report) {
      console.log(`Report keys: ${Object.keys(result.report).join(', ')}`);
    }
    console.log(`Accessibility: ${result.accessibility ? 'Present' : 'Missing'}`);
    console.log(`Results (raw): ${result.results ? Object.keys(result.results).join(', ') : 'Missing'}`);

    // Display summary
    displaySummary(result, analysisOptions);

  } catch (error) {
    spinner.fail('Analysis failed');
    throw error;
  }
}

async function runInteractiveMode() {
  console.log(chalk.blue.bold('🚀 UX Analyst AI - Interactive Mode\n'));

  const answers = await inquirer.prompt([
    {
      type: 'input',
      name: 'url',
      message: 'Enter the website URL to analyze:',
      validate: (input) => {
        try {
          new URL(input);
          return true;
        } catch {
          return 'Please enter a valid URL';
        }
      }
    },
    {
      type: 'checkbox',
      name: 'viewports',
      message: 'Select viewports to analyze:',
      choices: [
        { name: 'Desktop (1920x1080)', value: 'desktop', checked: true },
        { name: 'Tablet (768x1024)', value: 'tablet', checked: true },
        { name: 'Mobile (375x667)', value: 'mobile', checked: true }
      ],
      validate: (input) => input.length > 0 || 'Please select at least one viewport'
    },
    {
      type: 'list',
      name: 'analysisType',
      message: 'Choose analysis type:',
      choices: [
        { name: 'Comprehensive (detailed analysis)', value: 'comprehensive' },
        { name: 'Quick (faster, basic analysis)', value: 'quick' }
      ],
      default: 'comprehensive'
    },
    {
      type: 'confirm',
      name: 'includeAccessibility',
      message: 'Include accessibility analysis?',
      default: true
    },
    {
      type: 'confirm',
      name: 'includeCodeGeneration',
      message: 'Generate implementation code?',
      default: true
    },
    {
      type: 'list',
      name: 'outputFormat',
      message: 'Choose output format:',
      choices: [
        { name: 'JSON (machine-readable)', value: 'json' },
        { name: 'HTML (human-readable report)', value: 'html' },
        { name: 'Markdown (documentation-friendly)', value: 'markdown' }
      ],
      default: 'html'
    },
    {
      type: 'input',
      name: 'outputDir',
      message: 'Output directory:',
      default: './ux-analysis'
    }
  ]);

  await runAnalysis(answers.url, answers);
}

async function loadConfiguration(options) {
  const config = {
    geminiApiKey: options.apiKey || process.env.GEMINI_API_KEY,
    server: {
      port: 0, // Use random port for CLI mode
      environment: 'cli'
    },
    ai: {
      geminiApiKey: options.apiKey || process.env.GEMINI_API_KEY,
      gemini: {
        apiKey: options.apiKey || process.env.GEMINI_API_KEY,
        model: "gemini-1.5-flash",
        maxRetries: 3,
        baseDelay: 2000,
        timeoutMs: 45000,
        maxConcurrentRequests: 5
      }
    },
    database: {
      type: "sqlite",
      path: "./data/analysis.db"
    },
    screenshots: {
      storagePath: "./data/screenshots",
      viewports: {
        desktop: { width: 1920, height: 1080 },
        tablet: { width: 768, height: 1024 },
        mobile: { width: 375, height: 667 }
      },
      timeoutMs: 120000,
      waitForMs: 10000,
      maxFileSize: 10485760,
      retentionDays: 30
    },
    browser: {
      poolSize: 3,
      headless: "new",
      maxIdleTimeMs: 300000,
      maxLifetimeMs: 1800000,
      launchArgs: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-web-security",
        "--disable-features=VizDisplayCompositor"
      ]
    },
    analysis: {
      maxConcurrentAnalyses: 3,
      timeoutMs: 300000,
      defaultViewports: ["desktop", "tablet", "mobile"]
    }
  };

  if (options.config) {
    const configFile = await fs.readJson(options.config);
    Object.assign(config, configFile);
  }

  if (!config.geminiApiKey) {
    throw new Error('Gemini API key is required. Set GEMINI_API_KEY environment variable or use --api-key option.');
  }

  return config;
}

async function saveResults(result, options) {
  const outputDir = path.resolve(options.outputDir);
  await fs.ensureDir(outputDir);

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const baseFilename = `ux-analysis-${timestamp}`;

  // For HTML reports, embed screenshots as base64
  if (options.outputFormat === 'html' && result.screenshots && result.screenshots.length > 0) {
    console.log(chalk.cyan('📸 Converting screenshots to base64 for HTML embedding...'));

    for (const screenshot of result.screenshots) {
      try {
        // The screenshot object uses 'file_path' not 'filepath'
        const filePath = screenshot.filepath || screenshot.file_path;
        console.log(`🔍 Screenshot path: ${filePath}`);
        console.log(`🔍 Screenshot viewport: ${screenshot.viewport}`);

        if (filePath && await fs.pathExists(filePath)) {
          const imageBuffer = await fs.readFile(filePath);
          screenshot.base64 = imageBuffer.toString('base64');
          screenshot.viewport = screenshot.viewport || screenshot.device;
          console.log(`✓ Converted ${screenshot.viewport} screenshot`);
        } else {
          console.log(`⚠ Screenshot file not found: ${filePath}`);
        }
      } catch (error) {
        console.log(`⚠ Error converting screenshot ${screenshot.device}: ${error.message}`);
      }
    }
  }

  switch (options.outputFormat) {
    case 'json':
      await fs.writeJson(path.join(outputDir, `${baseFilename}.json`), result, { spaces: 2 });
      break;

    case 'html':
      const html = generateHTMLReport(result);
      await fs.writeFile(path.join(outputDir, `${baseFilename}.html`), html);
      break;

    case 'markdown':
      const markdown = generateMarkdownReport(result);
      await fs.writeFile(path.join(outputDir, `${baseFilename}.md`), markdown);
      break;
  }

  // Save implementation code if generated
  if (result.implementationCode) {
    const codeDir = path.join(outputDir, 'implementation-code');
    await fs.ensureDir(codeDir);

    if (result.implementationCode.html?.length > 0) {
      const htmlCode = result.implementationCode.html.map(item =>
        `<!-- ${item.title} -->\n${item.code}\n\n<!-- Instructions: ${item.instructions} -->\n`
      ).join('\n');
      await fs.writeFile(path.join(codeDir, 'improvements.html'), htmlCode);
    }

    if (result.implementationCode.css?.length > 0) {
      const cssCode = result.implementationCode.css.map(item =>
        `/* ${item.title} */\n${item.code}\n\n/* Instructions: ${item.instructions} */\n`
      ).join('\n');
      await fs.writeFile(path.join(codeDir, 'improvements.css'), cssCode);
    }

    if (result.implementationCode.javascript?.length > 0) {
      const jsCode = result.implementationCode.javascript.map(item =>
        `// ${item.title}\n${item.code}\n\n// Instructions: ${item.instructions}\n`
      ).join('\n');
      await fs.writeFile(path.join(codeDir, 'improvements.js'), jsCode);
    }

    // Implementation guide
    if (result.implementationCode.instructions?.length > 0) {
      const guide = `# UX Implementation Guide\n\n${result.implementationCode.instructions.map(item =>
        `## ${item.recommendation}\n\n${item.steps}\n\n**Notes:** ${item.notes}\n`
      ).join('\n')}`;
      await fs.writeFile(path.join(codeDir, 'IMPLEMENTATION_GUIDE.md'), guide);
    }
  }

  console.log(chalk.green(`\n📁 Results saved to: ${outputDir}`));
}

function displaySummary(result, options) {
  console.log(chalk.blue.bold('\n📊 Analysis Summary\n'));

  if (result.report?.summary) {
    const summary = result.report.summary;
    console.log(`${chalk.cyan('Overall Grade:')} ${getGradeEmoji(summary.overallGrade)} ${summary.overallGrade}`);
    console.log(`${chalk.cyan('UX Score:')} ${summary.uxScore || 'N/A'}/100`);
    console.log(`${chalk.cyan('Total Issues:')} ${summary.totalIssues || 0}`);
  }

  if (result.accessibility) {
    console.log(`${chalk.cyan('Accessibility Score:')} ${result.accessibility.score}/100`);
    console.log(`${chalk.cyan('Accessibility Violations:')} ${result.accessibility.totalViolations || 0}`);
  }

  if (result.screenshots?.length > 0) {
    console.log(`${chalk.cyan('Screenshots Captured:')} ${result.screenshots.length}`);
  }

  if (result.implementationCode) {
    const codeTypes = ['html', 'css', 'javascript'].filter(type =>
      result.implementationCode[type]?.length > 0
    );
    if (codeTypes.length > 0) {
      console.log(`${chalk.cyan('Implementation Code:')} ${codeTypes.join(', ').toUpperCase()}`);
    }
  }

  console.log(chalk.green('\n✅ Analysis complete! Check the output directory for detailed results.'));
}

function getGradeEmoji(grade) {
  switch (grade) {
    case 'Excellent': return '🏆';
    case 'Good': return '👍';
    case 'Fair': return '⚠️';
    case 'Poor': return '❌';
    default: return '📊';
  }
}

function generateHTMLReport(result) {
  const screenshots = result.screenshots || [];
  const accessibility = result.accessibility || {};
  const report = result.report || {};
  const implementationCode = result.implementationCode || {};

  return `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'self'; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; font-src 'self' https://cdnjs.cloudflare.com; img-src 'self' data:;">
    <meta http-equiv="X-Content-Type-Options" content="nosniff">
    <meta http-equiv="X-Frame-Options" content="DENY">
    <meta http-equiv="X-XSS-Protection" content="1; mode=block">
    <title>UX Analysis Report - ${escapeHtml(result.url || '')}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f8fafc;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 30px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; font-weight: 300; }
        .header .url { font-size: 1.1em; opacity: 0.9; margin-bottom: 15px; }
        .header .meta { display: flex; gap: 30px; flex-wrap: wrap; }
        .meta-item { background: rgba(255,255,255,0.1); padding: 10px 15px; border-radius: 6px; }

        .summary-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        .card {
            background: white;
            padding: 25px;
            border-radius: 12px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.08);
            border-left: 4px solid #667eea;
        }
        .card h3 { color: #4a5568; margin-bottom: 15px; font-size: 1.1em; }
        .score { font-size: 2.5em; font-weight: bold; color: #667eea; margin-bottom: 5px; }
        .grade { font-size: 1.2em; font-weight: 600; }
        .grade.excellent { color: #48bb78; }
        .grade.good { color: #38b2ac; }
        .grade.fair { color: #ed8936; }
        .grade.poor { color: #e53e3e; }

        .section {
            background: white;
            margin-bottom: 30px;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 15px rgba(0,0,0,0.08);
        }
        .section-header {
            background: #f7fafc;
            padding: 20px 30px;
            border-bottom: 1px solid #e2e8f0;
        }
        .section-header h2 { color: #2d3748; font-size: 1.5em; }
        .section-content { padding: 30px; }

        .screenshots-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 25px;
        }
        .screenshot-item {
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            overflow: hidden;
        }
        .screenshot-item h4 {
            background: #f7fafc;
            padding: 15px;
            color: #4a5568;
            text-transform: capitalize;
        }
        .screenshot-item img {
            width: 100%;
            height: auto;
            display: block;
        }

        .issues-list { list-style: none; }
        .issue-item {
            padding: 20px;
            margin-bottom: 15px;
            border-radius: 8px;
            border-left: 4px solid #e2e8f0;
        }
        .issue-item.high { border-left-color: #e53e3e; background: #fed7d7; }
        .issue-item.medium { border-left-color: #ed8936; background: #feebc8; }
        .issue-item.low { border-left-color: #38b2ac; background: #c6f6d5; }
        .issue-severity {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8em;
            font-weight: bold;
            text-transform: uppercase;
        }
        .severity-high { background: #e53e3e; color: white; }
        .severity-medium { background: #ed8936; color: white; }
        .severity-low { background: #38b2ac; color: white; }

        .code-section { margin-bottom: 25px; }
        .code-header {
            background: #2d3748;
            color: white;
            padding: 10px 15px;
            font-weight: bold;
            border-radius: 6px 6px 0 0;
        }
        pre[class*="language-"] {
            margin: 0;
            border-radius: 0 0 6px 6px;
        }

        .tabs { border-bottom: 1px solid #e2e8f0; margin-bottom: 20px; }
        .tab-button {
            background: none;
            border: none;
            padding: 12px 20px;
            cursor: pointer;
            border-bottom: 2px solid transparent;
            font-size: 1em;
        }
        .tab-button.active {
            border-bottom-color: #667eea;
            color: #667eea;
            font-weight: 600;
        }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>UX Analysis Report</h1>
            <div class="url">${result.url}</div>
            <div class="meta">
                <div class="meta-item">
                    <strong>Generated:</strong> ${new Date().toLocaleString()}
                </div>
                <div class="meta-item">
                    <strong>Analysis ID:</strong> ${result.id || 'N/A'}
                </div>
                <div class="meta-item">
                    <strong>Status:</strong> ${result.status || 'Completed'}
                </div>
            </div>
        </div>

        <div class="summary-cards">
            ${report.summary ? `
            <div class="card">
                <h3>Overall Grade</h3>
                <div class="grade ${(report.summary.overallGrade || '').toLowerCase()}">${report.summary.overallGrade || 'N/A'}</div>
            </div>
            <div class="card">
                <h3>UX Score</h3>
                <div class="score">${report.summary.uxScore || 0}</div>
                <div>out of 100</div>
            </div>
            <div class="card">
                <h3>Total Issues</h3>
                <div class="score">${report.summary.totalIssues || 0}</div>
                <div>issues found</div>
            </div>
            ` : ''}
            ${accessibility.score ? `
            <div class="card">
                <h3>Accessibility Score</h3>
                <div class="score">${accessibility.score}</div>
                <div>out of 100</div>
            </div>
            ` : ''}
        </div>

        ${screenshots.length > 0 ? `
        <div class="section">
            <div class="section-header">
                <h2>Screenshots</h2>
            </div>
            <div class="section-content">
                <div class="screenshots-grid">
                    ${screenshots.map(screenshot => `
                    <div class="screenshot-item">
                        <h4>${screenshot.viewport || screenshot.device || 'Screenshot'}</h4>
                        <img src="data:image/png;base64,${screenshot.base64 || ''}" alt="${screenshot.viewport} view" onerror="this.style.display='none'">
                    </div>
                    `).join('')}
                </div>
            </div>
        </div>
        ` : ''}

        ${report.issues && report.issues.length > 0 ? `
        <div class="section">
            <div class="section-header">
                <h2>Issues & Recommendations</h2>
            </div>
            <div class="section-content">
                <ul class="issues-list">
                    ${report.issues.map(issue => `
                    <li class="issue-item ${(issue.severity || 'medium').toLowerCase()}">
                        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px;">
                            <strong>${issue.description || issue.title || 'Issue'}</strong>
                            <span class="issue-severity severity-${(issue.severity || 'medium').toLowerCase()}">${issue.severity || 'Medium'}</span>
                        </div>
                        <p><strong>Category:</strong> ${issue.category || 'General'}</p>
                        <p><strong>Recommendation:</strong> ${issue.recommendation || issue.solution || 'No recommendation provided'}</p>
                        ${issue.location ? `<p><strong>Location:</strong> ${issue.location}</p>` : ''}
                    </li>
                    `).join('')}
                </ul>
            </div>
        </div>
        ` : ''}

        <div class="section">
            <div class="section-header">
                <h2>Implementation Code</h2>
            </div>
            <div class="section-content">
                ${implementationCode && (implementationCode.html?.length > 0 || implementationCode.css?.length > 0 || implementationCode.javascript?.length > 0) ? `
                <div class="tabs">
                    ${implementationCode.html?.length > 0 ? '<button class="tab-button active" onclick="showTab(\'html\')">HTML</button>' : ''}
                    ${implementationCode.css?.length > 0 ? '<button class="tab-button" onclick="showTab(\'css\')">CSS</button>' : ''}
                    ${implementationCode.javascript?.length > 0 ? '<button class="tab-button" onclick="showTab(\'js\')">JavaScript</button>' : ''}
                </div>

                ${implementationCode.html?.length > 0 ? `
                <div id="html-tab" class="tab-content active">
                    ${implementationCode.html.map(item => `
                    <div class="code-section">
                        <div class="code-header">${item.title || 'HTML Code'}</div>
                        <pre><code class="language-html">${escapeHtml(item.code || '')}</code></pre>
                        ${item.instructions ? `<p style="margin-top: 10px; color: #666;"><strong>Instructions:</strong> ${item.instructions}</p>` : ''}
                    </div>
                    `).join('')}
                </div>
                ` : ''}

                ${implementationCode.css?.length > 0 ? `
                <div id="css-tab" class="tab-content">
                    ${implementationCode.css.map(item => `
                    <div class="code-section">
                        <div class="code-header">${item.title || 'CSS Code'}</div>
                        <pre><code class="language-css">${escapeHtml(item.code || '')}</code></pre>
                        ${item.instructions ? `<p style="margin-top: 10px; color: #666;"><strong>Instructions:</strong> ${item.instructions}</p>` : ''}
                    </div>
                    `).join('')}
                </div>
                ` : ''}

                ${implementationCode.javascript?.length > 0 ? `
                <div id="js-tab" class="tab-content">
                    ${implementationCode.javascript.map(item => `
                    <div class="code-section">
                        <div class="code-header">${item.title || 'JavaScript Code'}</div>
                        <pre><code class="language-javascript">${escapeHtml(item.code || '')}</code></pre>
                        ${item.instructions ? `<p style="margin-top: 10px; color: #666;"><strong>Instructions:</strong> ${item.instructions}</p>` : ''}
                    </div>
                    `).join('')}
                </div>
                ` : ''}
                ` : `
                <div style="text-align: center; padding: 40px; color: #666; font-style: italic;">
                    <p>No implementation code recommendations generated.</p>
                    <p style="margin-top: 10px; font-size: 0.9em;">Try running the analysis with the <code>--code</code> flag to generate implementation suggestions.</p>
                </div>
                `}
            </div>
        </div>

        ${accessibility && accessibility.violations ? `
        <div class="section">
            <div class="section-header">
                <h2>Accessibility Analysis</h2>
            </div>
            <div class="section-content">
                <p><strong>Score:</strong> ${accessibility.score}/100</p>
                <p><strong>Total Violations:</strong> ${accessibility.totalViolations || 0}</p>
                ${accessibility.violations.length > 0 ? `
                <h4 style="margin-top: 20px;">Violations:</h4>
                <ul class="issues-list">
                    ${accessibility.violations.map(violation => `
                    <li class="issue-item ${violation.impact || 'medium'}">
                        <strong>${violation.description || violation.help || 'Accessibility Issue'}</strong>
                        <p><strong>Impact:</strong> ${violation.impact || 'Unknown'}</p>
                        ${violation.helpUrl ? `<p><a href="${violation.helpUrl}" target="_blank">Learn more</a></p>` : ''}
                    </li>
                    `).join('')}
                </ul>
                ` : ''}
            </div>
        </div>
        ` : ''}
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-core.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/autoloader/prism-autoloader.min.js"></script>
    <script>
        function showTab(tabName) {
            // Hide all tab contents
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });

            // Remove active class from all buttons
            document.querySelectorAll('.tab-button').forEach(button => {
                button.classList.remove('active');
            });

            // Show selected tab and activate button
            document.getElementById(tabName + '-tab').classList.add('active');
            event.target.classList.add('active');
        }

        // Initialize syntax highlighting
        Prism.highlightAll();
    </script>
</body>
</html>`;
}

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function isValidUrl(string) {
  try {
    const url = new URL(string);
    // Only allow HTTP and HTTPS protocols
    if (!['http:', 'https:'].includes(url.protocol)) {
      return false;
    }
    // Prevent localhost/private IPs in production
    const hostname = url.hostname.toLowerCase();
    const privateIpPatterns = [
      /^localhost$/,
      /^127\./,
      /^192\.168\./,
      /^10\./,
      /^172\.(1[6-9]|2[0-9]|3[0-1])\./,
      /^::1$/,
      /^fc00:/,
      /^fe80:/
    ];

    // Allow private IPs for development
    if (process.env.NODE_ENV !== 'production') {
      return true;
    }

    // Block private IPs in production
    return !privateIpPatterns.some(pattern => pattern.test(hostname));
  } catch (error) {
    return false;
  }
}

function generateMarkdownReport(result) {
  return `# UX Analysis Report

**Website:** ${result.url}
**Generated:** ${new Date().toLocaleString()}
${result.report?.summary ? `**Overall Grade:** ${result.report.summary.overallGrade}` : ''}

## Summary

${result.report?.summary ? `
- **UX Score:** ${result.report.summary.uxScore || 'N/A'}/100
- **Total Issues:** ${result.report.summary.totalIssues || 0}
` : ''}

${result.accessibility ? `
## Accessibility
- **Score:** ${result.accessibility.score}/100
- **Violations:** ${result.accessibility.totalViolations || 0}
` : ''}

## Detailed Results

\`\`\`json
${JSON.stringify(result, null, 2)}
\`\`\`
`;
}

async function configureSettings() {
  console.log(chalk.blue.bold('⚙️ UX Analyst CLI Configuration\n'));

  const answers = await inquirer.prompt([
    {
      type: 'input',
      name: 'apiKey',
      message: 'Enter your Gemini API key:',
      validate: (input) => input.length > 0 || 'API key is required'
    }
  ]);

  // Save to .env file
  const envPath = path.join(process.cwd(), '.env');
  const envContent = `GEMINI_API_KEY=${answers.apiKey}\n`;

  await fs.writeFile(envPath, envContent);
  console.log(chalk.green(`✅ Configuration saved to ${envPath}`));
}

if (require.main === module) {
  program.parse();
}

module.exports = { program };