/**
 * Interface for AI Critique Service
 * Defines the contract for AI-powered UX analysis operations
 */
class IAICritiqueService {
  constructor() {
    if (new.target === IAICritiqueService) {
      throw new Error('Cannot instantiate interface directly');
    }
  }

  /**
   * Generate comprehensive UX critique
   * @param {Object} analysisData - Analysis data object
   * @param {Object} analysisData.screenshots - Screenshot data by viewport
   * @param {Object} analysisData.accessibilityResults - Accessibility scan results
   * @param {Object} analysisData.visualAnalysis - Visual design analysis results
   * @param {string} analysisData.url - Website URL
   * @returns {Promise<Object>} UX critique result object
   */
  async generateUXCritique(analysisData) {
    throw new Error('generateUXCritique method must be implemented');
  }

  /**
   * Generate quick UX critique with limited data
   * @param {string} url - Website URL
   * @param {Object} basicData - Basic analysis data
   * @param {number} basicData.accessibilityIssues - Number of accessibility issues
   * @param {Array<string>} basicData.viewports - List of analyzed viewports
   * @returns {Promise<Object>} Quick critique result object
   */
  async generateQuickCritique(url, basicData) {
    throw new Error('generateQuickCritique method must be implemented');
  }

  /**
   * Generate comprehensive analysis report
   * @param {Object} critiques - Critique results
   * @param {Object} screenshots - Screenshot data
   * @param {Object} accessibilityResults - Accessibility results
   * @returns {Promise<Object>} Generated report object
   */
  async generateReport(critiques, screenshots, accessibilityResults) {
    throw new Error('generateReport method must be implemented');
  }

  /**
   * Analyze a single screenshot directly
   * @param {string} screenshotPath - Path to screenshot file
   * @param {string} context - Additional context for analysis
   * @returns {Promise<Object>} Screenshot analysis result
   */
  async analyzeScreenshotDirectly(screenshotPath, context = '') {
    throw new Error('analyzeScreenshotDirectly method must be implemented');
  }

  /**
   * Validate AI service configuration and connectivity
   * @returns {Promise<Object>} Validation result object
   */
  async validateService() {
    throw new Error('validateService method must be implemented');
  }

  /**
   * Test AI service with a simple request
   * @returns {Promise<Object>} Test result object
   */
  async testService() {
    throw new Error('testService method must be implemented');
  }

  /**
   * Get current AI service usage statistics
   * @returns {Promise<Object>} Usage statistics object
   */
  async getUsageStats() {
    throw new Error('getUsageStats method must be implemented');
  }

  /**
   * Get service health status
   * @returns {Promise<Object>} Health status object
   */
  async getHealthStatus() {
    throw new Error('getHealthStatus method must be implemented');
  }

  /**
   * Shutdown the service gracefully
   * @returns {Promise<void>}
   */
  async shutdown() {
    throw new Error('shutdown method must be implemented');
  }
}

module.exports = IAICritiqueService;