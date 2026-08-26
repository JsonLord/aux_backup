const express = require('express');
const { getDatabase } = require('../database/init');
const router = express.Router();

router.get('/', async (req, res) => {
  try {
    // Get comprehensive health status from service container
    const serviceHealthStatus = await req.services.getHealthStatus();

    // Basic database check
    let databaseHealth = true;
    try {
      const db = getDatabase();
      await new Promise((resolve, reject) => {
        db.get('SELECT 1', (err) => {
          if (err) reject(err);
          else resolve();
        });
      });
    } catch (error) {
      console.error('Database health check failed:', error);
      databaseHealth = false;
    }

    // Combine service container health with basic checks
    const health = {
      status: serviceHealthStatus.status,
      services: {
        ...serviceHealthStatus.services,
        database: databaseHealth
      },
      circuitBreakers: serviceHealthStatus.circuitBreakers,
      summary: {
        ...serviceHealthStatus.summary,
        database: databaseHealth ? 'healthy' : 'unhealthy'
      },
      statistics: req.services.getStats(),
      version: '2.0.0', // Updated for robust architecture
      timestamp: new Date().toISOString(),
      architecture: 'robust_v2'
    };

    // Determine final status including database
    if (!databaseHealth && health.status === 'healthy') {
      health.status = 'degraded';
    } else if (!databaseHealth && health.status === 'degraded') {
      health.status = 'unhealthy';
    }

    const statusCode = health.status === 'healthy' ? 200 :
                      health.status === 'degraded' ? 200 : 503;

    res.status(statusCode).json(health);

  } catch (error) {
    console.error('Health check failed:', error);
    res.status(503).json({
      status: 'unhealthy',
      error: 'Health check system failure',
      message: error.message,
      timestamp: new Date().toISOString()
    });
  }
});

module.exports = router;