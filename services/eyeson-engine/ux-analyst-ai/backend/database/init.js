const sqlite3 = require('sqlite3').verbose();
const path = require('path');
const fs = require('fs').promises;

const DB_PATH = process.env.DATABASE_URL?.replace('sqlite:', '') || './data/uxanalyst.db';

let db = null;

function getDatabase() {
  if (!db) {
    throw new Error('Database not initialized');
  }
  return db;
}

async function initializeDatabase() {
  try {
    // Ensure data directory exists
    const dbDir = path.dirname(DB_PATH);
    await fs.mkdir(dbDir, { recursive: true });

    return new Promise((resolve, reject) => {
      db = new sqlite3.Database(DB_PATH, (err) => {
        if (err) {
          reject(err);
          return;
        }

        console.log('Connected to SQLite database');
        createTables()
          .then(() => resolve())
          .catch(reject);
      });
    });
  } catch (error) {
    console.error('Database initialization error:', error);
    throw error;
  }
}

function createTables() {
  return new Promise((resolve, reject) => {
    const schema = `
      -- Analysis tracking
      CREATE TABLE IF NOT EXISTS analyses (
        id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'processing',
        progress INTEGER DEFAULT 0,
        stage TEXT DEFAULT 'validating',
        options TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME,
        error_message TEXT
      );

      -- Screenshot storage metadata
      CREATE TABLE IF NOT EXISTS screenshots (
        id TEXT PRIMARY KEY,
        analysis_id TEXT NOT NULL,
        viewport TEXT NOT NULL,
        file_path TEXT NOT NULL,
        width INTEGER,
        height INTEGER,
        file_size INTEGER,
        FOREIGN KEY (analysis_id) REFERENCES analyses (id)
      );

      -- Analysis results
      CREATE TABLE IF NOT EXISTS analysis_results (
        id TEXT PRIMARY KEY,
        analysis_id TEXT NOT NULL,
        result_type TEXT NOT NULL,
        result_data TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (analysis_id) REFERENCES analyses (id)
      );

      -- Usage tracking for analytics
      CREATE TABLE IF NOT EXISTS usage_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        analysis_id TEXT NOT NULL,
        url_domain TEXT,
        analysis_duration INTEGER,
        viewports_analyzed INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (analysis_id) REFERENCES analyses (id)
      );
    `;

    db.exec(schema, (err) => {
      if (err) {
        reject(err);
      } else {
        console.log('Database tables created successfully');
        resolve();
      }
    });
  });
}

module.exports = {
  initializeDatabase,
  getDatabase
};