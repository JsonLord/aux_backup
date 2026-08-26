const puppeteer = require('puppeteer');
const EventEmitter = require('events');

class BrowserInstance {
  constructor(browser, options = {}) {
    this.browser = browser;
    this.id = this.generateId();
    this.createdAt = Date.now();
    this.lastUsed = Date.now();
    this.isIdle = true;
    this.usageCount = 0;
    this.maxIdleTime = options.maxIdleTime || 300000; // 5 minutes
    this.maxLifetime = options.maxLifetime || 1800000; // 30 minutes
    this.maxUsageCount = options.maxUsageCount || 100;
    this.activeTabs = new Set();
  }

  generateId() {
    return `browser_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  }

  async newPage() {
    const page = await this.browser.newPage();
    const pageId = `page_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

    this.activeTabs.add(pageId);
    this.usageCount++;
    this.lastUsed = Date.now();
    this.isIdle = false;

    // Wrap page.close to clean up from our tracking
    const originalClose = page.close.bind(page);
    page.close = async () => {
      this.activeTabs.delete(pageId);
      if (this.activeTabs.size === 0) {
        this.isIdle = true;
      }
      return originalClose();
    };

    return page;
  }

  isExpired() {
    const now = Date.now();
    const idleTime = now - this.lastUsed;
    const lifetime = now - this.createdAt;

    return (
      (this.isIdle && idleTime > this.maxIdleTime) ||
      lifetime > this.maxLifetime ||
      this.usageCount > this.maxUsageCount ||
      this.browser.isConnected() === false
    );
  }

  async close() {
    try {
      // Close all active pages first
      for (const page of await this.browser.pages()) {
        try {
          await page.close();
        } catch (error) {
          console.warn(`Error closing page: ${error.message}`);
        }
      }

      await this.browser.close();
      console.log(`Browser ${this.id} closed successfully`);
    } catch (error) {
      console.error(`Error closing browser ${this.id}:`, error.message);
    }
  }

  getStatus() {
    const now = Date.now();
    return {
      id: this.id,
      isIdle: this.isIdle,
      usageCount: this.usageCount,
      activeTabs: this.activeTabs.size,
      idleTime: now - this.lastUsed,
      lifetime: now - this.createdAt,
      isExpired: this.isExpired(),
      isConnected: this.browser.isConnected()
    };
  }
}

class BrowserPool extends EventEmitter {
  constructor(options = {}) {
    super();

    this.maxSize = options.maxSize || 3;
    this.minSize = options.minSize || 1;
    this.launchOptions = options.launchOptions || {
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-gpu',
        '--disable-web-security',
        '--single-process'
      ]
    };

    this.instanceOptions = {
      maxIdleTime: options.maxIdleTime || 300000,
      maxLifetime: options.maxLifetime || 1800000,
      maxUsageCount: options.maxUsageCount || 100
    };

    this.instances = new Map();
    this.queue = [];
    this.isShuttingDown = false;

    // Stats
    this.stats = {
      created: 0,
      destroyed: 0,
      acquired: 0,
      released: 0,
      errors: 0,
      currentSize: 0,
      queueSize: 0
    };

    // Start maintenance
    this.startMaintenance();
  }

  /**
   * Get a browser instance from the pool
   */
  async acquire(timeout = 30000) {
    if (this.isShuttingDown) {
      throw new Error('Browser pool is shutting down');
    }

    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        reject(new Error(`Browser acquisition timeout after ${timeout}ms`));
      }, timeout);

      const handleRequest = async () => {
        try {
          clearTimeout(timeoutId);
          const instance = await this.getOrCreateInstance();
          this.stats.acquired++;
          resolve(instance);
        } catch (error) {
          clearTimeout(timeoutId);
          this.stats.errors++;
          reject(error);
        }
      };

      if (this.hasAvailableInstance()) {
        handleRequest();
      } else if (this.instances.size < this.maxSize) {
        handleRequest();
      } else {
        // Add to queue
        this.queue.push(handleRequest);
        this.stats.queueSize = this.queue.length;
        this.emit('queue', { size: this.queue.length, maxSize: this.maxSize });
      }
    });
  }

  /**
   * Release a browser instance back to the pool
   */
  async release(instance) {
    if (!instance || !this.instances.has(instance.id)) {
      return;
    }

    instance.isIdle = true;
    instance.lastUsed = Date.now();
    this.stats.released++;

    this.emit('release', { instanceId: instance.id, stats: instance.getStatus() });

    // Process queue if there are waiting requests
    if (this.queue.length > 0) {
      const handleRequest = this.queue.shift();
      this.stats.queueSize = this.queue.length;
      setImmediate(handleRequest);
    }
  }

  /**
   * Check if there's an available instance
   */
  hasAvailableInstance() {
    for (const instance of this.instances.values()) {
      if (instance.isIdle && !instance.isExpired()) {
        return true;
      }
    }
    return false;
  }

  /**
   * Get an existing instance or create a new one
   */
  async getOrCreateInstance() {
    // Try to find an available instance
    for (const instance of this.instances.values()) {
      if (instance.isIdle && !instance.isExpired()) {
        return instance;
      }
    }

    // Create new instance if under limit
    if (this.instances.size < this.maxSize) {
      return await this.createInstance();
    }

    throw new Error('No available browser instances and pool is at maximum capacity');
  }

  /**
   * Create a new browser instance
   */
  async createInstance() {
    try {
      console.log('Creating new browser instance...');
      const browser = await puppeteer.launch(this.launchOptions);
      const instance = new BrowserInstance(browser, this.instanceOptions);

      this.instances.set(instance.id, instance);
      this.stats.created++;
      this.stats.currentSize = this.instances.size;

      this.emit('create', { instanceId: instance.id, poolSize: this.instances.size });

      // Set up browser disconnect handler
      browser.on('disconnected', () => {
        this.handleBrowserDisconnect(instance.id);
      });

      console.log(`Browser instance ${instance.id} created. Pool size: ${this.instances.size}`);
      return instance;

    } catch (error) {
      this.stats.errors++;
      console.error('Failed to create browser instance:', error);
      throw error;
    }
  }

  /**
   * Handle browser disconnect
   */
  handleBrowserDisconnect(instanceId) {
    const instance = this.instances.get(instanceId);
    if (instance) {
      console.warn(`Browser ${instanceId} disconnected unexpectedly`);
      this.instances.delete(instanceId);
      this.stats.destroyed++;
      this.stats.currentSize = this.instances.size;
      this.emit('disconnect', { instanceId, poolSize: this.instances.size });
    }
  }

  /**
   * Remove expired instances
   */
  async cleanupExpiredInstances() {
    const expiredInstances = [];

    for (const [id, instance] of this.instances.entries()) {
      if (instance.isExpired()) {
        expiredInstances.push(id);
      }
    }

    for (const id of expiredInstances) {
      await this.destroyInstance(id, 'expired');
    }

    if (expiredInstances.length > 0) {
      console.log(`Cleaned up ${expiredInstances.length} expired browser instances`);
    }
  }

  /**
   * Destroy a specific instance
   */
  async destroyInstance(instanceId, reason = 'manual') {
    const instance = this.instances.get(instanceId);
    if (!instance) {
      return;
    }

    try {
      await instance.close();
      this.instances.delete(instanceId);
      this.stats.destroyed++;
      this.stats.currentSize = this.instances.size;

      this.emit('destroy', {
        instanceId,
        reason,
        poolSize: this.instances.size,
        stats: instance.getStatus()
      });

      console.log(`Browser instance ${instanceId} destroyed (reason: ${reason})`);

    } catch (error) {
      console.error(`Error destroying browser instance ${instanceId}:`, error);
    }
  }

  /**
   * Ensure minimum pool size
   */
  async ensureMinimumSize() {
    const currentSize = this.instances.size;
    const needed = this.minSize - currentSize;

    if (needed > 0) {
      console.log(`Creating ${needed} browser instances to maintain minimum pool size`);

      const createPromises = [];
      for (let i = 0; i < needed; i++) {
        createPromises.push(this.createInstance().catch(error => {
          console.error('Failed to create browser instance for minimum pool size:', error);
        }));
      }

      await Promise.allSettled(createPromises);
    }
  }

  /**
   * Get pool status
   */
  getStatus() {
    const instances = Array.from(this.instances.values()).map(instance => instance.getStatus());

    return {
      poolSize: this.instances.size,
      maxSize: this.maxSize,
      minSize: this.minSize,
      queueSize: this.queue.length,
      isShuttingDown: this.isShuttingDown,
      stats: { ...this.stats },
      instances,
      healthy: instances.filter(i => i.isConnected && !i.isExpired).length,
      idle: instances.filter(i => i.isIdle).length,
      active: instances.filter(i => !i.isIdle).length,
      expired: instances.filter(i => i.isExpired).length
    };
  }

  /**
   * Start maintenance routine
   */
  startMaintenance() {
    this.maintenanceInterval = setInterval(async () => {
      try {
        await this.cleanupExpiredInstances();
        await this.ensureMinimumSize();

        // Log status periodically
        const status = this.getStatus();
        if (status.poolSize > 0) {
          console.log(`Browser pool status: ${status.poolSize}/${status.maxSize} instances, ${status.active} active, ${status.queueSize} queued`);
        }

      } catch (error) {
        console.error('Browser pool maintenance error:', error);
      }
    }, 30000); // Run every 30 seconds
  }

  /**
   * Stop maintenance routine
   */
  stopMaintenance() {
    if (this.maintenanceInterval) {
      clearInterval(this.maintenanceInterval);
      this.maintenanceInterval = null;
    }
  }

  /**
   * Shutdown the browser pool
   */
  async shutdown(timeout = 30000) {
    console.log('Shutting down browser pool...');
    this.isShuttingDown = true;
    this.stopMaintenance();

    // Reject all queued requests
    while (this.queue.length > 0) {
      const handleRequest = this.queue.shift();
      setImmediate(() => {
        handleRequest(new Error('Browser pool is shutting down'));
      });
    }

    // Close all instances
    const shutdownPromises = Array.from(this.instances.values()).map(async (instance) => {
      try {
        await instance.close();
      } catch (error) {
        console.error(`Error closing browser ${instance.id} during shutdown:`, error);
      }
    });

    // Wait for all instances to close or timeout
    const timeoutPromise = new Promise((resolve) => {
      setTimeout(resolve, timeout);
    });

    await Promise.race([
      Promise.allSettled(shutdownPromises),
      timeoutPromise
    ]);

    this.instances.clear();
    this.stats.currentSize = 0;

    console.log('Browser pool shutdown complete');
    this.emit('shutdown', { totalDestroyed: shutdownPromises.length });
  }

  /**
   * Health check
   */
  async healthCheck() {
    const status = this.getStatus();
    const healthyRatio = status.poolSize > 0 ? status.healthy / status.poolSize : 1;

    return {
      status: healthyRatio >= 0.5 ? 'healthy' : 'unhealthy',
      poolSize: status.poolSize,
      healthy: status.healthy,
      expired: status.expired,
      queueSize: status.queueSize,
      healthyRatio,
      details: status
    };
  }
}

module.exports = BrowserPool;