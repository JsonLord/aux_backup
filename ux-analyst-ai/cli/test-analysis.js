#!/usr/bin/env node

const path = require('path');
require('dotenv').config();

// Simple test to see what's happening with the analysis
async function testAnalysis() {
  console.log('Testing analysis pipeline...');

  // Check if Gemini API key is available
  const apiKey = process.env.GEMINI_API_KEY;
  console.log(`API Key: ${apiKey ? 'Present' : 'Missing'}`);

  if (!apiKey) {
    console.log('❌ No Gemini API key found. Set GEMINI_API_KEY environment variable.');
    return;
  }

  try {
    // Test basic UXAnalyzer initialization
    const UXAnalyzer = require('./lib/UXAnalyzer');

    const config = {
      ai: {
        geminiApiKey: apiKey,
        gemini: {
          apiKey: apiKey,
          model: "gemini-1.5-flash"
        }
      },
      database: {
        type: "sqlite",
        path: "./data/analysis.db"
      },
      screenshots: {
        storagePath: "./data/screenshots",
        viewports: {
          desktop: { width: 1920, height: 1080 }
        },
        timeoutMs: 60000,
        waitForMs: 5000
      },
      browser: {
        poolSize: 1,
        headless: "new",
        launchArgs: ["--no-sandbox", "--disable-setuid-sandbox"]
      },
      analysis: {
        maxConcurrentAnalyses: 1,
        timeoutMs: 120000
      }
    };

    console.log('✓ Creating UXAnalyzer...');
    const analyzer = new UXAnalyzer(config);

    console.log('✓ Starting analysis...');
    const result = await analyzer.analyze('https://example.com', {
      viewports: ['desktop'],
      analysisType: 'quick',
      includeCodeGeneration: true,
      includeAccessibility: false
    });

    console.log('\n=== ANALYSIS RESULT ===');
    console.log('Status:', result.status);
    console.log('Screenshots:', result.screenshots?.length || 0);
    console.log('Implementation code:', result.implementationCode ? 'Yes' : 'No');
    console.log('Report:', result.report ? 'Yes' : 'No');

    if (result.screenshots?.length > 0) {
      console.log('Screenshot files:');
      result.screenshots.forEach((s, i) => {
        console.log(`  ${i}: ${s.filepath} (exists: ${require('fs').existsSync(s.filepath)})`);
      });
    }

    await analyzer.cleanup();
    console.log('✅ Test completed');

  } catch (error) {
    console.error('❌ Test failed:', error.message);
    console.error(error.stack);
  }
}

testAnalysis();