import React from 'react'
import AnalysisForm from '../components/AnalysisForm'

function HomePage() {
  return (
    <div className="max-w-4xl mx-auto">
      {/* Hero Section */}
      <div className="text-center mb-12">
        <h1 className="text-4xl md:text-5xl font-bold text-gray-900 mb-6">
          Get Instant UX Analysis with AI
        </h1>
        <p className="text-xl text-gray-600 mb-8 max-w-3xl mx-auto">
          Analyze any website's user experience with expert-level feedback powered by AI.
          Get accessibility insights, design critiques, and actionable recommendations in minutes.
        </p>
      </div>

      {/* Analysis Form */}
      <div className="mb-16">
        <AnalysisForm />
      </div>

      {/* Features Section */}
      <section id="features" className="mb-16">
        <h2 className="text-3xl font-bold text-center text-gray-900 mb-12">
          Comprehensive UX Analysis
        </h2>

        <div className="grid md:grid-cols-3 gap-8">
          <div className="card text-center">
            <div className="w-12 h-12 bg-primary-100 rounded-lg flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6 text-primary-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h3 className="text-xl font-semibold mb-3">Accessibility Analysis</h3>
            <p className="text-gray-600">
              Comprehensive WCAG compliance checking with detailed violation reports and fix recommendations.
            </p>
          </div>

          <div className="card text-center">
            <div className="w-12 h-12 bg-success-100 rounded-lg flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6 text-success-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
            </div>
            <h3 className="text-xl font-semibold mb-3">Visual Design Review</h3>
            <p className="text-gray-600">
              AI-powered analysis of typography, color, layout, and visual hierarchy with expert insights.
            </p>
          </div>

          <div className="card text-center">
            <div className="w-12 h-12 bg-warning-100 rounded-lg flex items-center justify-center mx-auto mb-4">
              <svg className="w-6 h-6 text-warning-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" />
              </svg>
            </div>
            <h3 className="text-xl font-semibold mb-3">Multi-Device Testing</h3>
            <p className="text-gray-600">
              Analyze your site across desktop, tablet, and mobile viewports for responsive design issues.
            </p>
          </div>
        </div>
      </section>

      {/* How it Works */}
      <section id="how-it-works" className="mb-16">
        <h2 className="text-3xl font-bold text-center text-gray-900 mb-12">
          How It Works
        </h2>

        <div className="grid md:grid-cols-4 gap-8">
          <div className="text-center">
            <div className="w-12 h-12 bg-primary-600 text-white rounded-full flex items-center justify-center mx-auto mb-4 font-bold">
              1
            </div>
            <h3 className="font-semibold mb-2">Enter URL</h3>
            <p className="text-gray-600 text-sm">
              Simply paste your website URL to start the analysis
            </p>
          </div>

          <div className="text-center">
            <div className="w-12 h-12 bg-primary-600 text-white rounded-full flex items-center justify-center mx-auto mb-4 font-bold">
              2
            </div>
            <h3 className="font-semibold mb-2">AI Analysis</h3>
            <p className="text-gray-600 text-sm">
              Our AI captures screenshots and analyzes UX patterns
            </p>
          </div>

          <div className="text-center">
            <div className="w-12 h-12 bg-primary-600 text-white rounded-full flex items-center justify-center mx-auto mb-4 font-bold">
              3
            </div>
            <h3 className="font-semibold mb-2">Expert Critique</h3>
            <p className="text-gray-600 text-sm">
              Get detailed feedback from AI trained on UX best practices
            </p>
          </div>

          <div className="text-center">
            <div className="w-12 h-12 bg-primary-600 text-white rounded-full flex items-center justify-center mx-auto mb-4 font-bold">
              4
            </div>
            <h3 className="font-semibold mb-2">Actionable Report</h3>
            <p className="text-gray-600 text-sm">
              Receive prioritized recommendations to improve your UX
            </p>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="text-center bg-gradient-to-r from-primary-600 to-primary-700 rounded-xl p-12 text-white">
        <h2 className="text-3xl font-bold mb-4">
          Ready to Improve Your UX?
        </h2>
        <p className="text-xl mb-8 text-primary-100">
          Get started with a free analysis of your website today.
        </p>
        <button
          onClick={() => document.getElementById('url-input')?.focus()}
          className="bg-white text-primary-600 px-8 py-3 rounded-lg font-semibold hover:bg-gray-100 transition-colors"
        >
          Start Free Analysis
        </button>
      </section>
    </div>
  )
}

export default HomePage