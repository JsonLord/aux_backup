/**
 * Interface for Screenshot Service
 * Defines the contract for screenshot capture operations
 */
class IScreenshotService {
  constructor() {
    if (new.target === IScreenshotService) {
      throw new Error('Cannot instantiate interface directly');
    }
  }

  /**
   * Capture a single screenshot
   * @param {string} url - Website URL to capture
   * @param {Object} options - Screenshot options
   * @param {Object} options.viewport - Viewport dimensions
   * @param {string} options.device - Device type (desktop, tablet, mobile)
   * @param {number} options.waitFor - Time to wait before capture (ms)
   * @param {boolean} options.fullPage - Capture full page or viewport only
   * @param {string} options.analysisId - Associated analysis ID for tracking
   * @returns {Promise<Object>} Screenshot result object
   */
  async captureScreenshot(url, options = {}) {
    throw new Error('captureScreenshot method must be implemented');
  }

  /**
   * Capture screenshots for multiple viewports
   * @param {string} url - Website URL to capture
   * @param {Array<string>} viewports - List of viewports to capture
   * @param {string} analysisId - Associated analysis ID for tracking
   * @returns {Promise<Object>} Screenshots result object with success/error details
   */
  async captureMultipleViewports(url, viewports, analysisId) {
    throw new Error('captureMultipleViewports method must be implemented');
  }

  /**
   * Validate if URL is accessible for screenshot capture
   * @param {string} url - Website URL to validate
   * @returns {Promise<boolean>} Validation result
   */
  async validateUrl(url) {
    throw new Error('validateUrl method must be implemented');
  }

  /**
   * Get screenshot file by ID
   * @param {string} screenshotId - Screenshot ID
   * @returns {Promise<Object>} Screenshot file information
   */
  async getScreenshot(screenshotId) {
    throw new Error('getScreenshot method must be implemented');
  }

  /**
   * Delete screenshot files
   * @param {string|Array<string>} screenshotIds - Screenshot ID(s) to delete
   * @returns {Promise<number>} Number of files deleted
   */
  async deleteScreenshots(screenshotIds) {
    throw new Error('deleteScreenshots method must be implemented');
  }

  /**
   * Cleanup old screenshot files
   * @param {number} maxAge - Maximum age in milliseconds
   * @returns {Promise<number>} Number of files cleaned up
   */
  async cleanupOldFiles(maxAge) {
    throw new Error('cleanupOldFiles method must be implemented');
  }

  /**
   * Get storage usage statistics
   * @returns {Promise<Object>} Storage statistics
   */
  async getStorageStats() {
    throw new Error('getStorageStats method must be implemented');
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

module.exports = IScreenshotService;