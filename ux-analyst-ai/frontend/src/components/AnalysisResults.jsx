import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import ScreenshotViewer from './ScreenshotViewer'
import CritiqueSection from './CritiqueSection'
import AccessibilitySection from './AccessibilitySection'
import RecommendationsSection from './RecommendationsSection'
import CodeImplementationSection from './CodeImplementationSection'

function AnalysisResults({ analysis }) {
  const [activeTab, setActiveTab] = useState('overview')

  const { results, screenshots } = analysis
  const report = results.final_report
  const accessibility = results.accessibility
  const uxCritique = results.ux_critique

  const tabs = [
    { id: 'overview', label: 'Overview', icon: '📊' },
    { id: 'screenshots', label: 'Screenshots', icon: '📱' },
    { id: 'ux', label: 'UX Analysis', icon: '🎨' },
    { id: 'accessibility', label: 'Accessibility', icon: '♿' },
    { id: 'recommendations', label: 'Recommendations', icon: '💡' },
    { id: 'code', label: 'Implementation Code', icon: '💻' }
  ]

  const getScoreColor = (score) => {
    if (score >= 90) return 'text-success-600'
    if (score >= 75) return 'text-warning-600'
    if (score >= 60) return 'text-warning-600'
    return 'text-error-600'
  }

  const getGradeColor = (grade) => {
    if (grade === 'Excellent') return 'bg-success-100 text-success-800'
    if (grade === 'Good') return 'bg-primary-100 text-primary-800'
    if (grade === 'Fair') return 'bg-warning-100 text-warning-800'
    return 'bg-error-100 text-error-800'
  }

  return (
    <div className="space-y-6">
      {/* Success Header */}
      <div className="card bg-gradient-to-r from-success-50 to-primary-50 border-success-200">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center mb-2">
              <div className="w-8 h-8 bg-success-500 rounded-full flex items-center justify-center mr-3">
                <svg className="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
              </div>
              <h2 className="text-2xl font-bold text-gray-900">Analysis Complete!</h2>
            </div>
            <p className="text-gray-600">
              Your website has been analyzed. Here are the results and recommendations.
            </p>
          </div>

          <div className="text-right space-x-4">
            <Link
              to={`/report/${analysis.id}`}
              className="btn btn-primary"
            >
              View Full Report
            </Link>
            <button
              onClick={() => window.open(`/api/analyze/${analysis.id}/report`, '_blank')}
              className="btn btn-secondary"
            >
              Download Report
            </button>
          </div>
        </div>
      </div>

      {/* Summary Cards */}
      {report && (
        <div className="grid md:grid-cols-4 gap-6">
          <div className="card text-center">
            <h3 className="text-sm font-medium text-gray-500 mb-2">Overall Grade</h3>
            <div className={`inline-block px-3 py-1 rounded-full text-sm font-semibold ${getGradeColor(report.summary.overallGrade)}`}>
              {report.summary.overallGrade}
            </div>
          </div>

          <div className="card text-center">
            <h3 className="text-sm font-medium text-gray-500 mb-2">UX Score</h3>
            <div className={`text-2xl font-bold ${getScoreColor(report.summary.uxScore)}`}>
              {report.summary.uxScore || 'N/A'}
              {report.summary.uxScore && <span className="text-sm">/100</span>}
            </div>
          </div>

          <div className="card text-center">
            <h3 className="text-sm font-medium text-gray-500 mb-2">Accessibility Score</h3>
            <div className={`text-2xl font-bold ${getScoreColor(report.summary.accessibilityScore)}`}>
              {report.summary.accessibilityScore || 'N/A'}
              {report.summary.accessibilityScore && <span className="text-sm">/100</span>}
            </div>
          </div>

          <div className="card text-center">
            <h3 className="text-sm font-medium text-gray-500 mb-2">Issues Found</h3>
            <div className="text-2xl font-bold text-gray-900">
              {report.summary.totalIssues}
            </div>
          </div>
        </div>
      )}

      {/* Navigation Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`
                py-4 px-1 border-b-2 font-medium text-sm whitespace-nowrap
                ${activeTab === tab.id
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }
              `}
            >
              <span className="mr-2">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="mt-6">
        {activeTab === 'overview' && (
          <div className="space-y-6">
            {/* Quick Overview */}
            <div className="card">
              <h3 className="text-xl font-semibold mb-4">Analysis Summary</h3>

              {report ? (
                <div className="grid md:grid-cols-2 gap-6">
                  <div>
                    <h4 className="font-medium text-gray-900 mb-3">Key Metrics</h4>
                    <div className="space-y-2">
                      <div className="flex justify-between">
                        <span className="text-gray-600">Overall Grade:</span>
                        <span className={`font-semibold px-2 py-1 rounded text-sm ${getGradeColor(report.summary.overallGrade)}`}>
                          {report.summary.overallGrade}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-600">UX Score:</span>
                        <span className={`font-semibold ${getScoreColor(report.summary.uxScore)}`}>
                          {report.summary.uxScore || 'N/A'}/100
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-600">Accessibility Score:</span>
                        <span className={`font-semibold ${getScoreColor(report.summary.accessibilityScore)}`}>
                          {report.summary.accessibilityScore || 'N/A'}/100
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-600">Priority Level:</span>
                        <span className={`badge ${
                          report.summary.priorityLevel === 'High' ? 'badge-error' :
                          report.summary.priorityLevel === 'Medium' ? 'badge-warning' :
                          'badge-success'
                        }`}>
                          {report.summary.priorityLevel}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div>
                    <h4 className="font-medium text-gray-900 mb-3">Analysis Details</h4>
                    <div className="space-y-2 text-sm text-gray-600">
                      <p>• Analyzed {Object.keys(screenshots).length} viewports</p>
                      <p>• Found {report.summary.totalIssues} total issues</p>
                      <p>• Completed at {new Date(analysis.completedAt).toLocaleString()}</p>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-gray-600">Loading summary...</p>
              )}
            </div>

            {/* Quick Actions */}
            <div className="grid md:grid-cols-3 gap-4">
              <button
                onClick={() => setActiveTab('ux')}
                className="card hover:bg-gray-50 transition-colors text-left"
              >
                <h4 className="font-semibold text-gray-900 mb-2">🎨 View UX Analysis</h4>
                <p className="text-sm text-gray-600">
                  Detailed feedback on design, usability, and user experience
                </p>
              </button>

              <button
                onClick={() => setActiveTab('accessibility')}
                className="card hover:bg-gray-50 transition-colors text-left"
              >
                <h4 className="font-semibold text-gray-900 mb-2">♿ Check Accessibility</h4>
                <p className="text-sm text-gray-600">
                  WCAG compliance issues and accessibility improvements
                </p>
              </button>

              <button
                onClick={() => setActiveTab('recommendations')}
                className="card hover:bg-gray-50 transition-colors text-left"
              >
                <h4 className="font-semibold text-gray-900 mb-2">💡 View Recommendations</h4>
                <p className="text-sm text-gray-600">
                  Prioritized action items to improve your website
                </p>
              </button>
            </div>
          </div>
        )}

        {activeTab === 'screenshots' && (
          <ScreenshotViewer screenshots={screenshots} url={analysis.url} />
        )}

        {activeTab === 'ux' && (
          <CritiqueSection critique={uxCritique} />
        )}

        {activeTab === 'accessibility' && (
          <AccessibilitySection accessibility={accessibility} />
        )}

        {activeTab === 'recommendations' && (
          <RecommendationsSection
            uxCritique={uxCritique}
            accessibility={accessibility}
            report={report}
          />
        )}

        {activeTab === 'code' && (
          <CodeImplementationSection analysisId={analysis.id} />
        )}
      </div>
    </div>
  )
}

export default AnalysisResults