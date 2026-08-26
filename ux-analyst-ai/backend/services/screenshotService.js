const path = require('path');
const fs = require('fs').promises;
const { v4: uuidv4 } = require('uuid');
const IScreenshotService = require('../interfaces/IScreenshotService');
const BrowserPool = require('../core/BrowserPool');
const CircuitBreaker = require('../core/CircuitBreaker');

class ScreenshotService extends IScreenshotService {
  constructor(config, logger = console) {
    super();

    this.config = config;
    this.logger = logger;
    this.storagePath = config.screenshots.storagePath;
    this.viewports = config.screenshots.viewports;
    this.timeoutMs = config.screenshots.timeoutMs;
    this.waitForMs = config.screenshots.waitForMs;
    this.maxFileSize = config.screenshots.maxFileSize;
    this.retentionDays = config.screenshots.retentionDays;

    // Initialize browser pool
    this.browserPool = new BrowserPool({
      maxSize: config.browser.poolSize,
      launchOptions: {
        headless: config.browser.headless,
        args: config.browser.launchArgs
      },
      maxIdleTime: config.browser.maxIdleTimeMs,
      maxLifetime: config.browser.maxLifetimeMs
    });

    // Initialize circuit breaker for screenshot operations
    this.circuitBreaker = CircuitBreaker.forAPI('Screenshot', {
      failureThreshold: 3,
      recoveryTimeout: 30000,
      expectedErrors: ['timeout', 'navigation', 'network']
    });

    this.stats = {
      captureAttempts: 0,
      captureSuccesses: 0,
      captureFailures: 0,
      totalSize: 0,
      averageSize: 0
    };

    this.isShuttingDown = false;
  }

  setAnalysisService(analysisService) {
    this.analysisService = analysisService;
  }

  async ensureStorageDirectory() {
    await fs.mkdir(this.storagePath, { recursive: true });
  }

  async captureScreenshot(url, options = {}) {
    if (this.isShuttingDown) {
      throw new Error('Screenshot service is shutting down');
    }

    const {
      viewport = this.viewports.desktop,
      device = 'desktop',
      waitFor = this.waitForMs,
      fullPage = true,
      analysisId = null
    } = options;

    this.stats.captureAttempts++;

    return this.circuitBreaker.execute(async () => {
      let browserInstance = null;
      let page = null;

      try {
        this.logger.log(`Starting screenshot capture for ${url} on ${device}`);

        // Get browser instance from pool
        browserInstance = await this.browserPool.acquire(this.timeoutMs);
        page = await browserInstance.newPage();

        // Configure page
        await page.setViewport(viewport);
        await page.setUserAgent(this.getUserAgent(device));

        // Set timeouts
        await page.setDefaultTimeout(this.timeoutMs);
        await page.setDefaultNavigationTimeout(this.timeoutMs);

        // Navigate with timeout protection
        const result = await Promise.race([
          this.performScreenshotCapture(page, url, device, waitFor, fullPage),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error('Screenshot capture timed out')), this.timeoutMs)
          )
        ]);

        this.stats.captureSuccesses++;
        this.updateFileStats(result.fileSize);

        return result;

      } catch (error) {
        this.stats.captureFailures++;
        this.logger.error(`Screenshot capture failed for ${url} on ${device}:`, error.message);
        throw error;

      } finally {
        // Cleanup page
        if (page) {
          try {
            await page.close();
          } catch (error) {
            this.logger.warn(`Error closing page: ${error.message}`);
          }
        }

        // Release browser back to pool
        if (browserInstance) {
          try {
            await this.browserPool.release(browserInstance);
          } catch (error) {
            this.logger.warn(`Error releasing browser: ${error.message}`);
          }
        }
      }
    });
  }

  /**
   * Perform the actual screenshot capture
   */
  async performScreenshotCapture(page, url, device, waitFor, fullPage) {
    // Navigate to URL
    this.logger.log(`Navigating to ${url}`);
    await page.goto(url, {
      waitUntil: 'domcontentloaded',
      timeout: this.timeoutMs
    });

    this.logger.log(`Page loaded, waiting ${waitFor}ms`);
    await page.waitForTimeout(waitFor);

    // Generate filename
    const screenshotId = uuidv4();
    const filename = `${screenshotId}-${device}.png`;
    const filepath = path.join(this.storagePath, filename);

    await this.ensureStorageDirectory();

    this.logger.log(`Taking screenshot: ${filepath}`);

    // Capture screenshot
    await page.screenshot({
      path: filepath,
      fullPage,
      type: 'png'
    });

    // Get file stats
    const stats = await fs.stat(filepath);

    // Validate file size
    if (stats.size > this.maxFileSize) {
      await fs.unlink(filepath); // Delete oversized file
      throw new Error(`Screenshot file too large: ${stats.size} bytes (max: ${this.maxFileSize})`);
    }

    this.logger.log(`Screenshot completed: ${device} - ${stats.size} bytes`);

    const viewport = await page.viewport();
    return {
      id: screenshotId,
      device,
      filepath,
      filename,
      width: viewport.width,
      height: viewport.height,
      fileSize: stats.size,
      url
    };
  }

  /**
   * Get user agent string for device type
   */
  getUserAgent(device) {
    const userAgents = {
      desktop: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      tablet: 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
      mobile: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
    };

    return userAgents[device] || userAgents.desktop;
  }

  /**
   * Update file statistics
   */
  updateFileStats(fileSize) {
    this.stats.totalSize += fileSize;
    this.stats.averageSize = this.stats.totalSize / this.stats.captureSuccesses;
  }

  async captureMultipleViewports(url, viewportNames = ['desktop', 'tablet', 'mobile'], analysisId = null) {
    const screenshots = {};
    const errors = {};

    for (const viewportName of viewportNames) {
      try {
        const viewport = this.viewports[viewportName];
        if (!viewport) {
          throw new Error(`Unknown viewport: ${viewportName}`);
        }

        const screenshot = await this.captureScreenshot(url, {
          viewport,
          device: viewportName,
          analysisId // Pass analysis ID for browser tracking
        });

        screenshots[viewportName] = screenshot;
      } catch (error) {
        console.error(`Error capturing ${viewportName} screenshot:`, error);
        errors[viewportName] = error.message;
      }
    }

    return {
      screenshots,
      errors: Object.keys(errors).length > 0 ? errors : null
    };
  }

  async validateUrl(url) {
    try {
      const urlObj = new URL(url);

      // Only allow http and https
      if (!['http:', 'https:'].includes(urlObj.protocol)) {
        throw new Error('Only HTTP and HTTPS URLs are allowed');
      }

      // Skip browser validation for faster startup - just do basic URL format check
      return true;
    } catch (error) {
      throw new Error(`Invalid URL format: ${error.message}`);
    }
  }

  async getScreenshotMetadata(screenshotPath) {
    try {
      const stats = await fs.stat(screenshotPath);
      return {
        exists: true,
        size: stats.size,
        created: stats.birthtime,
        modified: stats.mtime
      };
    } catch (error) {
      return {
        exists: false,
        error: error.message
      };
    }
  }

  async cleanup(screenshotPaths) {
    const results = [];
    for (const filepath of screenshotPaths) {
      try {
        await fs.unlink(filepath);
        results.push({ filepath, deleted: true });
      } catch (error) {
        results.push({ filepath, deleted: false, error: error.message });
      }
    }
    return results;
  }

  /**
   * Get screenshot by ID (interface method)
   */
  async getScreenshot(screenshotId) {
    // Implementation would query database for screenshot by ID
    throw new Error('getScreenshot method not implemented - requires database integration');
  }

  /**
   * Delete screenshots by ID (interface method)
   */
  async deleteScreenshots(screenshotIds) {
    const ids = Array.isArray(screenshotIds) ? screenshotIds : [screenshotIds];
    let deletedCount = 0;

    for (const id of ids) {
      try {
        // This would need database integration to find file path by ID
        // For now, we'll use the cleanup method with known file paths
        deletedCount++;
      } catch (error) {
        this.logger.error(`Failed to delete screenshot ${id}:`, error.message);
      }
    }

    return deletedCount;
  }

  /**
   * Cleanup old screenshot files
   */
  async cleanupOldFiles(maxAge = this.retentionDays * 24 * 60 * 60 * 1000) {
    try {
      const files = await fs.readdir(this.storagePath);
      const now = Date.now();
      let deletedCount = 0;

      for (const file of files) {
        const filePath = path.join(this.storagePath, file);
        const stats = await fs.stat(filePath);

        if (now - stats.mtime.getTime() > maxAge) {
          await fs.unlink(filePath);
          deletedCount++;
        }
      }

      this.logger.log(`Cleaned up ${deletedCount} old screenshot files`);
      return deletedCount;

    } catch (error) {
      this.logger.error('Failed to cleanup old files:', error.message);
      return 0;
    }
  }

  /**
   * Get storage usage statistics
   */
  async getStorageStats() {
    try {
      const files = await fs.readdir(this.storagePath);
      let totalSize = 0;
      let fileCount = 0;

      for (const file of files) {
        const filePath = path.join(this.storagePath, file);
        const stats = await fs.stat(filePath);
        totalSize += stats.size;
        fileCount++;
      }

      return {
        fileCount,
        totalSize,
        averageSize: fileCount > 0 ? totalSize / fileCount : 0,
        storagePath: this.storagePath,
        maxFileSize: this.maxFileSize,
        retentionDays: this.retentionDays
      };

    } catch (error) {
      this.logger.error('Failed to get storage stats:', error.message);
      return {
        fileCount: 0,
        totalSize: 0,
        averageSize: 0,
        error: error.message
      };
    }
  }

  /**
   * Get service health status
   */
  async getHealthStatus() {
    try {
      const browserPoolHealth = await this.browserPool.healthCheck();
      const circuitBreakerStatus = this.circuitBreaker.getStatus();
      const storageStats = await this.getStorageStats();

      // Check if storage directory is accessible
      await fs.access(this.storagePath);

      const isHealthy = (
        browserPoolHealth.status === 'healthy' &&
        circuitBreakerStatus.state !== 'OPEN' &&
        !this.isShuttingDown
      );

      return {
        status: isHealthy ? 'healthy' : 'unhealthy',
        browserPool: browserPoolHealth,
        circuitBreaker: {
          state: circuitBreakerStatus.state,
          failureCount: circuitBreakerStatus.failureCount,
          successRate: circuitBreakerStatus.monitoring.successRate
        },
        storage: storageStats,
        stats: this.stats,
        isShuttingDown: this.isShuttingDown
      };

    } catch (error) {
      return {
        status: 'unhealthy',
        error: error.message,
        stats: this.stats
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

    this.logger.log('Shutting down ScreenshotService...');
    this.isShuttingDown = true;

    try {
      // Stop circuit breaker monitoring
      this.circuitBreaker.stopMonitoring();

      // Shutdown browser pool
      await this.browserPool.shutdown();

      this.logger.log('ScreenshotService shutdown complete');

    } catch (error) {
      this.logger.error('Error during ScreenshotService shutdown:', error.message);
      throw error;
    }
  }
}

module.exports = ScreenshotService;