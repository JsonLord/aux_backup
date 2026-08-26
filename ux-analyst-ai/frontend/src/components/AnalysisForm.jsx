import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { startAnalysis } from '../api/analysis'

function AnalysisForm() {
  const navigate = useNavigate()
  const [url, setUrl] = useState('')
  const [options, setOptions] = useState({
    viewports: ['desktop', 'tablet', 'mobile'],
    includeAccessibility: true,
    analysisType: 'comprehensive'
  })

  const analysisMutation = useMutation({
    mutationFn: startAnalysis,
    onSuccess: (data) => {
      navigate(`/analysis/${data.analysisId}`)
    },
    onError: (error) => {
      console.error('Analysis failed:', error)
    }
  })

  const handleSubmit = (e) => {
    e.preventDefault()

    if (!url.trim()) {
      alert('Please enter a URL')
      return
    }

    // Basic URL validation
    try {
      new URL(url)
    } catch {
      alert('Please enter a valid URL (include http:// or https://)')
      return
    }

    analysisMutation.mutate({ url: url.trim(), options })
  }

  const handleViewportChange = (viewport) => {
    setOptions(prev => ({
      ...prev,
      viewports: prev.viewports.includes(viewport)
        ? prev.viewports.filter(v => v !== viewport)
        : [...prev.viewports, viewport]
    }))
  }

  return (
    <div className="card max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold text-gray-900 mb-6 text-center">
        Analyze Your Website
      </h2>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* URL Input */}
        <div>
          <label htmlFor="url-input" className="label">
            Website URL
          </label>
          <input
            id="url-input"
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com"
            className="input"
            disabled={analysisMutation.isPending}
            required
          />
          <p className="text-sm text-gray-500 mt-1">
            Enter the full URL including http:// or https://
          </p>
        </div>

        {/* Analysis Options */}
        <div>
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Analysis Options</h3>

          {/* Analysis Type */}
          <div className="mb-4">
            <label className="label">Analysis Type</label>
            <div className="space-y-2">
              <label className="flex items-center">
                <input
                  type="radio"
                  name="analysisType"
                  value="quick"
                  checked={options.analysisType === 'quick'}
                  onChange={(e) => setOptions(prev => ({ ...prev, analysisType: e.target.value }))}
                  className="mr-2"
                  disabled={analysisMutation.isPending}
                />
                <span className="text-sm">
                  <strong>Quick Analysis</strong> - Basic UX review (~1 min)
                </span>
              </label>
              <label className="flex items-center">
                <input
                  type="radio"
                  name="analysisType"
                  value="comprehensive"
                  checked={options.analysisType === 'comprehensive'}
                  onChange={(e) => setOptions(prev => ({ ...prev, analysisType: e.target.value }))}
                  className="mr-2"
                  disabled={analysisMutation.isPending}
                />
                <span className="text-sm">
                  <strong>Comprehensive Analysis</strong> - Detailed UX + accessibility (~3 min)
                </span>
              </label>
            </div>
          </div>

          {/* Viewports */}
          <div className="mb-4">
            <label className="label">Viewports to Analyze</label>
            <div className="space-y-2">
              {['desktop', 'tablet', 'mobile'].map(viewport => (
                <label key={viewport} className="flex items-center">
                  <input
                    type="checkbox"
                    checked={options.viewports.includes(viewport)}
                    onChange={() => handleViewportChange(viewport)}
                    className="mr-2"
                    disabled={analysisMutation.isPending}
                  />
                  <span className="text-sm capitalize">{viewport}</span>
                  <span className="text-xs text-gray-500 ml-2">
                    {viewport === 'desktop' && '(1920x1080)'}
                    {viewport === 'tablet' && '(768x1024)'}
                    {viewport === 'mobile' && '(375x667)'}
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* Accessibility */}
          <div className="mb-4">
            <label className="flex items-center">
              <input
                type="checkbox"
                checked={options.includeAccessibility}
                onChange={(e) => setOptions(prev => ({ ...prev, includeAccessibility: e.target.checked }))}
                className="mr-2"
                disabled={analysisMutation.isPending}
              />
              <span className="text-sm">
                <strong>Include Accessibility Scan</strong> - WCAG compliance check
              </span>
            </label>
          </div>
        </div>

        {/* Error Display */}
        {analysisMutation.isError && (
          <div className="bg-error-50 border border-error-200 text-error-700 px-4 py-3 rounded-lg">
            <strong>Error:</strong> {analysisMutation.error?.message || 'Failed to start analysis'}
          </div>
        )}

        {/* Submit Button */}
        <button
          type="submit"
          disabled={analysisMutation.isPending || options.viewports.length === 0}
          className={`w-full btn btn-primary ${
            (analysisMutation.isPending || options.viewports.length === 0) ? 'btn-disabled' : ''
          }`}
        >
          {analysisMutation.isPending ? (
            <span className="flex items-center justify-center">
              <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Starting Analysis...
            </span>
          ) : (
            'Start UX Analysis'
          )}
        </button>

        {options.viewports.length === 0 && (
          <p className="text-sm text-error-600 text-center">
            Please select at least one viewport to analyze
          </p>
        )}
      </form>

      {/* Info Box */}
      <div className="mt-6 bg-primary-50 border border-primary-200 rounded-lg p-4">
        <h4 className="font-semibold text-primary-900 mb-2">What happens next?</h4>
        <ul className="text-sm text-primary-700 space-y-1">
          <li>• We'll capture screenshots of your website</li>
          <li>• AI will analyze the design and usability</li>
          <li>• You'll get a detailed report with recommendations</li>
          <li>• The analysis typically takes 1-3 minutes</li>
        </ul>
      </div>
    </div>
  )
}

export default AnalysisForm