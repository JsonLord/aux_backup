const express = require('express');
const router = express.Router();

// Analysis service will be injected via middleware

// POST /api/analyze - Start new analysis
router.post('/', async (req, res) => {
  try {
    const { url, options = {} } = req.body;

    // Validate required fields
    if (!url) {
      return res.status(400).json({
        error: 'URL is required'
      });
    }

    // Validate URL format
    try {
      new URL(url);
    } catch (error) {
      return res.status(400).json({
        error: 'Invalid URL format'
      });
    }

    // Validate options
    const validViewports = ['desktop', 'tablet', 'mobile'];
    const validAnalysisTypes = ['quick', 'comprehensive'];

    if (options.viewports && !Array.isArray(options.viewports)) {
      return res.status(400).json({
        error: 'Viewports must be an array'
      });
    }

    if (options.viewports) {
      const invalidViewports = options.viewports.filter(v => !validViewports.includes(v));
      if (invalidViewports.length > 0) {
        return res.status(400).json({
          error: `Invalid viewports: ${invalidViewports.join(', ')}`
        });
      }
    }

    if (options.analysisType && !validAnalysisTypes.includes(options.analysisType)) {
      return res.status(400).json({
        error: `Analysis type must be one of: ${validAnalysisTypes.join(', ')}`
      });
    }

    // Start analysis with progress callback
    const analysisService = req.services.get('analysisService');
    const result = await analysisService.analyzeWebsite(url, options);

    res.status(202).json(result);

  } catch (error) {
    console.error('Analysis start error:', error);

    if (error.message.includes('concurrent analyses')) {
      return res.status(429).json({
        error: 'Too many concurrent analyses. Please try again later.',
        retryAfter: 60
      });
    }

    res.status(500).json({
      error: 'Failed to start analysis',
      message: process.env.NODE_ENV === 'development' ? error.message : undefined
    });
  }
});

// GET /api/analyze/:id - Get analysis result
router.get('/:id', async (req, res) => {
  try {
    const { id } = req.params;

    if (!id) {
      return res.status(400).json({
        error: 'Analysis ID is required'
      });
    }

    const analysisService = req.services.get('analysisService');
    const result = await analysisService.getAnalysisResult(id);

    if (!result) {
      return res.status(404).json({
        error: 'Analysis not found'
      });
    }

    // Transform screenshots for API response
    const screenshots = {};
    result.screenshots.forEach(screenshot => {
      screenshots[screenshot.viewport] = {
        id: screenshot.id,
        width: screenshot.width,
        height: screenshot.height,
        fileSize: screenshot.file_size,
        url: `/screenshots/${screenshot.file_path.split('/').pop()}`
      };
    });

    const response = {
      id: result.id,
      url: result.url,
      status: result.status,
      progress: result.progress || 0,
      stage: result.stage || 'validating',
      createdAt: result.createdAt,
      completedAt: result.completedAt,
      errorMessage: result.errorMessage,
      screenshots,
      results: result.results
    };

    res.json(response);

  } catch (error) {
    console.error('Get analysis error:', error);

    if (error.message === 'Analysis not found') {
      return res.status(404).json({
        error: 'Analysis not found'
      });
    }

    res.status(500).json({
      error: 'Failed to retrieve analysis',
      message: process.env.NODE_ENV === 'development' ? error.message : undefined
    });
  }
});

// GET /api/analyze/:id/report - Get formatted HTML report
router.get('/:id/report', async (req, res) => {
  try {
    const { id } = req.params;
    const analysisService = req.services.get('analysisService');
    const result = await analysisService.getAnalysisResult(id);

    if (!result) {
      return res.status(404).json({
        error: 'Analysis not found'
      });
    }

    if (result.status !== 'completed') {
      return res.status(400).json({
        error: 'Analysis not completed yet'
      });
    }

    // Generate HTML report
    const htmlReport = generateHTMLReport(result);

    res.setHeader('Content-Type', 'text/html');
    res.send(htmlReport);

  } catch (error) {
    console.error('Report generation error:', error);
    res.status(500).json({
      error: 'Failed to generate report'
    });
  }
});

// GET /api/analyze/:id/screenshots/:viewport - Get screenshot
router.get('/:id/screenshots/:viewport', async (req, res) => {
  try {
    const { id, viewport } = req.params;
    const analysisService = req.services.get('analysisService');
    const result = await analysisService.getAnalysisResult(id);

    if (!result) {
      return res.status(404).json({
        error: 'Analysis not found'
      });
    }

    const screenshot = result.screenshots.find(s => s.viewport === viewport);
    if (!screenshot) {
      return res.status(404).json({
        error: 'Screenshot not found'
      });
    }

    // Serve the screenshot file
    res.sendFile(screenshot.file_path, { root: '.' });

  } catch (error) {
    console.error('Screenshot serve error:', error);
    res.status(500).json({
      error: 'Failed to serve screenshot'
    });
  }
});

// GET /api/analyze/:id/code - Get generated implementation code
router.get('/:id/code', async (req, res) => {
  try {
    const { id } = req.params;
    const analysisService = req.services.get('analysisService');
    const result = await analysisService.getAnalysisResult(id);

    if (!result) {
      return res.status(404).json({
        error: 'Analysis not found'
      });
    }

    if (result.status !== 'completed') {
      return res.status(400).json({
        error: 'Analysis not completed yet'
      });
    }

    // Find implementation code in results
    const implementationCode = result.results.implementation_code;

    if (!implementationCode) {
      return res.status(404).json({
        error: 'No implementation code available for this analysis'
      });
    }

    res.json({
      analysisId: id,
      url: result.url,
      generatedAt: result.completedAt,
      code: implementationCode
    });

  } catch (error) {
    console.error('Get implementation code error:', error);
    res.status(500).json({
      error: 'Failed to retrieve implementation code'
    });
  }
});

// GET /api/analyze - Get active analyses (admin endpoint)
router.get('/', async (req, res) => {
  try {
    const analysisService = req.services.get('analysisService');
    const activeAnalyses = analysisService.getActiveAnalyses();

    res.json({
      active: activeAnalyses.length,
      analyses: activeAnalyses
    });

  } catch (error) {
    console.error('Get active analyses error:', error);
    res.status(500).json({
      error: 'Failed to get active analyses'
    });
  }
});

function generateHTMLReport(analysisResult) {
  const { url, results, screenshots } = analysisResult;
  const accessibility = results.accessibility;
  const ux = results.ux_critique;
  const report = results.final_report;

  // Format timestamp for user's local timezone
  const formatLocalTime = (timestamp) => {
    return new Date(timestamp).toLocaleString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZoneName: 'short'
    });
  };

  return `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UX Analysis Report - ${url}</title>
    <style>
        body { font-family: Arial, sans-serif; line-height: 1.6; margin: 0; padding: 20px; }
        .header { background: #f4f4f4; padding: 20px; margin-bottom: 20px; }
        .section { margin-bottom: 30px; }
        .score { font-size: 24px; font-weight: bold; color: #2c5aa0; }
        .issue { background: #f9f9f9; padding: 10px; margin: 10px 0; border-left: 4px solid #ccc; }
        .high { border-left-color: #d32f2f; }
        .medium { border-left-color: #f57c00; }
        .low { border-left-color: #388e3c; }
        .recommendation { background: #e3f2fd; padding: 15px; margin: 10px 0; border-radius: 4px; }
        .screenshots { display: flex; gap: 20px; flex-wrap: wrap; }
        .screenshot { flex: 1; min-width: 300px; }
        .screenshot img { width: 100%; height: auto; border: 1px solid #ddd; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background-color: #f5f5f5; }
    </style>
</head>
<body>
    <div class="header">
        <h1>UX Analysis Report</h1>
        <p><strong>Website:</strong> ${url}</p>
        <p><strong>Generated:</strong> ${formatLocalTime(analysisResult.createdAt)}</p>
        ${report ? `<p><strong>Overall Grade:</strong> ${report.summary.overallGrade}</p>` : ''}
    </div>

    ${report ? `
    <div class="section">
        <h2>Executive Summary</h2>
        <div class="score">Overall Score: ${report.summary.uxScore || 'N/A'}/100</div>
        <p>Total Issues Found: ${report.summary.totalIssues}</p>
        <p>Priority Level: ${report.summary.priorityLevel}</p>
    </div>
    ` : ''}

    ${accessibility ? `
    <div class="section">
        <h2>Accessibility Analysis</h2>
        <div class="score">Accessibility Score: ${accessibility.score}/100</div>
        <p>Total Violations: ${accessibility.totalViolations}</p>

        <h3>Top Issues</h3>
        ${accessibility.topIssues ? accessibility.topIssues.map(issue => `
        <div class="issue ${issue.impact}">
            <strong>${issue.description}</strong><br>
            Impact: ${issue.impact} | Instances: ${issue.count}
        </div>
        `).join('') : '<p>No accessibility issues found.</p>'}
    </div>
    ` : ''}

    ${ux && ux.structured_critique ? `
    <div class="section">
        <h2>UX Analysis</h2>
        <div class="score">UX Score: ${ux.structured_critique.overall_assessment.score}/100</div>

        <h3>Key Strengths</h3>
        <ul>
            ${ux.structured_critique.overall_assessment.strengths.map(strength => `<li>${strength}</li>`).join('')}
        </ul>

        <h3>Key Weaknesses</h3>
        <ul>
            ${ux.structured_critique.overall_assessment.weaknesses.map(weakness => `<li>${weakness}</li>`).join('')}
        </ul>

        <h3>Recommendations</h3>
        ${ux.structured_critique.recommendations.slice(0, 5).map(rec => `
        <div class="recommendation">
            <h4>${rec.title} (${rec.priority} Priority)</h4>
            <p>${rec.description}</p>
            <p><strong>Expected Impact:</strong> ${rec.impact}</p>
            <p><strong>Implementation Effort:</strong> ${rec.effort}</p>
        </div>
        `).join('')}
    </div>
    ` : ''}

    ${ux && ux.quick_critique ? `
    <div class="section">
        <h2>Quick UX Assessment</h2>
        <div style="white-space: pre-line;">${ux.quick_critique}</div>
    </div>
    ` : ''}

    <div class="section">
        <h2>Screenshots</h2>
        <div class="screenshots">
            ${screenshots.map(screenshot => `
            <div class="screenshot">
                <h4>${screenshot.viewport.charAt(0).toUpperCase() + screenshot.viewport.slice(1)}</h4>
                <img src="/screenshots/${screenshot.file_path.split('/').pop()}" alt="${screenshot.viewport} screenshot">
                <p>${screenshot.width}x${screenshot.height}</p>
            </div>
            `).join('')}
        </div>
    </div>

    <div class="section">
        <p><em>Generated by UX Analyst AI</em></p>
    </div>
</body>
</html>
  `;
}

module.exports = router;