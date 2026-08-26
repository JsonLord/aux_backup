const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
require('dotenv').config();

const { initializeDatabase } = require('./database/init');
const analysisRoutes = require('./routes/analysis');
const healthRoutes = require('./routes/health');

// New robust architecture imports
const configManager = require('./config/ConfigManager');
const serviceContainer = require('./core/ServiceContainer');
const ScreenshotService = require('./services/screenshotService');
const AICritiqueService = require('./services/aiCritiqueService');
const VisualDesignAnalyzer = require('./services/visualDesignAnalyzer');
const AnalysisService = require('./services/analysisService');
const CodeGenerationService = require('./services/codeGenerationService');

const app = express();
let config = null;
let PORT = process.env.PORT || 3000;

// Configure middleware and routes after initialization
function setupMiddleware() {
  // Security middleware
  app.use(helmet());
  app.use(cors());

  // Rate limiting (disabled in development)
  if (config.server.environment === 'production') {
    const limiter = rateLimit({
      windowMs: config.server.rateLimitWindowMs || 900000, // 15 minutes
      max: config.server.rateLimitMaxRequests || 10,
      message: 'Too many requests, please try again later.',
    });
    app.use('/api/', limiter);
  }

  // Body parsing
  app.use(express.json({ limit: '10mb' }));
  app.use(express.urlencoded({ extended: true }));

  // Make services available to routes
  app.use((req, res, next) => {
    req.services = serviceContainer;
    req.config = config;
    next();
  });

  // Routes
  app.use('/api/health', healthRoutes);
  app.use('/api/analyze', analysisRoutes);

  // Static files for screenshots
  app.use('/screenshots', express.static(config.screenshots.storagePath || 'data/screenshots'));

  // Error handling
  app.use((err, req, res, next) => {
    console.error(err.stack);
    res.status(500).json({
      error: 'Something went wrong!',
      message: config.server.environment === 'development' ? err.message : undefined
    });
  });

  // 404 handler
  app.use('*', (req, res) => {
    res.status(404).json({ error: 'Not found' });
  });
}

// Initialize robust architecture and start server
async function startServer() {
  try {
    console.log('🚀 Starting UX Analyst AI server with robust architecture...');

    // 1. Initialize configuration
    console.log('📋 Initializing configuration...');
    await configManager.initialize();
    configManager.validateRequiredEnvVars();
    config = configManager.get();
    PORT = config.server.port;
    console.log('✅ Configuration loaded successfully');

    // 2. Initialize database
    console.log('🗄️  Initializing database...');
    await initializeDatabase();
    console.log('✅ Database initialized');

    // 3. Register services with dependency injection
    console.log('🔧 Registering services...');
    await registerServices();

    // 4. Start all services
    console.log('▶️  Starting services...');
    await serviceContainer.startServices();
    console.log('✅ All services started successfully');

    // 5. Setup Express middleware and routes
    console.log('🌐 Setting up Express middleware and routes...');
    setupMiddleware();

    // 6. Start HTTP server
    await startServerWithPortHandling();

    // 7. Health check
    console.log('💊 Performing initial health check...');
    const healthStatus = await serviceContainer.getHealthStatus();
    console.log(`🏥 System health: ${healthStatus.status}`);

    // 8. Graceful shutdown handling
    process.on('SIGTERM', gracefulShutdown);
    process.on('SIGINT', gracefulShutdown);

    console.log('🎉 UX Analyst AI server startup complete!');

  } catch (error) {
    console.error('❌ Failed to start server:', error);
    await gracefulShutdown();
    process.exit(1);
  }
}

// Register all services with the service container
async function registerServices() {
  // Register ScreenshotService
  serviceContainer.register('screenshotService', (deps, container) => {
    return new ScreenshotService(config);
  }, {
    singleton: true,
    startupPriority: 10,
    dependencies: [],
    circuitBreaker: {
      failureThreshold: 3,
      recoveryTimeout: 30000
    },
    healthCheck: async (service) => service.getHealthStatus()
  });

  // Register VisualDesignAnalyzer
  serviceContainer.register('visualDesignAnalyzer', (deps, container) => {
    return new VisualDesignAnalyzer();
  }, {
    singleton: true,
    startupPriority: 20,
    dependencies: [],
    healthCheck: async (service) => ({ status: 'healthy' })
  });

  // Register AICritiqueService
  serviceContainer.register('aiCritiqueService', (deps, container) => {
    return new AICritiqueService(config);
  }, {
    singleton: true,
    startupPriority: 30,
    dependencies: [],
    circuitBreaker: {
      failureThreshold: 5,
      recoveryTimeout: 60000,
      expectedErrors: ['rate limit', '429', '503', 'timeout', 'overloaded']
    },
    healthCheck: async (service) => service.getHealthStatus()
  });

  // Register CodeGenerationService
  serviceContainer.register('codeGenerationService', (deps, container) => {
    return new CodeGenerationService({
      geminiApiKey: config.ai.geminiApiKey,
      logger: console
    });
  }, {
    singleton: true,
    startupPriority: 35,
    dependencies: [],
    circuitBreaker: {
      failureThreshold: 3,
      recoveryTimeout: 30000,
      expectedErrors: ['rate limit', '429', '503', 'timeout']
    },
    healthCheck: async (service) => service.getHealthStatus()
  });

  // Register AnalysisService (depends on other services)
  serviceContainer.register('analysisService', (deps, container) => {
    const screenshotService = container.get('screenshotService');
    const aiCritiqueService = container.get('aiCritiqueService');
    const visualDesignAnalyzer = container.get('visualDesignAnalyzer');
    const codeGenerationService = container.get('codeGenerationService');

    return new AnalysisService({
      screenshotService,
      aiCritiqueService,
      visualDesignAnalyzer,
      codeGenerationService,
      config
    });
  }, {
    singleton: true,
    startupPriority: 40,
    dependencies: ['screenshotService', 'aiCritiqueService', 'visualDesignAnalyzer', 'codeGenerationService'],
    healthCheck: async (service) => service.getHealthStatus ? service.getHealthStatus() : { status: 'healthy' }
  });

  console.log('✅ All services registered with dependency injection');
}

async function startServerWithPortHandling() {
  return new Promise((resolve, reject) => {
    const server = app.listen(PORT)
      .on('listening', () => {
        console.log(`🌐 UX Analyst AI server running on port ${PORT}`);
        console.log(`📊 Environment: ${config.server.environment}`);
        console.log(`🔗 Service endpoints:`);
        console.log(`   • Health: http://${config.server.host}:${PORT}/api/health`);
        console.log(`   • Analysis: http://${config.server.host}:${PORT}/api/analyze`);
        console.log(`   • Screenshots: http://${config.server.host}:${PORT}/screenshots/`);
        console.log(`🛡️  Circuit breakers active for fault tolerance`);
        console.log(`♻️  Resource cleanup and monitoring enabled`);
        resolve(server);
      })
      .on('error', (error) => {
        if (error.code === 'EADDRINUSE') {
          console.warn(`Port ${PORT} is in use. Attempting to detect and clean up stuck processes...`);

          // In production, you could add more sophisticated port cleanup here
          // For development, we'll provide helpful information
          console.error(`
❌ Port ${PORT} is already in use!

This usually means:
1. Another instance of this server is already running
2. A previous server instance crashed and didn't release the port
3. Another application is using this port

🔧 To resolve this:
1. Check running processes: netstat -ano | findstr :${PORT}
2. Kill the process: taskkill /PID <process_id>
3. Or restart your terminal/system

For production deployment, consider implementing automatic port cleanup or using process managers like PM2.
          `);

          reject(error);
        } else {
          reject(error);
        }
      });

    // Store server reference for graceful shutdown
    global.server = server;
  });
}

async function gracefulShutdown() {
  console.log('🛑 Received shutdown signal, cleaning up...');

  try {
    // Stop watching configuration files
    if (configManager) {
      configManager.stopWatching();
      console.log('📋 Configuration manager stopped');
    }

    // Shutdown all services through service container
    await serviceContainer.shutdown();
    console.log('🔧 All services shut down');

    // Close HTTP server
    if (global.server) {
      await new Promise((resolve, reject) => {
        global.server.close((error) => {
          if (error) {
            reject(error);
          } else {
            console.log('🌐 HTTP server closed');
            resolve();
          }
        });
      });
    }

    console.log('✅ Graceful shutdown complete');
    process.exit(0);

  } catch (error) {
    console.error('❌ Error during graceful shutdown:', error);

    // Force shutdown after error
    setTimeout(() => {
      console.error('⚠️ Forcing shutdown after error');
      process.exit(1);
    }, 5000);
  }
}


startServer();