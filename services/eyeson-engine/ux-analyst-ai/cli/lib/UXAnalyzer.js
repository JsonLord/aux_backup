const AnalysisService = require('../../backend/services/analysisService');
const ScreenshotService = require('../../backend/services/screenshotService');
const AICritiqueService = require('../../backend/services/aiCritiqueService');
const VisualDesignAnalyzer = require('../../backend/services/visualDesignAnalyzer');
const CodeGenerationService = require('../../backend/services/codeGenerationService');
const { initializeDatabase } = require('../../backend/database/init');

class UXAnalyzer {
  constructor(config) {
    this.config = config;
    this.services = null;
  }

  async initialize() {
    if (this.services) return;

    // Initialize database
    await initializeDatabase();

    // Initialize services
    const screenshotService = new ScreenshotService(this.config);
    const aiCritiqueService = new AICritiqueService(this.config);
    const visualDesignAnalyzer = new VisualDesignAnalyzer();
    const codeGenerationService = new CodeGenerationService({
      geminiApiKey: this.config.ai.geminiApiKey,
      logger: console
    });

    const analysisService = new AnalysisService({
      screenshotService,
      aiCritiqueService,
      visualDesignAnalyzer,
      codeGenerationService,
      config: this.config
    });

    this.services = {
      analysisService,
      screenshotService,
      aiCritiqueService,
      visualDesignAnalyzer,
      codeGenerationService
    };
  }

  async analyze(url, options = {}, progressCallback = null) {
    await this.initialize();

    const defaultOptions = {
      viewports: ['desktop', 'tablet', 'mobile'],
      analysisType: 'comprehensive',
      includeAccessibility: false,
      includeCodeGeneration: true
    };

    const finalOptions = { ...defaultOptions, ...options };

    // Start analysis
    const analysisResult = await this.services.analysisService.analyzeWebsite(url, finalOptions);
    const analysisId = analysisResult.analysisId;

    // Poll for progress if callback provided
    if (progressCallback) {
      await this.monitorProgress(analysisId, progressCallback);
    }

    // Wait for completion and get results
    const result = await this.waitForCompletion(analysisId);

    return this.formatResult(result);
  }

  async monitorProgress(analysisId, callback) {
    const checkProgress = async () => {
      try {
        const result = await this.services.analysisService.getAnalysisResult(analysisId);

        if (result) {
          callback({
            percent: result.progress || 0,
            stage: result.stage || 'Processing',
            status: result.status
          });

          if (result.status === 'completed' || result.status === 'failed') {
            return;
          }
        }

        // Continue monitoring
        setTimeout(checkProgress, 2000);
      } catch (error) {
        // Continue monitoring on error
        setTimeout(checkProgress, 2000);
      }
    };

    await checkProgress();
  }

  async waitForCompletion(analysisId, maxWaitTime = 300000) { // 5 minutes max
    const startTime = Date.now();

    return new Promise((resolve, reject) => {
      const checkCompletion = async () => {
        try {
          const result = await this.services.analysisService.getAnalysisResult(analysisId);

          if (result && result.status === 'completed') {
            resolve(result);
            return;
          }

          if (result && result.status === 'failed') {
            reject(new Error(result.errorMessage || 'Analysis failed'));
            return;
          }

          // Check timeout
          if (Date.now() - startTime > maxWaitTime) {
            reject(new Error('Analysis timeout'));
            return;
          }

          // Continue waiting
          setTimeout(checkCompletion, 2000);
        } catch (error) {
          reject(error);
        }
      };

      checkCompletion();
    });
  }

  formatResult(rawResult) {
    const formatted = {
      id: rawResult.id,
      url: rawResult.url,
      status: rawResult.status,
      createdAt: rawResult.createdAt,
      completedAt: rawResult.completedAt,
      screenshots: rawResult.screenshots || [],
      results: rawResult.results || {}
    };

    // Extract key results for easier CLI access
    if (rawResult.results) {
      formatted.accessibility = rawResult.results.accessibility;
      formatted.uxCritique = rawResult.results.ux_critique;
      formatted.report = rawResult.results.final_report;
      formatted.implementationCode = rawResult.results.implementation_code;
    }

    return formatted;
  }

  async cleanup() {
    if (this.services?.screenshotService) {
      // Close any open browsers
      await this.services.screenshotService.cleanup?.();
    }
  }
}

module.exports = UXAnalyzer;