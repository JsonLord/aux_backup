class CircuitBreaker {
  constructor(options = {}) {
    this.name = options.name || 'CircuitBreaker';
    this.failureThreshold = options.failureThreshold || 5;
    this.recoveryTimeout = options.recoveryTimeout || 60000; // 1 minute
    this.monitoringPeriod = options.monitoringPeriod || 60000; // 1 minute
    this.expectedErrors = options.expectedErrors || [];
    this.onStateChange = options.onStateChange || (() => {});
    this.onFailure = options.onFailure || (() => {});
    this.onSuccess = options.onSuccess || (() => {});

    // Circuit breaker states
    this.states = {
      CLOSED: 'CLOSED',     // Normal operation
      OPEN: 'OPEN',         // Circuit is open, failing fast
      HALF_OPEN: 'HALF_OPEN' // Testing if service has recovered
    };

    this.state = this.states.CLOSED;
    this.failureCount = 0;
    this.successCount = 0;
    this.lastFailureTime = null;
    this.nextAttemptTime = null;
    this.monitoring = {
      totalRequests: 0,
      successfulRequests: 0,
      failedRequests: 0,
      averageResponseTime: 0,
      lastResetTime: Date.now()
    };

    // Start monitoring
    this.startMonitoring();
  }

  /**
   * Execute a function with circuit breaker protection
   */
  async execute(fn, ...args) {
    const startTime = Date.now();
    this.monitoring.totalRequests++;

    // Check if circuit is open
    if (this.state === this.states.OPEN) {
      if (this.canAttemptReset()) {
        this.setState(this.states.HALF_OPEN);
      } else {
        const error = new Error(`Circuit breaker '${this.name}' is OPEN. Failing fast.`);
        error.isCircuitBreakerError = true;
        this.recordFailure(error);
        throw error;
      }
    }

    try {
      const result = await fn(...args);
      this.recordSuccess(Date.now() - startTime);
      return result;

    } catch (error) {
      this.recordFailure(error, Date.now() - startTime);
      throw error;
    }
  }

  /**
   * Record a successful execution
   */
  recordSuccess(responseTime = 0) {
    this.successCount++;
    this.monitoring.successfulRequests++;
    this.updateAverageResponseTime(responseTime);

    if (this.state === this.states.HALF_OPEN) {
      // Success in half-open state closes the circuit
      this.setState(this.states.CLOSED);
      this.failureCount = 0;
    }

    this.onSuccess({
      name: this.name,
      state: this.state,
      successCount: this.successCount,
      failureCount: this.failureCount,
      responseTime
    });
  }

  /**
   * Record a failed execution
   */
  recordFailure(error, responseTime = 0) {
    this.failureCount++;
    this.lastFailureTime = Date.now();
    this.monitoring.failedRequests++;
    this.updateAverageResponseTime(responseTime);

    // Check if this is an expected error that shouldn't count towards failures
    if (this.isExpectedError(error)) {
      return;
    }

    // Transition to OPEN state if failure threshold is reached
    if (this.failureCount >= this.failureThreshold) {
      this.setState(this.states.OPEN);
      this.nextAttemptTime = Date.now() + this.recoveryTimeout;
    }

    this.onFailure({
      name: this.name,
      state: this.state,
      successCount: this.successCount,
      failureCount: this.failureCount,
      error: error.message,
      responseTime
    });
  }

  /**
   * Check if error is expected and shouldn't trigger circuit breaker
   */
  isExpectedError(error) {
    return this.expectedErrors.some(expectedError => {
      if (typeof expectedError === 'string') {
        return error.message.includes(expectedError);
      }
      if (expectedError instanceof RegExp) {
        return expectedError.test(error.message);
      }
      if (typeof expectedError === 'function') {
        return expectedError(error);
      }
      return false;
    });
  }

  /**
   * Check if we can attempt to reset the circuit breaker
   */
  canAttemptReset() {
    return this.nextAttemptTime && Date.now() >= this.nextAttemptTime;
  }

  /**
   * Manually close the circuit breaker
   */
  close() {
    this.setState(this.states.CLOSED);
    this.failureCount = 0;
    this.successCount = 0;
    this.lastFailureTime = null;
    this.nextAttemptTime = null;
  }

  /**
   * Manually open the circuit breaker
   */
  open() {
    this.setState(this.states.OPEN);
    this.nextAttemptTime = Date.now() + this.recoveryTimeout;
  }

  /**
   * Force the circuit breaker into half-open state
   */
  halfOpen() {
    this.setState(this.states.HALF_OPEN);
  }

  /**
   * Set the circuit breaker state
   */
  setState(newState) {
    const oldState = this.state;
    this.state = newState;

    if (oldState !== newState) {
      console.log(`Circuit breaker '${this.name}' state changed: ${oldState} -> ${newState}`);
      this.onStateChange({
        name: this.name,
        oldState,
        newState,
        failureCount: this.failureCount,
        successCount: this.successCount,
        timestamp: new Date().toISOString()
      });
    }
  }

  /**
   * Update average response time
   */
  updateAverageResponseTime(responseTime) {
    const totalRequests = this.monitoring.totalRequests;
    const currentAverage = this.monitoring.averageResponseTime;
    this.monitoring.averageResponseTime =
      ((currentAverage * (totalRequests - 1)) + responseTime) / totalRequests;
  }

  /**
   * Get current circuit breaker status
   */
  getStatus() {
    return {
      name: this.name,
      state: this.state,
      failureCount: this.failureCount,
      successCount: this.successCount,
      failureThreshold: this.failureThreshold,
      nextAttemptTime: this.nextAttemptTime,
      lastFailureTime: this.lastFailureTime,
      monitoring: {
        ...this.monitoring,
        uptime: Date.now() - this.monitoring.lastResetTime,
        successRate: this.monitoring.totalRequests > 0
          ? (this.monitoring.successfulRequests / this.monitoring.totalRequests) * 100
          : 0,
        failureRate: this.monitoring.totalRequests > 0
          ? (this.monitoring.failedRequests / this.monitoring.totalRequests) * 100
          : 0
      }
    };
  }

  /**
   * Check if circuit breaker is healthy
   */
  isHealthy() {
    const status = this.getStatus();
    return status.state !== this.states.OPEN && status.monitoring.failureRate < 50;
  }

  /**
   * Reset monitoring statistics
   */
  resetStats() {
    this.monitoring = {
      totalRequests: 0,
      successfulRequests: 0,
      failedRequests: 0,
      averageResponseTime: 0,
      lastResetTime: Date.now()
    };
  }

  /**
   * Start monitoring and periodic reset
   */
  startMonitoring() {
    this.monitoringInterval = setInterval(() => {
      const status = this.getStatus();

      // Log status if there's activity
      if (status.monitoring.totalRequests > 0) {
        console.log(`Circuit breaker '${this.name}' stats:`, {
          state: status.state,
          requests: status.monitoring.totalRequests,
          successRate: Math.round(status.monitoring.successRate * 100) / 100,
          avgResponseTime: Math.round(status.monitoring.averageResponseTime)
        });
      }

      // Reset monitoring stats periodically
      this.resetStats();
    }, this.monitoringPeriod);
  }

  /**
   * Stop monitoring
   */
  stopMonitoring() {
    if (this.monitoringInterval) {
      clearInterval(this.monitoringInterval);
      this.monitoringInterval = null;
    }
  }

  /**
   * Create a circuit breaker wrapper for a function
   */
  static wrap(fn, options = {}) {
    const circuitBreaker = new CircuitBreaker(options);

    return async function(...args) {
      return circuitBreaker.execute(fn, ...args);
    };
  }

  /**
   * Create a circuit breaker for HTTP requests
   */
  static forHttp(options = {}) {
    const defaultOptions = {
      name: 'HTTP',
      failureThreshold: 5,
      recoveryTimeout: 30000,
      expectedErrors: [
        'ECONNREFUSED',
        'ENOTFOUND',
        'ETIMEDOUT',
        'Network Error'
      ],
      ...options
    };

    return new CircuitBreaker(defaultOptions);
  }

  /**
   * Create a circuit breaker for database operations
   */
  static forDatabase(options = {}) {
    const defaultOptions = {
      name: 'Database',
      failureThreshold: 3,
      recoveryTimeout: 60000,
      expectedErrors: [
        'connection refused',
        'timeout',
        'database is locked'
      ],
      ...options
    };

    return new CircuitBreaker(defaultOptions);
  }

  /**
   * Create a circuit breaker for external APIs
   */
  static forAPI(apiName, options = {}) {
    const defaultOptions = {
      name: apiName || 'ExternalAPI',
      failureThreshold: 5,
      recoveryTimeout: 60000,
      expectedErrors: [
        'rate limit',
        '429',
        '503',
        'timeout',
        'overloaded'
      ],
      ...options
    };

    return new CircuitBreaker(defaultOptions);
  }
}

module.exports = CircuitBreaker;