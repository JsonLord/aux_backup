import React from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getAnalysisResult } from '../api/analysis'
import ProgressTracker from '../components/ProgressTracker'
import AnalysisResults from '../components/AnalysisResults'

function AnalysisPage() {
  const { id } = useParams()

  const { data: analysis, isLoading, isError, error } = useQuery({
    queryKey: ['analysis', id],
    queryFn: () => getAnalysisResult(id),
    refetchInterval: (data) => {
      // Keep polling if analysis is still processing
      return data?.status === 'processing' ? 2000 : false
    },
    enabled: !!id
  })

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="card text-center">
          <div className="animate-spin w-8 h-8 border-2 border-primary-600 border-t-transparent rounded-full mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Loading Analysis...</h2>
          <p className="text-gray-600">Please wait while we fetch your analysis results.</p>
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="card text-center">
          <div className="w-16 h-16 bg-error-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-error-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-error-900 mb-2">Analysis Not Found</h2>
          <p className="text-gray-600 mb-4">
            {error?.message || 'The analysis you\'re looking for could not be found.'}
          </p>
          <Link to="/" className="btn btn-primary">
            Start New Analysis
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-3xl font-bold text-gray-900">UX Analysis Results</h1>
          <Link to="/" className="btn btn-secondary">
            Start New Analysis
          </Link>
        </div>

        <div className="bg-gray-50 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-gray-500">Analyzing</p>
              <p className="font-semibold text-gray-900 break-all">{analysis.url}</p>
            </div>
            <div className="text-right">
              <p className="text-sm text-gray-500">Started</p>
              <p className="text-sm text-gray-700">
                {new Date(analysis.createdAt).toLocaleString()}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Status-based Content */}
      {analysis.status === 'processing' && (
        <ProgressTracker progress={analysis.progress} />
      )}

      {analysis.status === 'failed' && (
        <div className="card text-center">
          <div className="w-16 h-16 bg-error-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-error-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-error-900 mb-2">Analysis Failed</h2>

          {/* Enhanced error messaging based on error type */}
          <div className="text-left bg-gray-50 rounded-lg p-4 mb-6 max-w-2xl mx-auto">
            <p className="text-gray-800 font-medium mb-2">Error Details:</p>
            <p className="text-gray-600 mb-3">
              {analysis.errorMessage || 'The analysis encountered an error and could not be completed.'}
            </p>

            {/* Specific suggestions based on error type */}
            {analysis.errorMessage?.includes('timed out') && (
              <div className="bg-blue-50 border-l-4 border-blue-400 p-3 mb-3">
                <p className="text-blue-800 text-sm">
                  <strong>Timeout Error:</strong> This usually happens when the website takes too long to load or respond.
                  Try again in a few minutes, or try analyzing a different website.
                </p>
              </div>
            )}

            {analysis.errorMessage?.includes('overloaded') && (
              <div className="bg-yellow-50 border-l-4 border-yellow-400 p-3 mb-3">
                <p className="text-yellow-800 text-sm">
                  <strong>Service Overloaded:</strong> Our AI analysis service is currently experiencing high demand.
                  Please wait a few minutes and try again.
                </p>
              </div>
            )}

            {analysis.errorMessage?.includes('screenshot') && (
              <div className="bg-orange-50 border-l-4 border-orange-400 p-3 mb-3">
                <p className="text-orange-800 text-sm">
                  <strong>Screenshot Error:</strong> We couldn't capture screenshots of the website.
                  This might happen if the site blocks automated access or has loading issues.
                </p>
              </div>
            )}

            {analysis.errorMessage?.includes('accessibility') && (
              <div className="bg-purple-50 border-l-4 border-purple-400 p-3 mb-3">
                <p className="text-purple-800 text-sm">
                  <strong>Accessibility Scan Error:</strong> There was an issue with the accessibility analysis.
                  The UX analysis may still be available.
                </p>
              </div>
            )}

            {/* General retry suggestions */}
            <div className="bg-green-50 border-l-4 border-green-400 p-3">
              <p className="text-green-800 text-sm">
                <strong>Suggestions:</strong>
              </p>
              <ul className="text-green-700 text-sm mt-1 list-disc list-inside space-y-1">
                <li>Wait 2-3 minutes and try again</li>
                <li>Make sure the website URL is publicly accessible</li>
                <li>Try a different website to test the service</li>
                <li>Contact support if the issue persists</li>
              </ul>
            </div>
          </div>

          <div className="space-x-4">
            <button
              onClick={() => window.location.reload()}
              className="btn btn-primary"
            >
              Try Again
            </button>
            <Link to="/" className="btn btn-secondary">
              Start New Analysis
            </Link>
          </div>
        </div>
      )}

      {analysis.status === 'completed' && (
        <AnalysisResults analysis={analysis} />
      )}
    </div>
  )
}

export default AnalysisPage