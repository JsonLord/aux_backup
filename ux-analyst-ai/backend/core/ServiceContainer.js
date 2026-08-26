const EventEmitter = require('events');

/**
 * Service Container for dependency injection and service lifecycle management
 */
class ServiceContainer extends EventEmitter {
  constructor() {
    super();
    this.services = new Map();
    this.factories = new Map();
    this.singletons = new Map();
    this.circuitBreakers = new Map();
    this.isShuttingDown = false;
    this.startupOrder = [];
    this.shutdownOrder = [];
  }

  /**
   * Register a service factory
   * @param {string} name - Service name
   * @param {Function} factory - Factory function that creates the service
   * @param {Object} options - Registration options
   * @param {boolean} options.singleton - Whether to create only one instance
   * @param {Array<string>} options.dependencies - List of service dependencies
   * @param {Object} options.circuitBreaker - Circuit breaker configuration
   * @param {number} options.startupPriority - Startup priority (lower = earlier)
   * @param {Function} options.healthCheck - Health check function
   */
  register(name, factory, options = {}) {
    if (this.factories.has(name)) {
      throw new Error(`Service '${name}' is already registered`);
    }

    const serviceConfig = {
      factory,
      singleton: options.singleton || false,
      dependencies: options.dependencies || [],
      circuitBreaker: options.circuitBreaker || null,
      startupPriority: options.startupPriority || 100,
      healthCheck: options.healthCheck || null,
      startupTimeout: options.startupTimeout || 30000,
      shutdownTimeout: options.shutdownTimeout || 10000
    };

    this.factories.set(name, serviceConfig);

    // Add to startup order based on priority
    this.updateStartupOrder(name, serviceConfig.startupPriority);

    console.log(`Service '${name}' registered${serviceConfig.singleton ? ' (singleton)' : ''}`);
  }

  /**
   * Register a service instance directly
   * @param {string} name - Service name
   * @param {*} instance - Service instance
   * @param {Object} options - Registration options
   */
  registerInstance(name, instance, options = {}) {
    if (this.services.has(name)) {
      throw new Error(`Service instance '${name}' is already registered`);
    }

    this.services.set(name, instance);

    if (options.healthCheck) {
      this.factories.set(name, { healthCheck: options.healthCheck });
    }

    console.log(`Service instance '${name}' registered`);
  }

  /**
   * Get a service instance
   * @param {string} name - Service name
   * @returns {*} Service instance
   */
  get(name) {
    if (this.isShuttingDown) {
      throw new Error(`Cannot get service '${name}' during shutdown`);
    }

    // Return existing instance if available
    if (this.services.has(name)) {
      return this.services.get(name);
    }

    // Return singleton if available
    if (this.singletons.has(name)) {
      return this.singletons.get(name);
    }

    // Create new instance
    return this.createInstance(name);
  }

  /**
   * Create a new service instance
   * @param {string} name - Service name
   * @returns {*} Service instance
   */
  createInstance(name) {
    const serviceConfig = this.factories.get(name);
    if (!serviceConfig) {
      throw new Error(`Service '${name}' is not registered`);
    }

    // Check for circular dependencies
    this.checkCircularDependencies(name, new Set());

    // Create dependency instances
    const dependencies = {};
    for (const depName of serviceConfig.dependencies) {
      dependencies[depName] = this.get(depName);
    }

    // Create service instance
    let instance;
    try {
      instance = serviceConfig.factory(dependencies, this);
    } catch (error) {
      console.error(`Failed to create service '${name}':`, error);
      throw new Error(`Service creation failed for '${name}': ${error.message}`);
    }

    // Store instance
    if (serviceConfig.singleton) {
      this.singletons.set(name, instance);
    } else {
      this.services.set(name, instance);
    }

    // Set up circuit breaker if configured
    if (serviceConfig.circuitBreaker) {
      this.setupCircuitBreaker(name, instance, serviceConfig.circuitBreaker);
    }

    this.emit('serviceCreated', { name, instance, config: serviceConfig });
    console.log(`Service '${name}' created successfully`);

    return instance;
  }

  /**
   * Check for circular dependencies
   * @param {string} name - Service name
   * @param {Set} visited - Set of visited services
   */
  checkCircularDependencies(name, visited) {
    if (visited.has(name)) {
      const cycle = Array.from(visited).concat(name).join(' -> ');
      throw new Error(`Circular dependency detected: ${cycle}`);
    }

    const serviceConfig = this.factories.get(name);
    if (!serviceConfig) return;

    visited.add(name);

    for (const depName of serviceConfig.dependencies) {
      this.checkCircularDependencies(depName, new Set(visited));
    }
  }

  /**
   * Set up circuit breaker for a service
   * @param {string} name - Service name
   * @param {*} instance - Service instance
   * @param {Object} circuitBreakerConfig - Circuit breaker configuration
   */
  setupCircuitBreaker(name, instance, circuitBreakerConfig) {
    const CircuitBreaker = require('./CircuitBreaker');

    const breaker = new CircuitBreaker({
      name: `Service_${name}`,
      ...circuitBreakerConfig,
      onStateChange: (event) => {
        this.emit('circuitBreakerStateChange', { serviceName: name, ...event });
      },
      onFailure: (event) => {
        this.emit('circuitBreakerFailure', { serviceName: name, ...event });
      }
    });

    this.circuitBreakers.set(name, breaker);

    // Wrap service methods with circuit breaker
    this.wrapServiceWithCircuitBreaker(instance, breaker);
  }

  /**
   * Wrap service methods with circuit breaker
   * @param {*} instance - Service instance
   * @param {CircuitBreaker} breaker - Circuit breaker instance
   */
  wrapServiceWithCircuitBreaker(instance, breaker) {
    const methodsToWrap = ['execute', 'run', 'process', 'analyze', 'generate'];

    for (const methodName of methodsToWrap) {
      if (typeof instance[methodName] === 'function') {
        const originalMethod = instance[methodName].bind(instance);
        instance[methodName] = (...args) => {
          return breaker.execute(originalMethod, ...args);
        };
      }
    }
  }

  /**
   * Check if a service is registered
   * @param {string} name - Service name
   * @returns {boolean} Registration status
   */
  has(name) {
    return this.factories.has(name) || this.services.has(name);
  }

  /**
   * Update startup order based on priority
   * @param {string} name - Service name
   * @param {number} priority - Startup priority
   */
  updateStartupOrder(name, priority) {
    // Remove if already exists
    const existingIndex = this.startupOrder.findIndex(item => item.name === name);
    if (existingIndex !== -1) {
      this.startupOrder.splice(existingIndex, 1);
    }

    // Insert at correct position based on priority
    const insertIndex = this.startupOrder.findIndex(item => item.priority > priority);
    if (insertIndex === -1) {
      this.startupOrder.push({ name, priority });
    } else {
      this.startupOrder.splice(insertIndex, 0, { name, priority });
    }

    // Update shutdown order (reverse of startup)
    this.shutdownOrder = [...this.startupOrder].reverse();
  }

  /**
   * Start all services in priority order
   */
  async startServices() {
    console.log('Starting services...');

    for (const { name } of this.startupOrder) {
      const serviceConfig = this.factories.get(name);
      if (!serviceConfig) continue;

      try {
        console.log(`Starting service: ${name}`);

        // Create instance with timeout
        const instance = await this.createInstanceWithTimeout(name, serviceConfig.startupTimeout);

        // Call startup method if it exists
        if (instance && typeof instance.startup === 'function') {
          await instance.startup();
        }

        this.emit('serviceStarted', { name, instance });
        console.log(`Service '${name}' started successfully`);

      } catch (error) {
        console.error(`Failed to start service '${name}':`, error);
        this.emit('serviceStartFailed', { name, error });

        // Decide whether to continue or stop based on service criticality
        if (serviceConfig.critical !== false) {
          throw new Error(`Critical service '${name}' failed to start: ${error.message}`);
        }
      }
    }

    console.log('All services started successfully');
  }

  /**
   * Create service instance with timeout
   * @param {string} name - Service name
   * @param {number} timeout - Timeout in milliseconds
   * @returns {Promise<*>} Service instance
   */
  async createInstanceWithTimeout(name, timeout) {
    return Promise.race([
      Promise.resolve(this.createInstance(name)),
      new Promise((_, reject) => {
        setTimeout(() => reject(new Error(`Service startup timeout`)), timeout);
      })
    ]);
  }

  /**
   * Shutdown all services in reverse order
   */
  async shutdown() {
    if (this.isShuttingDown) {
      return;
    }

    console.log('Shutting down services...');
    this.isShuttingDown = true;

    for (const { name } of this.shutdownOrder) {
      try {
        await this.shutdownService(name);
      } catch (error) {
        console.error(`Error shutting down service '${name}':`, error);
      }
    }

    // Stop circuit breakers
    for (const [name, breaker] of this.circuitBreakers) {
      try {
        breaker.stopMonitoring();
      } catch (error) {
        console.error(`Error stopping circuit breaker for '${name}':`, error);
      }
    }

    this.services.clear();
    this.singletons.clear();
    this.circuitBreakers.clear();

    console.log('All services shut down');
    this.emit('shutdown');
  }

  /**
   * Shutdown a specific service
   * @param {string} name - Service name
   */
  async shutdownService(name) {
    const instance = this.services.get(name) || this.singletons.get(name);
    if (!instance) return;

    const serviceConfig = this.factories.get(name);
    const timeout = serviceConfig?.shutdownTimeout || 10000;

    console.log(`Shutting down service: ${name}`);

    try {
      // Call shutdown method if it exists
      if (typeof instance.shutdown === 'function') {
        await Promise.race([
          instance.shutdown(),
          new Promise((_, reject) => {
            setTimeout(() => reject(new Error('Shutdown timeout')), timeout);
          })
        ]);
      }

      this.emit('serviceShutdown', { name, instance });
      console.log(`Service '${name}' shut down successfully`);

    } catch (error) {
      console.error(`Error during shutdown of service '${name}':`, error);
      this.emit('serviceShutdownError', { name, error });
    }

    // Remove from containers
    this.services.delete(name);
    this.singletons.delete(name);
  }

  /**
   * Get health status of all services
   */
  async getHealthStatus() {
    const healthStatus = {
      status: 'healthy',
      services: {},
      circuitBreakers: {},
      summary: {
        total: 0,
        healthy: 0,
        unhealthy: 0,
        unknown: 0
      }
    };

    // Check service health
    for (const [name, serviceConfig] of this.factories) {
      const instance = this.services.get(name) || this.singletons.get(name);

      if (!instance) {
        healthStatus.services[name] = { status: 'not_started' };
        healthStatus.summary.unknown++;
        continue;
      }

      healthStatus.summary.total++;

      try {
        let serviceHealth = { status: 'healthy' };

        // Use custom health check if available
        if (serviceConfig.healthCheck) {
          serviceHealth = await serviceConfig.healthCheck(instance);
        } else if (typeof instance.getHealthStatus === 'function') {
          serviceHealth = await instance.getHealthStatus();
        } else if (typeof instance.healthCheck === 'function') {
          serviceHealth = await instance.healthCheck();
        }

        healthStatus.services[name] = serviceHealth;

        if (serviceHealth.status === 'healthy') {
          healthStatus.summary.healthy++;
        } else {
          healthStatus.summary.unhealthy++;
        }

      } catch (error) {
        healthStatus.services[name] = {
          status: 'unhealthy',
          error: error.message
        };
        healthStatus.summary.unhealthy++;
      }
    }

    // Check circuit breaker status
    for (const [name, breaker] of this.circuitBreakers) {
      healthStatus.circuitBreakers[name] = breaker.getStatus();
    }

    // Determine overall status
    if (healthStatus.summary.unhealthy > 0) {
      healthStatus.status = 'unhealthy';
    } else if (healthStatus.summary.unknown > 0) {
      healthStatus.status = 'degraded';
    }

    return healthStatus;
  }

  /**
   * Get service statistics
   */
  getStats() {
    return {
      registered: this.factories.size,
      active: this.services.size,
      singletons: this.singletons.size,
      circuitBreakers: this.circuitBreakers.size,
      startupOrder: this.startupOrder.map(item => item.name),
      isShuttingDown: this.isShuttingDown
    };
  }

  /**
   * List all registered services
   */
  listServices() {
    const services = [];

    for (const [name, config] of this.factories) {
      const isActive = this.services.has(name) || this.singletons.has(name);
      const hasCircuitBreaker = this.circuitBreakers.has(name);

      services.push({
        name,
        isActive,
        isSingleton: config.singleton,
        hasCircuitBreaker,
        dependencies: config.dependencies,
        startupPriority: config.startupPriority
      });
    }

    return services.sort((a, b) => a.startupPriority - b.startupPriority);
  }
}

// Create singleton instance
const serviceContainer = new ServiceContainer();

module.exports = serviceContainer;