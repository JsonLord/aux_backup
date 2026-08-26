import React, { useState } from 'react'

function AccessibilitySection({ accessibility }) {
  const [expandedViolation, setExpandedViolation] = useState(null)
  const [filterLevel, setFilterLevel] = useState('all')

  if (!accessibility) {
    return (
      <div className="card">
        <p className="text-gray-600">Accessibility data not available</p>
      </div>
    )
  }

  const getScoreColor = (score) => {
    if (score >= 90) return 'text-success-600'
    if (score >= 75) return 'text-primary-600'
    if (score >= 60) return 'text-warning-600'
    return 'text-error-600'
  }

  const getImpactColor = (impact) => {
    if (impact === 'critical') return 'badge-error'
    if (impact === 'serious') return 'badge-error'
    if (impact === 'moderate') return 'badge-warning'
    return 'badge-info'
  }

  const getComplianceColor = (status) => {
    return status === 'Compliant' ? 'text-success-600' : 'text-error-600'
  }

  const filteredViolations = accessibility.violations?.filter(violation => {
    if (filterLevel === 'all') return true
    return violation.impact === filterLevel
  }) || []

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="card">
        <h3 className="text-xl font-semibold mb-4">Accessibility Overview</h3>

        <div className="grid md:grid-cols-4 gap-6 mb-6">
          <div className="text-center">
            <div className={`text-3xl font-bold ${getScoreColor(accessibility.summary.score)}`}>
              {accessibility.summary.score}
              <span className="text-lg text-gray-500">/100</span>
            </div>
            <p className="text-gray-600 text-sm">Accessibility Score</p>
          </div>

          <div className="text-center">
            <div className="text-3xl font-bold text-error-600">
              {accessibility.summary.totalViolations}
            </div>
            <p className="text-gray-600 text-sm">Total Violations</p>
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
            <p className="text-gray-600 text-sm">Manual Review Needed</p>
          </div>
        </div>

        {/* Impact Breakdown */}
        <div className="bg-gray-50 rounded-lg p-4">
          <h4 className="font-semibold text-gray-900 mb-3">Violations by Impact</h4>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {Object.entries(accessibility.summary.violationsByImpact).map(([impact, count]) => (
              <div key={impact} className="text-center">
                <div className={`text-xl font-bold ${
                  impact === 'critical' ? 'text-red-600' :
                  impact === 'serious' ? 'text-orange-600' :
                  impact === 'moderate' ? 'text-yellow-600' :
                  'text-blue-600'
                }`}>
                  {count}
                </div>
                <p className="text-sm text-gray-600 capitalize">{impact}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* WCAG Compliance */}
      <div className="card">
        <h3 className="text-xl font-semibold mb-4">WCAG Compliance Status</h3>

        <div className="grid md:grid-cols-2 gap-6">
          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-gray-700">WCAG 2.1 Level A:</span>
              <span className={`font-semibold ${getComplianceColor('Compliant')}`}>
                {accessibility.violations?.some(v => v.tags?.includes('wcag2a')) ? 'Non-compliant' : 'Compliant'}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-700">WCAG 2.1 Level AA:</span>
              <span className={`font-semibold ${getComplianceColor('Compliant')}`}>
                {accessibility.violations?.some(v => v.tags?.includes('wcag2aa')) ? 'Non-compliant' : 'Compliant'}
              </span>
            </div>
          </div>

          <div>
            <h4 className="font-semibold text-gray-900 mb-2">Key Categories</h4>
            <div className="space-y-1 text-sm">
              {Object.entries(accessibility.summary.categories || {}).slice(0, 5).map(([category, issues]) => (
                <div key={category} className="flex justify-between">
                  <span className="text-gray-600 capitalize">{category.replace('-', ' ')}:</span>
                  <span className="font-medium">{issues.length} issues</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Violations List */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xl font-semibold">Accessibility Violations</h3>

          {/* Filter */}
          <select
            value={filterLevel}
            onChange={(e) => setFilterLevel(e.target.value)}
            className="px-3 py-1 border border-gray-300 rounded text-sm"
          >
            <option value="all">All Impacts</option>
            <option value="critical">Critical</option>
            <option value="serious">Serious</option>
            <option value="moderate">Moderate</option>
            <option value="minor">Minor</option>
          </select>
        </div>

        {filteredViolations.length === 0 ? (
          <div className="text-center py-8">
            <div className="w-16 h-16 bg-success-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-success-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h4 className="text-lg font-semibold text-gray-900 mb-2">
              {filterLevel === 'all' ? 'No Violations Found!' : `No ${filterLevel} violations found`}
            </h4>
            <p className="text-gray-600">
              {filterLevel === 'all'
                ? 'Great job! Your website passed all automated accessibility tests.'
                : `Try selecting "All Impacts" to see other violation levels.`
              }
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {filteredViolations.map((violation, index) => (
              <div key={violation.id || index} className="border border-gray-200 rounded-lg">
                <button
                  onClick={() => setExpandedViolation(expandedViolation === index ? null : index)}
                  className="w-full p-4 text-left hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 mr-4">
                      <div className="flex items-center mb-2">
                        <h4 className="font-semibold text-gray-900 mr-3">{violation.help}</h4>
                        <span className={`badge ${getImpactColor(violation.impact)}`}>
                          {violation.impact}
                        </span>
                      </div>
                      <p className="text-gray-700 text-sm">{violation.description}</p>
                      <p className="text-gray-500 text-xs mt-1">
                        Affects {violation.nodes?.length || 0} element(s)
                      </p>
                    </div>
                    <svg
                      className={`w-5 h-5 text-gray-400 transition-transform ${
                        expandedViolation === index ? 'rotate-180' : ''
                      }`}
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </div>
                </button>

                {expandedViolation === index && (
                  <div className="px-4 pb-4 border-t border-gray-100">
                    <div className="space-y-4 mt-4">
                      {/* Help Information */}
                      <div>
                        <h5 className="font-semibold text-gray-900 mb-2">How to Fix</h5>
                        <p className="text-gray-700 text-sm">{violation.help}</p>
                        {violation.helpUrl && (
                          <a
                            href={violation.helpUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary-600 hover:text-primary-700 text-sm mt-1 inline-block"
                          >
                            Learn more →
                          </a>
                        )}
                      </div>

                      {/* Affected Elements */}
                      {violation.nodes && violation.nodes.length > 0 && (
                        <div>
                          <h5 className="font-semibold text-gray-900 mb-2">
                            Affected Elements ({violation.nodes.length})
                          </h5>
                          <div className="space-y-2 max-h-40 overflow-y-auto">
                            {violation.nodes.slice(0, 5).map((node, nodeIndex) => (
                              <div key={nodeIndex} className="bg-gray-50 rounded p-3 text-sm">
                                <div className="font-mono text-xs text-gray-600 mb-1">
                                  Target: {node.target?.join(', ') || 'Unknown'}
                                </div>
                                <div className="text-gray-700">
                                  {node.html?.substring(0, 150)}
                                  {node.html?.length > 150 && '...'}
                                </div>
                              </div>
                            ))}
                            {violation.nodes.length > 5 && (
                              <p className="text-sm text-gray-500">
                                ... and {violation.nodes.length - 5} more elements
                              </p>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Tags */}
                      {violation.tags && violation.tags.length > 0 && (
                        <div>
                          <h5 className="font-semibold text-gray-900 mb-2">Related Standards</h5>
                          <div className="flex flex-wrap gap-2">
                            {violation.tags.map(tag => (
                              <span
                                key={tag}
                                className="px-2 py-1 bg-gray-100 text-gray-700 rounded text-xs"
                              >
                                {tag.toUpperCase()}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Additional Info */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h4 className="font-semibold text-blue-900 mb-2">About This Analysis</h4>
        <ul className="text-sm text-blue-700 space-y-1">
          <li>• This automated scan covers many but not all accessibility issues</li>
          <li>• Manual testing is recommended for comprehensive accessibility evaluation</li>
          <li>• Focus on critical and serious issues first for maximum impact</li>
          <li>• Consider testing with actual assistive technologies</li>
        </ul>
      </div>
    </div>
  )
}

export default AccessibilitySection