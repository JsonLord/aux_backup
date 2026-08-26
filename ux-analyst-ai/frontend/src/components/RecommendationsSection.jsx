import React, { useState } from 'react'

function RecommendationsSection({ uxCritique, accessibility, report }) {
  const [filterPriority, setFilterPriority] = useState('all')
  const [expandedRec, setExpandedRec] = useState(null)

  // Combine recommendations from different sources
  const recommendations = []

  // Add UX recommendations
  if (uxCritique?.structured_critique?.recommendations) {
    recommendations.push(...uxCritique.structured_critique.recommendations.map(rec => ({
      ...rec,
      source: 'UX Analysis',
      sourceIcon: '🎨'
    })))
  }

  // Add accessibility recommendations (converted from violations)
  if (accessibility?.violations) {
    const a11yRecs = accessibility.violations
      .filter(v => v.impact === 'critical' || v.impact === 'serious')
      .slice(0, 5) // Limit to top 5 most important
      .map(violation => ({
        priority: violation.impact === 'critical' ? 'High' : 'Medium',
        category: 'Accessibility',
        title: violation.help,
        description: violation.description,
        impact: `Affects ${violation.nodes?.length || 0} elements. ${violation.impact} accessibility issue.`,
        effort: 'Medium',
        source: 'Accessibility Scan',
        sourceIcon: '♿',
        helpUrl: violation.helpUrl
      }))

    recommendations.push(...a11yRecs)
  }

  // Filter by priority
  const filteredRecommendations = recommendations.filter(rec => {
    if (filterPriority === 'all') return true
    return rec.priority.toLowerCase() === filterPriority.toLowerCase()
  })

  // Sort by priority
  const priorityOrder = { High: 3, Medium: 2, Low: 1 }
  filteredRecommendations.sort((a, b) =>
    priorityOrder[b.priority] - priorityOrder[a.priority]
  )

  const getPriorityColor = (priority) => {
    if (priority === 'High') return 'badge-error'
    if (priority === 'Medium') return 'badge-warning'
    return 'badge-success'
  }

  const getEffortColor = (effort) => {
    if (effort === 'High') return 'text-error-600'
    if (effort === 'Medium') return 'text-warning-600'
    return 'text-success-600'
  }

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="card">
        <h3 className="text-xl font-semibold mb-4">Recommendations Summary</h3>

        <div className="grid md:grid-cols-4 gap-6">
          <div className="text-center">
            <div className="text-2xl font-bold text-error-600">
              {recommendations.filter(r => r.priority === 'High').length}
            </div>
            <p className="text-gray-600 text-sm">High Priority</p>
          </div>

          <div className="text-center">
            <div className="text-2xl font-bold text-warning-600">
              {recommendations.filter(r => r.priority === 'Medium').length}
            </div>
            <p className="text-gray-600 text-sm">Medium Priority</p>
          </div>

          <div className="text-center">
            <div className="text-2xl font-bold text-success-600">
              {recommendations.filter(r => r.priority === 'Low').length}
            </div>
            <p className="text-gray-600 text-sm">Low Priority</p>
          </div>

          <div className="text-center">
            <div className="text-2xl font-bold text-gray-600">
              {recommendations.length}
            </div>
            <p className="text-gray-600 text-sm">Total Items</p>
          </div>
        </div>

        {/* Quick Action Items */}
        {report?.summary?.priorityLevel === 'High' && (
          <div className="mt-6 bg-error-50 border border-error-200 rounded-lg p-4">
            <h4 className="font-semibold text-error-900 mb-2">🚨 Immediate Action Required</h4>
            <p className="text-error-700 text-sm">
              Your website has critical issues that should be addressed immediately.
              Focus on the high-priority items below to improve user experience and accessibility.
            </p>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="card">
        <div className="flex items-center justify-between">
          <h3 className="text-xl font-semibold">Action Items</h3>

          <select
            value={filterPriority}
            onChange={(e) => setFilterPriority(e.target.value)}
            className="px-3 py-1 border border-gray-300 rounded text-sm"
          >
            <option value="all">All Priorities</option>
            <option value="high">High Priority</option>
            <option value="medium">Medium Priority</option>
            <option value="low">Low Priority</option>
          </select>
        </div>
      </div>

      {/* Recommendations List */}
      {filteredRecommendations.length === 0 ? (
        <div className="card text-center">
          <div className="w-16 h-16 bg-success-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-success-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h4 className="text-lg font-semibold text-gray-900 mb-2">
            {filterPriority === 'all' ? 'No Recommendations' : `No ${filterPriority} priority items`}
          </h4>
          <p className="text-gray-600">
            {filterPriority === 'all'
              ? 'Great job! No specific recommendations were generated.'
              : 'Try selecting "All Priorities" to see other recommendations.'
            }
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredRecommendations.map((rec, index) => (
            <div key={index} className="card border-l-4 border-l-gray-300">
              <button
                onClick={() => setExpandedRec(expandedRec === index ? null : index)}
                className="w-full text-left"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 mr-4">
                    <div className="flex items-center mb-2">
                      <span className="text-lg mr-2">{rec.sourceIcon}</span>
                      <h4 className="font-semibold text-gray-900 mr-3">{rec.title}</h4>
                      <span className={`badge ${getPriorityColor(rec.priority)}`}>
                        {rec.priority}
                      </span>
                    </div>

                    <div className="flex items-center space-x-4 text-sm text-gray-600 mb-2">
                      <span>📂 {rec.category}</span>
                      <span>📍 {rec.source}</span>
                      {rec.effort && (
                        <span className={`font-medium ${getEffortColor(rec.effort)}`}>
                          💪 {rec.effort} effort
                        </span>
                      )}
                    </div>

                    <p className="text-gray-700 text-sm">
                      {rec.description?.substring(0, 150)}
                      {rec.description?.length > 150 && '...'}
                    </p>
                  </div>

                  <svg
                    className={`w-5 h-5 text-gray-400 transition-transform ${
                      expandedRec === index ? 'rotate-180' : ''
                    }`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </button>

              {expandedRec === index && (
                <div className="mt-4 pt-4 border-t border-gray-100 space-y-4">
                  {/* Full Description */}
                  <div>
                    <h5 className="font-semibold text-gray-900 mb-2">Description</h5>
                    <p className="text-gray-700">{rec.description}</p>
                  </div>

                  {/* Expected Impact */}
                  {rec.impact && (
                    <div>
                      <h5 className="font-semibold text-gray-900 mb-2">Expected Impact</h5>
                      <p className="text-gray-700">{rec.impact}</p>
                    </div>
                  )}

                  {/* Implementation Details */}
                  <div className="grid md:grid-cols-2 gap-4">
                    <div>
                      <h5 className="font-semibold text-gray-900 mb-2">Implementation</h5>
                      <div className="space-y-1 text-sm text-gray-600">
                        <div className="flex justify-between">
                          <span>Priority:</span>
                          <span className={`badge ${getPriorityColor(rec.priority)}`}>
                            {rec.priority}
                          </span>
                        </div>
                        {rec.effort && (
                          <div className="flex justify-between">
                            <span>Effort Required:</span>
                            <span className={`font-medium ${getEffortColor(rec.effort)}`}>
                              {rec.effort}
                            </span>
                          </div>
                        )}
                        <div className="flex justify-between">
                          <span>Category:</span>
                          <span className="font-medium">{rec.category}</span>
                        </div>
                      </div>
                    </div>

                    <div>
                      <h5 className="font-semibold text-gray-900 mb-2">Resources</h5>
                      <div className="space-y-2">
                        {rec.helpUrl && (
                          <a
                            href={rec.helpUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block text-primary-600 hover:text-primary-700 text-sm"
                          >
                            📖 Learn more about this issue →
                          </a>
                        )}
                        {rec.source === 'UX Analysis' && (
                          <p className="text-sm text-gray-600">
                            💡 Generated by AI UX analysis
                          </p>
                        )}
                        {rec.source === 'Accessibility Scan' && (
                          <p className="text-sm text-gray-600">
                            ♿ Found in accessibility audit
                          </p>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex space-x-3 pt-2">
                    <button className="px-4 py-2 bg-primary-100 text-primary-700 rounded text-sm font-medium hover:bg-primary-200 transition-colors">
                      Mark as Done
                    </button>
                    <button className="px-4 py-2 bg-gray-100 text-gray-700 rounded text-sm font-medium hover:bg-gray-200 transition-colors">
                      Save for Later
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Implementation Guide */}
      <div className="card bg-gradient-to-r from-blue-50 to-primary-50">
        <h3 className="text-xl font-semibold mb-4">Implementation Guide</h3>

        <div className="grid md:grid-cols-3 gap-6">
          <div>
            <h4 className="font-semibold text-primary-900 mb-2">🚀 Start Here</h4>
            <ul className="text-sm text-primary-700 space-y-1">
              <li>• Focus on high-priority items first</li>
              <li>• Address accessibility issues quickly</li>
              <li>• Test changes before deploying</li>
            </ul>
          </div>

          <div>
            <h4 className="font-semibold text-primary-900 mb-2">📈 Track Progress</h4>
            <ul className="text-sm text-primary-700 space-y-1">
              <li>• Re-run analysis after changes</li>
              <li>• Monitor user feedback</li>
              <li>• Measure performance impact</li>
            </ul>
          </div>

          <div>
            <h4 className="font-semibold text-primary-900 mb-2">🎯 Best Practices</h4>
            <ul className="text-sm text-primary-700 space-y-1">
              <li>• Make changes incrementally</li>
              <li>• Consider user impact</li>
              <li>• Document improvements</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}

export default RecommendationsSection