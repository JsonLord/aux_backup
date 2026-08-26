import React from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getAnalysisResult } from '../api/analysis'

function ReportPage() {
  const { id } = useParams()

  const { data: analysis, isLoading, isError, error } = useQuery({
    queryKey: ['analysis', id],
    queryFn: () => getAnalysisResult(id),
    enabled: !!id
  })

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="card text-center">
          <div className="animate-spin w-8 h-8 border-2 border-primary-600 border-t-transparent rounded-full mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Loading Report...</h2>
          <p className="text-gray-600">Please wait while we prepare your report.</p>
        </div>
      </div>
    )
  }

  if (isError || !analysis) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="card text-center">
          <div className="w-16 h-16 bg-error-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-error-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-error-900 mb-2">Report Not Found</h2>
          <p className="text-gray-600 mb-4">
            {error?.message || 'The report you\'re looking for could not be found.'}
          </p>
          <Link to="/" className="btn btn-primary">
            Start New Analysis
          </Link>
        </div>
      </div>
    )
  }

  if (analysis.status !== 'completed') {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="card text-center">
          <div className="w-16 h-16 bg-warning-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-warning-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-warning-900 mb-2">Analysis Not Complete</h2>
          <p className="text-gray-600 mb-4">
            The analysis is still in progress. Please wait for it to complete before viewing the report.
          </p>
          <div className="space-x-4">
            <Link to={`/analysis/${id}`} className="btn btn-primary">
              View Analysis Progress
            </Link>
            <Link to="/" className="btn btn-secondary">
              Start New Analysis
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const { results } = analysis
  const report = results.final_report
  const accessibility = results.accessibility
  const uxCritique = results.ux_critique

  const getScoreColor = (score) => {
    if (score >= 90) return 'text-success-600'
    if (score >= 75) return 'text-primary-600'
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
    <div className="max-w-4xl mx-auto print:max-w-full">
      {/* Header - Hidden when printing */}
      <div className="mb-8 print:hidden">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-3xl font-bold text-gray-900">UX Analysis Report</h1>
          <div className="space-x-4">
            <button
              onClick={() => window.print()}
              className="btn btn-secondary"
            >
              Print Report
            </button>
            <button
              onClick={() => window.open(`/api/analyze/${analysis.id}/report`, '_blank')}
              className="btn btn-primary"
            >
              Download HTML
            </button>
          </div>
        </div>
        <div className="text-sm text-gray-600">
          <Link to={`/analysis/${id}`} className="text-primary-600 hover:text-primary-700">
            ← Back to Analysis
          </Link>
        </div>
      </div>

      {/* Report Content */}
      <div className="space-y-8 print:space-y-6">
        {/* Executive Summary */}
        <div className="card">
          <div className="border-b border-gray-200 pb-4 mb-6">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Executive Summary</h2>
            <p className="text-gray-600">Website: {analysis.url}</p>
            <p className="text-gray-600">Generated: {new Date(analysis.createdAt).toLocaleString()}</p>
          </div>

          {report && (
            <div className="grid md:grid-cols-2 gap-8">
              <div>
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Overall Assessment</h3>
                <div className="space-y-3">
                  <div className="flex justify-between items-center">
                    <span className="text-gray-700">Overall Grade:</span>
                    <span className={`px-3 py-1 rounded-full text-sm font-semibold ${getGradeColor(report.summary.overallGrade)}`}>
                      {report.summary.overallGrade}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-gray-700">UX Score:</span>
                    <span className={`text-xl font-bold ${getScoreColor(report.summary.uxScore)}`}>
                      {report.summary.uxScore || 'N/A'}/100
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-gray-700">Accessibility Score:</span>
                    <span className={`text-xl font-bold ${getScoreColor(report.summary.accessibilityScore)}`}>
                      {report.summary.accessibilityScore || 'N/A'}/100
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-gray-700">Issues Found:</span>
                    <span className="text-xl font-bold text-gray-900">
                      {report.summary.totalIssues}
                    </span>
                  </div>
                </div>
              </div>

              <div>
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Key Findings</h3>
                <div className="space-y-3">
                  <div>
                    <h4 className="font-medium text-success-700 mb-1">✅ Strengths</h4>
                    <ul className="text-sm text-gray-700 space-y-1">
                      {uxCritique?.structured_critique?.overall_assessment?.strengths?.slice(0, 3).map((strength, index) => (
                        <li key={index}>• {strength}</li>
                      )) || <li>• Analysis completed successfully</li>}
                    </ul>
                  </div>
                  <div>
                    <h4 className="font-medium text-error-700 mb-1">⚠️ Areas for Improvement</h4>
                    <ul className="text-sm text-gray-700 space-y-1">
                      {uxCritique?.structured_critique?.overall_assessment?.weaknesses?.slice(0, 3).map((weakness, index) => (
                        <li key={index}>• {weakness}</li>
                      )) || <li>• Check detailed analysis for specific recommendations</li>}
                    </ul>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* UX Analysis Summary */}
        {uxCritique && (
          <div className="card">
            <h2 className="text-2xl font-bold text-gray-900 mb-6">UX Analysis</h2>

            {uxCritique.structured_critique ? (
              <div className="space-y-6">
                <div className="grid md:grid-cols-5 gap-4">
                  {[
                    { key: 'visual_design', label: 'Visual Design', data: uxCritique.structured_critique.visual_design },
                    { key: 'usability', label: 'Usability', data: uxCritique.structured_critique.usability },
                    { key: 'accessibility', label: 'UX Accessibility', data: uxCritique.structured_critique.accessibility },
                    { key: 'mobile_responsiveness', label: 'Mobile UX', data: uxCritique.structured_critique.mobile_responsiveness },
                    { key: 'performance', label: 'Performance UX', data: uxCritique.structured_critique.performance }
                  ].map(section => (
                    <div key={section.key} className="text-center">
                      <div className={`text-2xl font-bold ${getScoreColor(section.data?.score || 0)}`}>
                        {section.data?.score || 'N/A'}
                      </div>
                      <p className="text-sm text-gray-600">{section.label}</p>
                    </div>
                  ))}
                </div>

                <div>
                  <h3 className="text-lg font-semibold text-gray-900 mb-3">Overall Assessment</h3>
                  <p className="text-gray-700">
                    {uxCritique.structured_critique.overall_assessment?.summary}
                  </p>
                </div>
              </div>
            ) : (
              <div>
                <h3 className="text-lg font-semibold text-gray-900 mb-3">Quick Assessment</h3>
                <div className="prose prose-gray max-w-none">
                  <div className="whitespace-pre-line text-gray-700">
                    {uxCritique.quick_critique}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Accessibility Summary */}
        {accessibility && (
          <div className="card">
            <h2 className="text-2xl font-bold text-gray-900 mb-6">Accessibility Analysis</h2>

            <div className="grid md:grid-cols-4 gap-6 mb-6">
              <div className="text-center">
                <div className={`text-3xl font-bold ${getScoreColor(accessibility.summary.score)}`}>
                  {accessibility.summary.score}/100
                </div>
                <p className="text-gray-600 text-sm">Accessibility Score</p>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-error-600">
                  {accessibility.summary.totalViolations}
                </div>
                <p className="text-gray-600 text-sm">Violations</p>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-success-600">
                  {accessibility.summary.totalPasses}
                </div>
                <p className="text-gray-600 text-sm">Passed Tests</p>
              </div>
              <div className="text-center">
                <div className="text-3xl font-bold text-warning-600">
                  {accessibility.summary.totalIncomplete}
                </div>
                <p className="text-gray-600 text-sm">Manual Review</p>
              </div>
            </div>

            {accessibility.violations && accessibility.violations.length > 0 && (
              <div>
                <h3 className="text-lg font-semibold text-gray-900 mb-3">Top Accessibility Issues</h3>
                <div className="space-y-3">
                  {accessibility.violations.slice(0, 5).map((violation, index) => (
                    <div key={index} className="flex justify-between items-center py-2 border-b border-gray-100">
                      <div>
                        <p className="font-medium text-gray-900">{violation.help}</p>
                        <p className="text-sm text-gray-600">{violation.description}</p>
                      </div>
                      <div className="text-right">
                        <span className={`badge ${
                          violation.impact === 'critical' ? 'badge-error' :
                          violation.impact === 'serious' ? 'badge-error' :
                          violation.impact === 'moderate' ? 'badge-warning' :
                          'badge-info'
                        }`}>
                          {violation.impact}
                        </span>
                        <p className="text-xs text-gray-500 mt-1">
                          {violation.nodes?.length || 0} elements
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Top Recommendations */}
        <div className="card">
          <h2 className="text-2xl font-bold text-gray-900 mb-6">Priority Recommendations</h2>

          <div className="space-y-4">
            {/* UX Recommendations */}
            {uxCritique?.structured_critique?.recommendations?.slice(0, 3).map((rec, index) => (
              <div key={index} className="border border-gray-200 rounded-lg p-4">
                <div className="flex justify-between items-start mb-2">
                  <h3 className="font-semibold text-gray-900">{rec.title}</h3>
                  <span className={`badge ${
                    rec.priority === 'High' ? 'badge-error' :
                    rec.priority === 'Medium' ? 'badge-warning' :
                    'badge-success'
                  }`}>
                    {rec.priority}
                  </span>
                </div>
                <p className="text-gray-700 mb-2">{rec.description}</p>
                <div className="text-sm text-gray-600">
                  <strong>Expected Impact:</strong> {rec.impact}
                </div>
              </div>
            )) || <p className="text-gray-600">No specific UX recommendations available.</p>}

            {/* Accessibility Recommendations */}
            {accessibility?.violations?.filter(v => v.impact === 'critical' || v.impact === 'serious')
              .slice(0, 2).map((violation, index) => (
              <div key={`a11y-${index}`} className="border border-gray-200 rounded-lg p-4">
                <div className="flex justify-between items-start mb-2">
                  <h3 className="font-semibold text-gray-900">♿ {violation.help}</h3>
                  <span className={`badge ${violation.impact === 'critical' ? 'badge-error' : 'badge-warning'}`}>
                    {violation.impact}
                  </span>
                </div>
                <p className="text-gray-700 mb-2">{violation.description}</p>
                <div className="text-sm text-gray-600">
                  <strong>Affects:</strong> {violation.nodes?.length || 0} elements
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="card text-center bg-gray-50">
          <p className="text-gray-600 mb-2">
            Report generated by UX Analyst AI on {new Date(analysis.completedAt).toLocaleString()}
          </p>
          <p className="text-sm text-gray-500">
            For detailed analysis and interactive features, visit the full analysis page.
          </p>
          <div className="mt-4 print:hidden">
            <Link
              to={`/analysis/${id}`}
              className="btn btn-primary"
            >
              View Interactive Analysis
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

export default ReportPage