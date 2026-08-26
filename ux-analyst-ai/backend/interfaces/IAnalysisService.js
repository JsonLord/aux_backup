/**
 * Interface for Analysis Service
 * Defines the contract for website analysis operations
 */
class IAnalysisService {
  constructor() {
    if (new.target === IAnalysisService) {
      throw new Error('Cannot instantiate interface directly');
    }
  }

  /**
   * Analyze a website with given options
   * @param {string} url - Website URL to analyze
   * @param {Object} options - Analysis options
   * @param {Array<string>} options.viewports - Viewports to analyze (desktop, tablet, mobile)
   * @param {string} options.analysisType - Type of analysis (quick, comprehensive)
   * @param {boolean} options.includeAccessibility - Include accessibility analysis
   * @param {boolean} options.includeVisualAnalysis - Include visual design analysis
   * @param {boolean} options.includeAICritique - Include AI-powered critique
   * @returns {Promise<Object>} Analysis result object
   */
  async analyzeWebsite(url, options = {}) {
    throw new Error('analyzeWebsite method must be implemented');
  }

  /**
   * Get analysis result by ID
   * @param {string} analysisId - Analysis ID
   * @returns {Promise<Object>} Analysis result
   */
  async getAnalysisResult(analysisId) {
    throw new Error('getAnalysisResult method must be implemented');
  }

  /**
   * Update analysis progress
   * @param {string} analysisId - Analysis ID
   * @param {number} progress - Progress percentage (0-100)
   * @param {string} stage - Current stage description
   * @returns {Promise<void>}
   */
  async updateProgress(analysisId, progress, stage) {
    throw new Error('updateProgress method must be implemented');
  }

  /**
   * Cancel an ongoing analysis
   * @param {string} analysisId - Analysis ID to cancel
   * @returns {Promise<boolean>} Success status
   */
  async cancelAnalysis(analysisId) {
    throw new Error('cancelAnalysis method must be implemented');
  }

  /**
   * Get list of active analyses
   * @returns {Promise<Array>} List of active analysis objects
   */
  async getActiveAnalyses() {
    throw new Error('getActiveAnalyses method must be implemented');
  }

  /**
   * Cleanup stuck or expired analyses
   * @returns {Promise<number>} Number of analyses cleaned up
   */
  async cleanupStuckAnalyses() {
    throw new Error('cleanupStuckAnalyses method must be implemented');
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

module.exports = IAnalysisService;