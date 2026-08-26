/**
 * Bootstrap script demonstrating the new robust architecture
 * This shows how to properly initialize services with the new system
 */

const configManager = require('./config/ConfigManager');
const serviceContainer = require('./core/ServiceContainer');

// Import service classes
const ScreenshotService = require('./services/screenshotService');
const AICritiqueService = require('./services/aiCritiqueService');
const VisualDesignAnalyzer = require('./services/visualDesignAnalyzer');

async function bootstrap() {
  try {
    console.log('🚀 Starting UX Analyst AI with robust architecture...');

    // 1. Initialize configuration
    console.log('📋 Initializing configuration...');
    await configManager.initialize();

    // Validate required environment variables
    configManager.validateRequiredEnvVars();

    const config = configManager.get();
    console.log('✅ Configuration loaded successfully');
    console.log('📊 Config summary:', JSON.stringify(configManager.getSummary(), null, 2));

    // 2. Register services with dependency injection
    console.log('🔧 Registering services...');

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

    // 3. Start all services in priority order
    console.log('▶️  Starting services...');
    await serviceContainer.startServices();

    // 4. Get services and test them
    console.log('🧪 Testing services...');

    const screenshotService = serviceContainer.get('screenshotService');
    const aiCritiqueService = serviceContainer.get('aiCritiqueService');
    const visualAnalyzer = serviceContainer.get('visualDesignAnalyzer');

    console.log('✅ All services initialized successfully!');

    // 5. Health check
    console.log('💊 Performing health check...');
    const healthStatus = await serviceContainer.getHealthStatus();
    console.log('🏥 Health status:', JSON.stringify(healthStatus, null, 2));

    // 6. Service statistics
    console.log('📈 Service statistics:', JSON.stringify(serviceContainer.getStats(), null, 2));

    // 7. Set up graceful shutdown
    process.on('SIGTERM', gracefulShutdown);
    process.on('SIGINT', gracefulShutdown);

    console.log('🎉 Bootstrap complete! System is ready.');
    return { configManager, serviceContainer };

  } catch (error) {
    console.error('❌ Bootstrap failed:', error);
    process.exit(1);
  }
}

/**
 * Graceful shutdown handler
 */
async function gracefulShutdown() {
  console.log('🛑 Graceful shutdown initiated...');

  try {
    // Stop watching configuration files
    configManager.stopWatching();

    // Shutdown all services
    await serviceContainer.shutdown();

    console.log('✅ Graceful shutdown complete');
    process.exit(0);

  } catch (error) {
    console.error('❌ Error during graceful shutdown:', error);
    process.exit(1);
  }
}

/**
 * Demo function showing how to use the services
 */
async function demo() {
  const { serviceContainer } = await bootstrap();

  try {
    console.log('\n🎬 Running demo...');

    // Get services from container
    const screenshotService = serviceContainer.get('screenshotService');

    // Test screenshot capture with new architecture
    console.log('📸 Testing screenshot capture...');

    const screenshotResult = await screenshotService.captureScreenshot('https://example.com', {
      device: 'desktop',
      viewport: { width: 1920, height: 1080 }
    });

    console.log('✅ Screenshot captured:', screenshotResult);

    // Check health after operations
    const finalHealth = await serviceContainer.getHealthStatus();
    console.log('💊 Final health check:', finalHealth.status);

  } catch (error) {
    console.error('❌ Demo failed:', error);
  }
}

// Export for use in other files
module.exports = {
  bootstrap,
  gracefulShutdown,
  demo
};

// Run demo if this file is executed directly
if (require.main === module) {
  demo().catch(console.error);
}