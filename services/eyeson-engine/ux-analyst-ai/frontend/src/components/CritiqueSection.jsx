import React, { useState } from 'react'

function CritiqueSection({ critique }) {
  const [expandedSections, setExpandedSections] = useState({})

  if (!critique) {
    return (
      <div className="card">
        <p className="text-gray-600">UX critique data not available</p>
      </div>
    )
  }

  const toggleSection = (sectionKey) => {
    setExpandedSections(prev => ({
      ...prev,
      [sectionKey]: !prev[sectionKey]
    }))
  }

  const getScoreColor = (score) => {
    if (score >= 90) return 'text-success-600'
    if (score >= 75) return 'text-primary-600'
    if (score >= 60) return 'text-warning-600'
    return 'text-error-600'
  }

  const getSeverityColor = (severity) => {
    if (severity === 'High') return 'badge-error'
    if (severity === 'Medium') return 'badge-warning'
    return 'badge-success'
  }

  // Handle both structured and quick critique formats
  if (critique.quick_critique) {
    return (
      <div className="card">
        <h3 className="text-xl font-semibold mb-4">Quick UX Assessment</h3>
        <div className="prose prose-gray max-w-none">
          <div className="whitespace-pre-line text-gray-700">
            {critique.quick_critique}
          </div>
        </div>
      </div>
    )
  }

  const structuredCritique = critique.structured_critique

  if (!structuredCritique) {
    return (
      <div className="card">
        <h3 className="text-xl font-semibold mb-4">UX Analysis</h3>
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <p className="text-yellow-800">
            The AI critique is available but couldn't be parsed into structured format.
          </p>
          {critique.raw_response && (
            <details className="mt-4">
              <summary className="cursor-pointer font-medium">View Raw Response</summary>
              <div className="mt-2 text-sm whitespace-pre-line text-gray-700">
                {critique.raw_response}
              </div>
            </details>
          )}
        </div>
      </div>
    )
  }

  const sections = [
    { key: 'visual_design', title: '🎨 Visual Design', data: structuredCritique.visual_design },
    { key: 'usability', title: '🖱️ Usability', data: structuredCritique.usability },
    { key: 'accessibility', title: '♿ Accessibility', data: structuredCritique.accessibility },
    { key: 'mobile_responsiveness', title: '📱 Mobile Responsiveness', data: structuredCritique.mobile_responsiveness },
    { key: 'performance', title: '⚡ Performance', data: structuredCritique.performance }
  ]

  return (
    <div className="space-y-6">
      {/* Overall Assessment */}
      {structuredCritique.overall_assessment && (
        <div className="card">
          <h3 className="text-xl font-semibold mb-4">Overall Assessment</h3>

          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <div className="text-center mb-4">
                <div className={`text-4xl font-bold ${getScoreColor(structuredCritique.overall_assessment.score)}`}>
                  {structuredCritique.overall_assessment.score}
                  <span className="text-lg text-gray-500">/100</span>
                </div>
                <p className="text-gray-600 mt-2">Overall UX Score</p>
              </div>

              <div className="text-sm text-gray-700">
                {structuredCritique.overall_assessment.summary}
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <h4 className="font-semibold text-success-700 mb-2">✅ Strengths</h4>
                <ul className="space-y-1">
                  {structuredCritique.overall_assessment.strengths?.map((strength, index) => (
                    <li key={index} className="text-sm text-gray-700 flex items-start">
                      <span className="text-success-500 mr-2">•</span>
                      {strength}
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <h4 className="font-semibold text-error-700 mb-2">⚠️ Areas for Improvement</h4>
                <ul className="space-y-1">
                  {structuredCritique.overall_assessment.weaknesses?.map((weakness, index) => (
                    <li key={index} className="text-sm text-gray-700 flex items-start">
                      <span className="text-error-500 mr-2">•</span>
                      {weakness}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Detailed Sections */}
      {sections.map(section => {
        if (!section.data) return null

        const isExpanded = expandedSections[section.key]

        return (
          <div key={section.key} className="card">
            <button
              onClick={() => toggleSection(section.key)}
              className="w-full flex items-center justify-between text-left"
            >
              <h3 className="text-xl font-semibold">{section.title}</h3>
              <div className="flex items-center space-x-3">
                <div className={`text-2xl font-bold ${getScoreColor(section.data.score)}`}>
                  {section.data.score}
                  <span className="text-sm text-gray-500">/100</span>
                </div>
                <svg
                  className={`w-5 h-5 text-gray-400 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
            </button>

            {isExpanded && (
              <div className="mt-6 space-y-4">
                {/* Feedback */}
                <div>
                  <h4 className="font-semibold text-gray-900 mb-2">Feedback</h4>
                  <p className="text-gray-700">{section.data.feedback}</p>
                </div>

                {/* Issues */}
                {section.data.issues && section.data.issues.length > 0 && (
                  <div>
                    <h4 className="font-semibold text-gray-900 mb-3">Issues Found</h4>
                    <div className="space-y-3">
                      {section.data.issues.map((issue, index) => (
                        <div key={index} className="border border-gray-200 rounded-lg p-4">
                          <div className="flex items-start justify-between mb-2">
                            <h5 className="font-medium text-gray-900">{issue.category}</h5>
                            <span className={`badge ${getSeverityColor(issue.severity)}`}>
                              {issue.severity}
                            </span>
                          </div>
                          <p className="text-gray-700 mb-3">{issue.description}</p>
                          <div className="bg-blue-50 border border-blue-200 rounded p-3">
                            <h6 className="font-medium text-blue-900 mb-1">💡 Recommendation</h6>
                            <p className="text-blue-800 text-sm">{issue.recommendation}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}

      {/* Generated Info */}
      <div className="text-center text-sm text-gray-500">
        <p>
          Analysis generated by {critique.model_used} at{' '}
          {new Date(critique.generated_at).toLocaleString()}
        </p>
      </div>
    </div>
  )
}

export default CritiqueSection