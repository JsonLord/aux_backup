const { GoogleGenerativeAI } = require('@google/generative-ai');
const fs = require('fs').promises;
const IAICritiqueService = require('../interfaces/IAICritiqueService');
const CircuitBreaker = require('../core/CircuitBreaker');

class AICritiqueService extends IAICritiqueService {
  constructor(config = {}, logger = console) {
    super();

    this.config = config;
    this.logger = logger;
    this.isShuttingDown = false;

    // Initialize stats
    this.stats = {
      critiqueAttempts: 0,
      critiqueSuccesses: 0,
      critiqueFailures: 0,
      totalTokensUsed: 0,
      averageResponseTime: 0
    };

    // Get API key from config or environment
    const apiKey = config.ai?.gemini?.apiKey || process.env.GEMINI_API_KEY;
    if (!apiKey) {
      throw new Error('Gemini API key is required (config.ai.gemini.apiKey or GEMINI_API_KEY env var)');
    }

    this.genAI = new GoogleGenerativeAI(apiKey);
    this.model = this.genAI.getGenerativeModel({
      model: config.ai?.gemini?.model || process.env.GEMINI_MODEL || 'gemini-1.5-flash'
    });

    // Initialize circuit breaker for AI operations
    this.circuitBreaker = CircuitBreaker.forAPI('AICritique', {
      failureThreshold: config.ai?.gemini?.failureThreshold || 5,
      recoveryTimeout: config.ai?.gemini?.recoveryTimeout || 60000,
      expectedErrors: ['rate limit', '429', '503', 'timeout', 'overloaded', 'quota']
    });

    // Configuration for timeouts and retries
    this.timeoutMs = config.ai?.gemini?.timeoutMs || 45000;
    this.maxRetries = config.ai?.gemini?.maxRetries || 3;
    this.baseDelay = config.ai?.gemini?.baseDelay || 2000;
  }

  async callGeminiWithRetry(apiCall, maxRetries = this.maxRetries, baseDelay = this.baseDelay) {
    const startTime = Date.now();
    this.stats.critiqueAttempts++;

    return this.circuitBreaker.execute(async () => {
      for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
          this.logger.log(`Gemini API attempt ${attempt}/${maxRetries}`);

          // Add timeout wrapper to prevent infinite hanging
          const result = await Promise.race([
            apiCall(),
            new Promise((_, reject) =>
              setTimeout(() => reject(new Error('Gemini API call timed out')), this.timeoutMs)
            )
          ]);

          this.logger.log(`Gemini API attempt ${attempt} succeeded`);

          // Update stats
          const responseTime = Date.now() - startTime;
          this.stats.critiqueSuccesses++;
          this.updateResponseTimeStats(responseTime);

          return result;
        } catch (error) {
          this.logger.error(`Gemini API attempt ${attempt} failed:`, error.message);

          // Check if it's a retryable error
          const isRetryable = error.status === 503 ||
                             error.message.includes('timed out') ||
                             error.message.includes('overloaded') ||
                             error.message.includes('rate limit') ||
                             error.message.includes('quota') ||
                             error.code === 'ECONNRESET' ||
                             error.code === 'ETIMEDOUT';

          if (isRetryable && attempt < maxRetries) {
            const delay = baseDelay * Math.pow(2, attempt - 1); // Exponential backoff
            this.logger.log(`Waiting ${delay}ms before retry (reason: ${error.message})...`);
            await new Promise(resolve => setTimeout(resolve, delay));
            continue;
          }

          // Update failure stats
          this.stats.critiqueFailures++;
          throw error;
        }
      }
    });
  }

  async generateUXCritique(analysisData) {
    if (this.isShuttingDown) {
      throw new Error('AI Critique service is shutting down');
    }

    const {
      screenshots,
      accessibilityResults,
      visualAnalysis,
      url
    } = analysisData;

    try {
      const prompt = this.buildCritiquePrompt(analysisData);

      // Prepare image data for Gemini (if screenshots available)
      const imageParts = await this.prepareImageParts(screenshots);

      // Combine text prompt with images
      const parts = [prompt, ...imageParts];

      const response = await this.callGeminiWithRetry(async () => {
        const result = await this.model.generateContent(parts);
        return await result.response;
      });
      const critiqueText = response.text();

      return this.parseCritiqueResponse(critiqueText);

    } catch (error) {
      this.logger.error('AI critique generation error:', error);
      throw new Error(`Failed to generate UX critique: ${error.message}`);
    }
  }

  async prepareImageParts(screenshots) {
    const imageParts = [];

    try {
      // Add up to 3 screenshots (desktop, tablet, mobile) to keep under Gemini limits
      const priorityViewports = ['desktop', 'tablet', 'mobile'];

      for (const viewport of priorityViewports) {
        if (screenshots[viewport]) {
          const screenshot = screenshots[viewport];
          try {
            const imageData = await fs.readFile(screenshot.filepath);
            imageParts.push({
              inlineData: {
                data: imageData.toString('base64'),
                mimeType: 'image/png'
              }
            });

            // Add context about which viewport this is
            imageParts.push(`[${viewport.toUpperCase()} SCREENSHOT - ${screenshot.width}x${screenshot.height}]`);
          } catch (fileError) {
            this.logger.warn(`Could not read screenshot for ${viewport}:`, fileError.message);
          }
        }
      }
    } catch (error) {
      this.logger.warn('Error preparing image parts:', error.message);
    }

    return imageParts;
  }

  buildCritiquePrompt(analysisData) {
    const { screenshots, accessibilityResults, visualAnalysis, url } = analysisData;

    return `You are a senior UX designer and accessibility expert. Analyze this website and provide detailed UX feedback based on the screenshots and data provided.

**Website URL:** ${url}

**Screenshots Analysis Context:**
I will provide screenshots of this website across different viewports. Please analyze them for:
- Visual hierarchy and design principles
- User interface clarity and usability
- Mobile responsiveness and layout adaptation
- Visual accessibility (contrast, text size, spacing)
- Overall user experience quality

**Screenshots Available:**
${Object.keys(screenshots).map(viewport => `- ${viewport}: ${screenshots[viewport].width}x${screenshots[viewport].height}`).join('\n')}

**Accessibility Analysis Summary:**
- Total violations: ${accessibilityResults?.summary?.totalViolations || 0}
- Critical issues: ${accessibilityResults?.summary?.violationsByImpact?.critical || 0}
- Serious issues: ${accessibilityResults?.summary?.violationsByImpact?.serious || 0}
- Accessibility score: ${accessibilityResults?.summary?.score || 'N/A'}/100

**Key Accessibility Violations:**
${accessibilityResults?.violations?.slice(0, 5).map(v => `- ${v.description} (${v.impact} impact)`).join('\n') || 'None found'}

**Visual Design Analysis Summary:**
${visualAnalysis ? `
- Overall Visual Score: ${visualAnalysis.combined?.overallScore || 'N/A'}/100
- Total Visual Issues: ${visualAnalysis.combined?.totalIssues || 0}
- Critical Visual Issues: ${visualAnalysis.combined?.criticalIssues || 0}
- Responsive Consistency: ${Math.round((visualAnalysis.combined?.responsiveConsistency || 0) * 100)}%

**Top Visual Design Issues:**
${visualAnalysis.combined?.topIssues?.slice(0, 3).map(issue => `- ${issue.description} (${issue.severity} priority) - affects ${issue.affectedViewports?.join(', ')}`).join('\n') || 'None found'}
` : 'Visual analysis not available'}

**IMPORTANT: AI Design Anti-Pattern Detection**
Please specifically check for common signs that this website may have been designed by AI tools and flag any of these issues:

**Visual & Layout Red Flags:**
- Generic, template-like appearance that looks similar to other modern websites
- Overly perfect, sterile design lacking human character or brand personality
- Mechanical spacing and element placement (everything perfectly aligned/centered)
- Inconsistent visual hierarchy or unclear content flow
- Over-reliance on stock photography or generic imagery
- Excessive use of gradients, drop shadows, or trendy effects without purpose
- Perfect symmetry everywhere (unnatural balance)
- Homogeneous, "safe" color palettes lacking personality

**Content & Copy Issues:**
- Buzzword overuse ("innovative", "revolutionary", "cutting-edge", "empower", "solutions")
- Vague, meaningless copy ("Empowering solutions for your unique needs")
- Robotic, corporate tone lacking human personality
- Poor content structure (walls of text or overly fragmented)
- Generic CTAs ("Learn More", "Get Started") without context
- Missing authentic details (pricing, contact info, specifics)
- Excessive emoji usage in headings, buttons, or throughout content 🚀✨💡
- Emojis that feel forced or don't match the brand tone

**User Experience Problems:**
- Feature overload trying to do everything at once
- Confusing navigation with too many options or unclear labels
- No clear user journey or call-to-action hierarchy
- Missing human elements (testimonials, team photos, personal stories)
- Over-optimization that feels calculated rather than intuitive

If you detect potential AI design patterns, include an "ai_design_assessment" section in your response:

"ai_design_assessment": {
  "likely_ai_generated": true/false,
  "confidence": 1-100,
  "detected_patterns": ["list of specific AI patterns found"],
  "recommendations": ["specific suggestions to make design more human and authentic"],
  "human_elements_missing": ["what human touches could improve the design"]
}

Please analyze the provided screenshots and provide a comprehensive UX critique in the following JSON format:

{
  "overall_assessment": {
    "score": 1-100,
    "summary": "Brief overall assessment",
    "strengths": ["strength1", "strength2"],
    "weaknesses": ["weakness1", "weakness2"]
  },
  "visual_design": {
    "score": 1-100,
    "feedback": "Detailed feedback on visual design",
    "issues": [
      {
        "category": "Typography/Layout/Color/etc",
        "severity": "High/Medium/Low",
        "description": "Issue description",
        "recommendation": "Specific improvement suggestion"
      }
    ]
  },
  "usability": {
    "score": 1-100,
    "feedback": "Detailed usability feedback",
    "issues": [
      {
        "category": "Navigation/Forms/Content/etc",
        "severity": "High/Medium/Low",
        "description": "Issue description",
        "recommendation": "Specific improvement suggestion"
      }
    ]
  },
  "accessibility": {
    "score": 1-100,
    "feedback": "Accessibility assessment beyond automated testing",
    "issues": [
      {
        "category": "Visual/Motor/Cognitive/etc",
        "severity": "High/Medium/Low",
        "description": "Issue description",
        "recommendation": "Specific improvement suggestion"
      }
    ]
  },
  "mobile_responsiveness": {
    "score": 1-100,
    "feedback": "Mobile and responsive design assessment",
    "issues": [
      {
        "category": "Layout/Touch/Performance/etc",
        "severity": "High/Medium/Low",
        "description": "Issue description",
        "recommendation": "Specific improvement suggestion"
      }
    ]
  },
  "performance": {
    "score": 1-100,
    "feedback": "Performance and loading assessment based on visual cues",
    "issues": [
      {
        "category": "Speed/Size/Optimization/etc",
        "severity": "High/Medium/Low",
        "description": "Issue description",
        "recommendation": "Specific improvement suggestion"
      }
    ]
  },
  "recommendations": [
    {
      "priority": "High/Medium/Low",
      "category": "Category name",
      "title": "Recommendation title",
      "description": "Detailed recommendation",
      "impact": "Expected impact of implementing this change",
      "effort": "Low/Medium/High implementation effort"
    }
  ],
  "ai_design_assessment": {
    "likely_ai_generated": true/false,
    "confidence": 1-100,
    "detected_patterns": ["list of specific AI patterns found"],
    "recommendations": ["specific suggestions to make design more human and authentic"],
    "human_elements_missing": ["what human touches could improve the design"]
  }
}

NOTE: The "ai_design_assessment" section is OPTIONAL - only include it if you detect potential AI design patterns. If the design appears authentically human-made, omit this section entirely.

Focus on actionable, specific feedback based on what you can see in the screenshots. Consider modern UX best practices, WCAG guidelines, and current design trends. Be constructive and provide clear next steps.`;
  }

  parseCritiqueResponse(critiqueText) {
    try {
      // Extract JSON from the response (Gemini sometimes wraps it in markdown)
      const jsonMatch = critiqueText.match(/\{[\s\S]*\}/);
      if (!jsonMatch) {
        throw new Error('No JSON found in response');
      }

      const parsed = JSON.parse(jsonMatch[0]);

      // Validate the structure
      this.validateCritiqueStructure(parsed);

      return {
        raw_response: critiqueText,
        structured_critique: parsed,
        generated_at: new Date().toISOString(),
        model_used: process.env.GEMINI_MODEL || 'gemini-1.5-flash'
      };

    } catch (error) {
      this.logger.error('Error parsing AI critique:', error);

      // Fallback: return unstructured response
      return {
        raw_response: critiqueText,
        structured_critique: null,
        error: error.message,
        generated_at: new Date().toISOString(),
        model_used: process.env.GEMINI_MODEL || 'gemini-1.5-flash'
      };
    }
  }

  validateCritiqueStructure(critique) {
    const requiredSections = [
      'overall_assessment',
      'visual_design',
      'usability',
      'accessibility',
      'mobile_responsiveness',
      'performance',
      'recommendations'
    ];

    for (const section of requiredSections) {
      if (!critique[section]) {
        throw new Error(`Missing required section: ${section}`);
      }
    }

    // Validate scores are numbers between 1-100
    const scoreSections = requiredSections.slice(0, -1); // Exclude recommendations
    for (const section of scoreSections) {
      const score = critique[section].score;
      if (typeof score !== 'number' || score < 1 || score > 100) {
        throw new Error(`Invalid score in section ${section}: ${score}`);
      }
    }
  }

  async generateReport(critiques, screenshots, accessibilityResults) {
    if (this.isShuttingDown) {
      throw new Error('AI Critique service is shutting down');
    }

    try {
      const reportPrompt = this.buildReportPrompt(critiques, screenshots, accessibilityResults);

      const response = await this.callGeminiWithRetry(async () => {
        const result = await this.model.generateContent(reportPrompt);
        return await result.response;
      });
      const reportText = response.text();

      return {
        executive_summary: this.extractExecutiveSummary(reportText),
        detailed_report: reportText,
        generated_at: new Date().toISOString()
      };

    } catch (error) {
      this.logger.error('Report generation error:', error);
      throw new Error(`Failed to generate report: ${error.message}`);
    }
  }

  buildReportPrompt(critiques, screenshots, accessibilityResults) {
    return `Create a comprehensive UX analysis report based on the following data:

**UX Critique Results:**
${JSON.stringify(critiques.structured_critique, null, 2)}

**Accessibility Summary:**
- Overall Score: ${accessibilityResults?.summary?.score || 'N/A'}/100
- Total Violations: ${accessibilityResults?.summary?.totalViolations || 0}
- Critical Issues: ${accessibilityResults?.summary?.violationsByImpact?.critical || 0}

**Screenshots Analyzed:**
${Object.keys(screenshots).join(', ')}

Generate a professional UX analysis report that includes:

1. **Executive Summary** (2-3 paragraphs)
   - Overall assessment and key findings
   - Primary recommendations
   - Business impact

2. **Detailed Findings** (organized by category)
   - Visual Design Analysis
   - Usability Assessment
   - Accessibility Review
   - Mobile Experience
   - Performance Considerations

3. **Prioritized Recommendations**
   - High priority fixes
   - Medium priority improvements
   - Long-term enhancements

4. **Next Steps**
   - Immediate actions
   - Implementation timeline suggestions

Format as HTML for web display. Use professional language suitable for stakeholders.`;
  }

  extractExecutiveSummary(reportText) {
    // Extract the executive summary section
    const summaryMatch = reportText.match(/executive summary[^<]*<\/?\w*>(.*?)(?=<h[1-6]|$)/is);
    return summaryMatch ? summaryMatch[1].trim() : reportText.substring(0, 500) + '...';
  }

  async generateQuickCritique(url, basicData) {
    if (this.isShuttingDown) {
      throw new Error('AI Critique service is shutting down');
    }

    // Simplified critique for quick analysis
    try {
      const prompt = `Provide a quick UX assessment for ${url}.

Basic data available:
- Accessibility issues found: ${basicData.accessibilityIssues || 0}
- Screenshots captured: ${basicData.viewports?.join(', ') || 'desktop'}

Give a brief assessment (max 300 words) covering:
1. Overall first impression
2. Top 3 improvement areas
3. Accessibility concerns
4. One priority recommendation

Be concise and actionable.`;

      const result = await this.callGeminiWithRetry(async () => {
        const result = await this.model.generateContent(prompt);
        return await result.response;
      });

      return {
        quick_critique: result.text(),
        generated_at: new Date().toISOString(),
        type: 'quick'
      };

    } catch (error) {
      this.logger.error('Quick critique error:', error);

      // Fallback to basic analysis when AI is unavailable
      this.logger.warn('Gemini API unavailable, providing fallback analysis');
      return this.generateFallbackCritique(url, basicData);
    }
  }

  generateFallbackCritique(url, basicData) {
    const domain = new URL(url).hostname;
    const accessibilityIssues = basicData.accessibilityIssues || 0;
    const viewports = basicData.viewports?.join(', ') || 'desktop';

    let fallbackText = `**UX Analysis for ${domain}**

📊 **Analysis Summary:**
- Screenshots captured: ${viewports}
- Accessibility scan: ${accessibilityIssues} issues detected
- Analysis type: Automated (AI service temporarily unavailable)

🔍 **Key Observations:**
• Website successfully loaded and captured across ${basicData.viewports?.length || 1} viewport(s)
• ${accessibilityIssues === 0 ? 'No major accessibility issues detected' : `${accessibilityIssues} accessibility issue(s) require attention`}
• Screenshots available for visual review and manual analysis

📋 **Recommended Next Steps:**
1. **Manual Review**: Examine captured screenshots for visual design quality
2. **Accessibility**: ${accessibilityIssues > 0 ? 'Address accessibility issues found' : 'Conduct deeper accessibility testing'}
3. **User Testing**: Perform real user testing for usability insights
4. **Performance**: Check loading speeds and mobile responsiveness

⚠️ **Note**: This is a basic automated analysis. For detailed AI-powered insights, please retry when the AI service is available.

*Analysis generated on ${new Date().toLocaleString()}*`;

    return {
      quick_critique: fallbackText,
      generated_at: new Date().toISOString(),
      type: 'fallback'
    };
  }

  async analyzeScreenshotDirectly(screenshotPath, context = '') {
    if (this.isShuttingDown) {
      throw new Error('AI Critique service is shutting down');
    }

    // Direct screenshot analysis utility (bonus feature)
    try {
      const imageData = await fs.readFile(screenshotPath);

      const parts = [
        `Analyze this website screenshot for UX and accessibility issues. ${context}

        Provide specific feedback on:
        - Visual hierarchy and clarity
        - Accessibility concerns you can see
        - User experience issues
        - Mobile-friendliness (if applicable)

        Be specific and actionable in your feedback.`,
        {
          inlineData: {
            data: imageData.toString('base64'),
            mimeType: 'image/png'
          }
        }
      ];

      const response = await this.callGeminiWithRetry(async () => {
        const result = await this.model.generateContent(parts);
        return await result.response;
      });

      return {
        analysis: response.text(),
        generated_at: new Date().toISOString()
      };

    } catch (error) {
      this.logger.error('Direct screenshot analysis error:', error);
      throw new Error(`Failed to analyze screenshot: ${error.message}`);
    }
  }
  /**
   * Update response time statistics
   */
  updateResponseTimeStats(responseTime) {
    const totalRequests = this.stats.critiqueSuccesses;
    if (totalRequests === 1) {
      this.stats.averageResponseTime = responseTime;
    } else {
      this.stats.averageResponseTime =
        (this.stats.averageResponseTime * (totalRequests - 1) + responseTime) / totalRequests;
    }
  }

  /**
   * Validate AI service configuration and connectivity
   */
  async validateService() {
    try {
      const testPrompt = 'Respond with "OK" to confirm service is working.';

      const response = await this.callGeminiWithRetry(async () => {
        const result = await this.model.generateContent(testPrompt);
        return await result.response;
      });

      const responseText = response.text().trim();

      return {
        status: 'valid',
        responseReceived: true,
        responseText,
        model: this.config.ai?.gemini?.model || 'gemini-1.5-flash',
        circuitBreakerState: this.circuitBreaker.getStatus().state
      };

    } catch (error) {
      return {
        status: 'invalid',
        error: error.message,
        circuitBreakerState: this.circuitBreaker.getStatus().state
      };
    }
  }

  /**
   * Test AI service with a simple request
   */
  async testService() {
    try {
      const startTime = Date.now();
      const testPrompt = 'Give a brief test response about UX design principles.';

      const response = await this.callGeminiWithRetry(async () => {
        const result = await this.model.generateContent(testPrompt);
        return await result.response;
      });

      const responseTime = Date.now() - startTime;

      return {
        status: 'success',
        responseTime,
        responseText: response.text(),
        testPassed: true
      };

    } catch (error) {
      return {
        status: 'failed',
        error: error.message,
        testPassed: false
      };
    }
  }

  /**
   * Get current AI service usage statistics
   */
  async getUsageStats() {
    const circuitBreakerStatus = this.circuitBreaker.getStatus();

    return {
      ...this.stats,
      successRate: this.stats.critiqueAttempts > 0 ?
        (this.stats.critiqueSuccesses / this.stats.critiqueAttempts * 100).toFixed(2) + '%' : '0%',
      circuitBreaker: {
        state: circuitBreakerStatus.state,
        failureCount: circuitBreakerStatus.failureCount,
        successRate: circuitBreakerStatus.monitoring.successRate
      },
      isShuttingDown: this.isShuttingDown
    };
  }

  /**
   * Get service health status
   */
  async getHealthStatus() {
    try {
      const circuitBreakerStatus = this.circuitBreaker.getStatus();
      const usageStats = await this.getUsageStats();

      // Quick connectivity test (with shorter timeout)
      const originalTimeout = this.timeoutMs;
      this.timeoutMs = 10000; // 10 second timeout for health check

      let connectivityTest;
      try {
        connectivityTest = await this.validateService();
      } catch (error) {
        connectivityTest = {
          status: 'failed',
          error: error.message
        };
      } finally {
        this.timeoutMs = originalTimeout; // Restore original timeout
      }

      const isHealthy = (
        circuitBreakerStatus.state !== 'OPEN' &&
        !this.isShuttingDown &&
        connectivityTest.status === 'valid'
      );

      return {
        status: isHealthy ? 'healthy' : 'unhealthy',
        connectivity: connectivityTest,
        circuitBreaker: {
          state: circuitBreakerStatus.state,
          failureCount: circuitBreakerStatus.failureCount,
          successRate: circuitBreakerStatus.monitoring.successRate
        },
        usage: usageStats,
        isShuttingDown: this.isShuttingDown,
        model: this.config.ai?.gemini?.model || 'gemini-1.5-flash'
      };

    } catch (error) {
      return {
        status: 'unhealthy',
        error: error.message,
        isShuttingDown: this.isShuttingDown
      };
    }
  }

  /**
   * Shutdown the service gracefully
   */
  async shutdown() {
    if (this.isShuttingDown) {
      return;
    }

    this.logger.log('Shutting down AICritiqueService...');
    this.isShuttingDown = true;

    try {
      // Stop circuit breaker monitoring
      this.circuitBreaker.stopMonitoring();

      this.logger.log('AICritiqueService shutdown complete');

    } catch (error) {
      this.logger.error('Error during AICritiqueService shutdown:', error.message);
      throw error;
    }
  }
}

module.exports = AICritiqueService;