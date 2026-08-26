const fs = require('fs').promises;
const path = require('path');
const Joi = require('joi');
const configSchema = require('./schema');

class ConfigManager {
  constructor() {
    this.config = null;
    this.environment = process.env.NODE_ENV || 'development';
    this.configCache = new Map();
    this.watchers = new Map();
    this.validationErrors = [];
    this.isInitialized = false;
  }

  /**
   * Initialize the configuration manager
   */
  async initialize() {
    if (this.isInitialized) {
      return this.config;
    }

    try {
      // Load base configuration
      const baseConfig = await this.loadBaseConfig();

      // Load environment-specific configuration
      const envConfig = await this.loadEnvironmentConfig();

      // Merge configurations (environment overrides base)
      const mergedConfig = this.mergeConfigs(baseConfig, envConfig);

      // Load environment variables
      const envVarsConfig = this.loadEnvironmentVariables();

      // Final merge (env vars override everything)
      const finalConfig = this.mergeConfigs(mergedConfig, envVarsConfig);

      // Validate configuration
      await this.validateConfig(finalConfig);

      this.config = finalConfig;
      this.isInitialized = true;

      console.log(`Configuration loaded successfully for environment: ${this.environment}`);
      return this.config;

    } catch (error) {
      console.error('Failed to initialize configuration:', error);
      throw error;
    }
  }

  /**
   * Load base configuration
   */
  async loadBaseConfig() {
    const configPath = path.join(__dirname, 'default.json');

    try {
      const configFile = await fs.readFile(configPath, 'utf8');
      return JSON.parse(configFile);
    } catch (error) {
      if (error.code === 'ENOENT') {
        console.warn('Default configuration file not found, using schema defaults');
        return {};
      }
      throw new Error(`Failed to load base configuration: ${error.message}`);
    }
  }

  /**
   * Load environment-specific configuration
   */
  async loadEnvironmentConfig() {
    const configPath = path.join(__dirname, `${this.environment}.json`);

    try {
      const configFile = await fs.readFile(configPath, 'utf8');
      return JSON.parse(configFile);
    } catch (error) {
      if (error.code === 'ENOENT') {
        console.warn(`Environment configuration file not found: ${configPath}`);
        return {};
      }
      throw new Error(`Failed to load environment configuration: ${error.message}`);
    }
  }

  /**
   * Load configuration from environment variables
   */
  loadEnvironmentVariables() {
    const envConfig = {};

    // Map environment variables to configuration structure
    const envMappings = {
      // Server
      'PORT': 'server.port',
      'HOST': 'server.host',
      'NODE_ENV': 'server.environment',
      'CORS_ENABLED': 'server.corsEnabled',
      'RATE_LIMIT_ENABLED': 'server.rateLimitEnabled',
      'RATE_LIMIT_WINDOW_MS': 'server.rateLimitWindowMs',
      'RATE_LIMIT_MAX_REQUESTS': 'server.rateLimitMaxRequests',

      // Database
      'DATABASE_TYPE': 'database.type',
      'DATABASE_PATH': 'database.path',
      'DATABASE_HOST': 'database.host',
      'DATABASE_PORT': 'database.port',
      'DATABASE_NAME': 'database.name',
      'DATABASE_USERNAME': 'database.username',
      'DATABASE_PASSWORD': 'database.password',

      // AI Services
      'GEMINI_API_KEY': 'ai.gemini.apiKey',
      'GEMINI_MODEL': 'ai.gemini.model',
      'GEMINI_MAX_RETRIES': 'ai.gemini.maxRetries',
      'GEMINI_TIMEOUT_MS': 'ai.gemini.timeoutMs',

      // Analysis
      'MAX_CONCURRENT_ANALYSES': 'analysis.maxConcurrentAnalyses',
      'ANALYSIS_TIMEOUT_MS': 'analysis.timeoutMs',
      'MAX_STUCK_TIME_MS': 'analysis.maxStuckTimeMs',
      'CLEANUP_INTERVAL_MS': 'analysis.cleanupIntervalMs',
      'ENABLE_ACCESSIBILITY': 'analysis.enableAccessibility',
      'ENABLE_VISUAL_ANALYSIS': 'analysis.enableVisualAnalysis',
      'ENABLE_AI_CRITIQUE': 'analysis.enableAICritique',

      // Screenshots
      'SCREENSHOT_STORAGE_PATH': 'screenshots.storagePath',
      'SCREENSHOT_TIMEOUT_MS': 'screenshots.timeoutMs',
      'SCREENSHOT_WAIT_FOR_MS': 'screenshots.waitForMs',

      // Browser
      'BROWSER_POOL_SIZE': 'browser.poolSize',
      'BROWSER_MAX_IDLE_TIME_MS': 'browser.maxIdleTimeMs',
      'BROWSER_MAX_LIFETIME_MS': 'browser.maxLifetimeMs',
      'BROWSER_HEADLESS': 'browser.headless',

      // Logging
      'LOG_LEVEL': 'logging.level',
      'LOG_ENABLE_CONSOLE': 'logging.enableConsole',
      'LOG_ENABLE_FILE': 'logging.enableFile',
      'LOG_FILE_PATH': 'logging.filePath',

      // Features
      'FEATURE_ACCESSIBILITY_ANALYSIS': 'features.accessibilityAnalysis',
      'FEATURE_VISUAL_DESIGN_ANALYSIS': 'features.visualDesignAnalysis',
      'FEATURE_AI_CRITIQUE': 'features.aiCritique',
      'FEATURE_QUEUE_SYSTEM': 'features.queueSystem',
      'FEATURE_CACHING': 'features.caching',

      // Redis/Queue
      'REDIS_HOST': 'queue.redis.host',
      'REDIS_PORT': 'queue.redis.port',
      'REDIS_PASSWORD': 'queue.redis.password',
      'REDIS_DB': 'queue.redis.db'
    };

    // Process environment variables
    for (const [envVar, configPath] of Object.entries(envMappings)) {
      const value = process.env[envVar];
      if (value !== undefined) {
        this.setNestedValue(envConfig, configPath, this.parseEnvValue(value));
      }
    }

    return envConfig;
  }

  /**
   * Parse environment variable value to appropriate type
   */
  parseEnvValue(value) {
    // Boolean
    if (value.toLowerCase() === 'true') return true;
    if (value.toLowerCase() === 'false') return false;

    // Number
    if (/^\d+$/.test(value)) return parseInt(value, 10);
    if (/^\d+\.\d+$/.test(value)) return parseFloat(value);

    // Array (comma-separated)
    if (value.includes(',')) {
      return value.split(',').map(item => item.trim());
    }

    // String
    return value;
  }

  /**
   * Set nested object value using dot notation
   */
  setNestedValue(obj, path, value) {
    const keys = path.split('.');
    let current = obj;

    for (let i = 0; i < keys.length - 1; i++) {
      const key = keys[i];
      if (!(key in current) || typeof current[key] !== 'object') {
        current[key] = {};
      }
      current = current[key];
    }

    current[keys[keys.length - 1]] = value;
  }

  /**
   * Merge two configuration objects
   */
  mergeConfigs(base, override) {
    const result = JSON.parse(JSON.stringify(base));

    function merge(target, source) {
      for (const key in source) {
        if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
          if (!target[key] || typeof target[key] !== 'object') {
            target[key] = {};
          }
          merge(target[key], source[key]);
        } else {
          target[key] = source[key];
        }
      }
    }

    merge(result, override);
    return result;
  }

  /**
   * Validate configuration against schema
   */
  async validateConfig(config) {
    try {
      const { error, value } = configSchema.validate(config, {
        allowUnknown: false,
        abortEarly: false,
        stripUnknown: true
      });

      if (error) {
        this.validationErrors = error.details.map(detail => ({
          path: detail.path.join('.'),
          message: detail.message,
          value: detail.context?.value
        }));

        const errorMsg = `Configuration validation failed:\n${this.validationErrors
          .map(err => `  - ${err.path}: ${err.message}`)
          .join('\n')}`;

        throw new Error(errorMsg);
      }

      // Use validated and default-filled configuration
      Object.assign(config, value);

    } catch (error) {
      console.error('Configuration validation error:', error.message);
      throw error;
    }
  }

  /**
   * Get configuration value by path
   */
  get(path, defaultValue = undefined) {
    if (!this.isInitialized) {
      throw new Error('Configuration not initialized. Call initialize() first.');
    }

    if (!path) {
      return this.config;
    }

    const keys = path.split('.');
    let current = this.config;

    for (const key of keys) {
      if (current && typeof current === 'object' && key in current) {
        current = current[key];
      } else {
        return defaultValue;
      }
    }

    return current;
  }

  /**
   * Check if a feature is enabled
   */
  isFeatureEnabled(featureName) {
    return this.get(`features.${featureName}`, false);
  }

  /**
   * Get database configuration
   */
  getDatabaseConfig() {
    return this.get('database');
  }

  /**
   * Get server configuration
   */
  getServerConfig() {
    return this.get('server');
  }

  /**
   * Get AI service configuration
   */
  getAIConfig() {
    return this.get('ai');
  }

  /**
   * Get analysis configuration
   */
  getAnalysisConfig() {
    return this.get('analysis');
  }

  /**
   * Get browser configuration
   */
  getBrowserConfig() {
    return this.get('browser');
  }

  /**
   * Get logging configuration
   */
  getLoggingConfig() {
    return this.get('logging');
  }

  /**
   * Get health check configuration
   */
  getHealthConfig() {
    return this.get('health');
  }

  /**
   * Get security configuration
   */
  getSecurityConfig() {
    return this.get('security');
  }

  /**
   * Watch configuration file for changes
   */
  async watchConfig(callback) {
    if (!this.isFeatureEnabled('configReloading')) {
      return;
    }

    const configFiles = [
      path.join(__dirname, 'default.json'),
      path.join(__dirname, `${this.environment}.json`)
    ];

    for (const filePath of configFiles) {
      try {
        const watcher = fs.watch(filePath, async (eventType) => {
          if (eventType === 'change') {
            console.log(`Configuration file changed: ${filePath}`);
            try {
              await this.reload();
              if (callback) callback(this.config);
            } catch (error) {
              console.error('Failed to reload configuration:', error);
            }
          }
        });

        this.watchers.set(filePath, watcher);
      } catch (error) {
        console.warn(`Cannot watch configuration file: ${filePath}`);
      }
    }
  }

  /**
   * Reload configuration
   */
  async reload() {
    this.isInitialized = false;
    this.config = null;
    this.configCache.clear();
    await this.initialize();
  }

  /**
   * Stop watching configuration files
   */
  stopWatching() {
    for (const [filePath, watcher] of this.watchers) {
      try {
        watcher.close();
        console.log(`Stopped watching: ${filePath}`);
      } catch (error) {
        console.warn(`Error closing watcher for ${filePath}:`, error);
      }
    }
    this.watchers.clear();
  }

  /**
   * Validate required environment variables
   */
  validateRequiredEnvVars() {
    const required = [
      'GEMINI_API_KEY'
    ];

    const missing = required.filter(envVar => !process.env[envVar]);

    if (missing.length > 0) {
      throw new Error(`Missing required environment variables: ${missing.join(', ')}`);
    }
  }

  /**
   * Get current environment
   */
  getEnvironment() {
    return this.environment;
  }

  /**
   * Check if running in development mode
   */
  isDevelopment() {
    return this.environment === 'development';
  }

  /**
   * Check if running in production mode
   */
  isProduction() {
    return this.environment === 'production';
  }

  /**
   * Get configuration summary for logging
   */
  getSummary() {
    if (!this.isInitialized) {
      return { status: 'not_initialized' };
    }

    return {
      environment: this.environment,
      server: {
        port: this.get('server.port'),
        host: this.get('server.host')
      },
      features: this.get('features'),
      database: {
        type: this.get('database.type'),
        path: this.get('database.path')
      },
      analysis: {
        maxConcurrent: this.get('analysis.maxConcurrentAnalyses'),
        timeoutMs: this.get('analysis.timeoutMs')
      }
    };
  }
}

// Create singleton instance
const configManager = new ConfigManager();

module.exports = configManager;