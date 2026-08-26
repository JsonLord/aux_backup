#!/usr/bin/env node

require('dotenv').config();
const CodeGenerationService = require('../backend/services/codeGenerationService');

async function testCodeGeneration() {
  console.log('Testing code generation service...');

  const codeGen = new CodeGenerationService({
    geminiApiKey: process.env.GEMINI_API_KEY,
    logger: console
  });

  // Test with a simple recommendation
  const testRecommendation = {
    title: "Improve Visual Hierarchy",
    description: "Add clear visual hierarchy using typography and spacing",
    priority: "High",
    impact: "High"
  };

  try {
    console.log('🔧 Testing code generation for:', testRecommendation.title);

    // Test the full bundle generation like the analysis service does
    const mockAnalysisResults = {
      ux_critique: {
        structured_critique: {
          recommendations: [testRecommendation]
        }
      }
    };

    console.log('📦 Testing full code bundle generation...');
    const bundleResult = await codeGen.generateCodeBundle(mockAnalysisResults, 'https://example.com');

    console.log('\n=== BUNDLE RESULT ===');
    console.log('Success:', bundleResult.success);

    if (bundleResult.success && bundleResult.bundle) {
      const bundle = bundleResult.bundle;
      console.log('HTML implementations:', bundle.html?.length || 0);
      console.log('CSS implementations:', bundle.css?.length || 0);
      console.log('JS implementations:', bundle.javascript?.length || 0);
      console.log('Instructions:', bundle.instructions?.length || 0);

      if (bundle.css?.length > 0) {
        console.log('\nFirst CSS implementation:');
        console.log('Title:', bundle.css[0].title);
        console.log('Code length:', bundle.css[0].code?.length || 0);
      }
    } else {
      console.log('Bundle error:', bundleResult.error);
    }

  } catch (error) {
    console.error('Test failed:', error.message);
  }
}

testCodeGeneration();