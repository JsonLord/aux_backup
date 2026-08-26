const Joi = require('joi');

// Configuration schema validation using Joi
const configSchema = Joi.object({
  // Server Configuration
  server: Joi.object({
    port: Joi.number().integer().min(1000).max(65535).default(3000),
    host: Joi.string().default('localhost'),
    environment: Joi.string().valid('development', 'staging', 'production').default('development'),
    maxRequestSize: Joi.string().default('10mb'),
    corsEnabled: Joi.boolean().default(true),
    rateLimitEnabled: Joi.boolean().default(true),
    rateLimitWindowMs: Joi.number().integer().positive().default(900000), // 15 minutes
    rateLimitMaxRequests: Joi.number().integer().positive().default(10)
  }).required(),

  // Database Configuration
  database: Joi.object({
    type: Joi.string().valid('sqlite', 'postgres', 'mysql').default('sqlite'),
    path: Joi.string().default('./data/analysis.db'),
    host: Joi.string().when('type', { is: Joi.not('sqlite'), then: Joi.required() }),
    port: Joi.number().integer().when('type', { is: Joi.not('sqlite'), then: Joi.required() }),
    name: Joi.string().when('type', { is: Joi.not('sqlite'), then: Joi.required() }),
    username: Joi.string().when('type', { is: Joi.not('sqlite'), then: Joi.required() }),
    password: Joi.string().when('type', { is: Joi.not('sqlite'), then: Joi.required() }),
    maxConnections: Joi.number().integer().positive().default(10),
    acquireTimeoutMs: Joi.number().integer().positive().default(30000),
    createTimeoutMs: Joi.number().integer().positive().default(30000),
    destroyTimeoutMs: Joi.number().integer().positive().default(5000),
    idleTimeoutMs: Joi.number().integer().positive().default(30000),
    reapIntervalMs: Joi.number().integer().positive().default(1000)
  }).required(),

  // AI Services Configuration
  ai: Joi.object({
    gemini: Joi.object({
      apiKey: Joi.string().required(),
      model: Joi.string().default('gemini-1.5-flash'),
      maxRetries: Joi.number().integer().min(1).max(10).default(3),
      baseDelay: Joi.number().integer().positive().default(2000),
      timeoutMs: Joi.number().integer().positive().default(45000),
      maxConcurrentRequests: Joi.number().integer().positive().default(5)
    }).required()
  }).required(),

  // Analysis Configuration
  analysis: Joi.object({
    maxConcurrentAnalyses: Joi.number().integer().positive().default(3),
    timeoutMs: Joi.number().integer().positive().default(300000), // 5 minutes
    maxStuckTimeMs: Joi.number().integer().positive().default(600000), // 10 minutes
    cleanupIntervalMs: Joi.number().integer().positive().default(120000), // 2 minutes
    defaultViewports: Joi.array().items(
      Joi.string().valid('desktop', 'tablet', 'mobile')
    ).default(['desktop', 'tablet', 'mobile']),
    enableAccessibility: Joi.boolean().default(false),
    enableVisualAnalysis: Joi.boolean().default(true),
    enableAICritique: Joi.boolean().default(true)
  }).required(),

  // Screenshot Service Configuration
  screenshots: Joi.object({
    storagePath: Joi.string().default('./data/screenshots'),
    maxFileSize: Joi.number().integer().positive().default(10485760), // 10MB
    retentionDays: Joi.number().integer().positive().default(30),
    timeoutMs: Joi.number().integer().positive().default(15000),
    waitForMs: Joi.number().integer().positive().default(1000),
    viewports: Joi.object({
      desktop: Joi.object({
        width: Joi.number().integer().positive().default(1920),
        height: Joi.number().integer().positive().default(1080)
      }),
      tablet: Joi.object({
        width: Joi.number().integer().positive().default(768),
        height: Joi.number().integer().positive().default(1024)
      }),
      mobile: Joi.object({
        width: Joi.number().integer().positive().default(375),
        height: Joi.number().integer().positive().default(667)
      })
    }).default({
      desktop: { width: 1920, height: 1080 },
      tablet: { width: 768, height: 1024 },
      mobile: { width: 375, height: 667 }
    })
  }).required(),

  // Browser Configuration
  browser: Joi.object({
    poolSize: Joi.number().integer().positive().default(3),
    maxIdleTimeMs: Joi.number().integer().positive().default(300000), // 5 minutes
    maxLifetimeMs: Joi.number().integer().positive().default(1800000), // 30 minutes
    launchArgs: Joi.array().items(Joi.string()).default([
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--disable-web-security',
      '--single-process'
    ]),
    headless: Joi.boolean().default(true),
    enableLogging: Joi.boolean().default(false)
  }).required(),

  // Visual Analysis Configuration
  visualAnalysis: Joi.object({
    enableColorAnalysis: Joi.boolean().default(true),
    enableLayoutAnalysis: Joi.boolean().default(true),
    enableTypographyAnalysis: Joi.boolean().default(true),
    enableSpacingAnalysis: Joi.boolean().default(true),
    enableHierarchyAnalysis: Joi.boolean().default(true),
    maxImageSize: Joi.number().integer().positive().default(5242880), // 5MB
    processingTimeoutMs: Joi.number().integer().positive().default(30000),
    colorThresholds: Joi.object({
      lowContrast: Joi.number().positive().default(3.0),
      normalContrast: Joi.number().positive().default(4.5),
      highContrast: Joi.number().positive().default(7.0)
    }),
    layoutThresholds: Joi.object({
      minWhitespace: Joi.number().min(0).max(1).default(0.15),
      maxContentDensity: Joi.number().min(0).max(1).default(0.7),
      minTouchTargetSize: Joi.number().positive().default(44)
    })
  }).required(),

  // Logging Configuration
  logging: Joi.object({
    level: Joi.string().valid('error', 'warn', 'info', 'debug').default('info'),
    enableConsole: Joi.boolean().default(true),
    enableFile: Joi.boolean().default(false),
    filePath: Joi.string().default('./logs/app.log'),
    maxFileSize: Joi.string().default('10MB'),
    maxFiles: Joi.number().integer().positive().default(5),
    enableStructured: Joi.boolean().default(true),
    enableCorrelationId: Joi.boolean().default(true)
  }).required(),

  // Health Check Configuration
  health: Joi.object({
    enabled: Joi.boolean().default(true),
    endpoint: Joi.string().default('/health'),
    intervalMs: Joi.number().integer().positive().default(30000),
    timeoutMs: Joi.number().integer().positive().default(5000),
    checks: Joi.object({
      database: Joi.boolean().default(true),
      ai: Joi.boolean().default(true),
      storage: Joi.boolean().default(true),
      memory: Joi.boolean().default(true),
      browser: Joi.boolean().default(true)
    })
  }).required(),

  // Security Configuration
  security: Joi.object({
    helmet: Joi.object({
      enabled: Joi.boolean().default(true),
      contentSecurityPolicy: Joi.boolean().default(true),
      crossOriginEmbedderPolicy: Joi.boolean().default(false)
    }),
    cors: Joi.object({
      enabled: Joi.boolean().default(true),
      origin: Joi.alternatives().try(
        Joi.boolean(),
        Joi.string(),
        Joi.array().items(Joi.string())
      ).default(true),
      credentials: Joi.boolean().default(false)
    }),
    rateLimit: Joi.object({
      enabled: Joi.boolean().default(true),
      windowMs: Joi.number().integer().positive().default(900000),
      max: Joi.number().integer().positive().default(100),
      standardHeaders: Joi.boolean().default(true),
      legacyHeaders: Joi.boolean().default(false)
    })
  }).required(),

  // Feature Flags
  features: Joi.object({
    accessibilityAnalysis: Joi.boolean().default(false),
    visualDesignAnalysis: Joi.boolean().default(true),
    aiCritique: Joi.boolean().default(true),
    advancedReporting: Joi.boolean().default(false),
    queueSystem: Joi.boolean().default(false),
    caching: Joi.boolean().default(false),
    metrics: Joi.boolean().default(false),
    websockets: Joi.boolean().default(false)
  }).required(),

  // Queue Configuration (for future implementation)
  queue: Joi.object({
    enabled: Joi.boolean().default(false),
    redis: Joi.object({
      host: Joi.string().default('localhost'),
      port: Joi.number().integer().positive().default(6379),
      password: Joi.string().allow(''),
      db: Joi.number().integer().min(0).default(0),
      keyPrefix: Joi.string().default('ux-analyst:'),
      maxRetriesPerJob: Joi.number().integer().min(0).default(3)
    }),
    jobs: Joi.object({
      analysis: Joi.object({
        priority: Joi.number().integer().default(0),
        attempts: Joi.number().integer().positive().default(3),
        backoff: Joi.object({
          type: Joi.string().valid('fixed', 'exponential').default('exponential'),
          delay: Joi.number().integer().positive().default(2000)
        })
      })
    })
  }).required()
});

module.exports = configSchema;