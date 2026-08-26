import React, { useState } from 'react'

function ScreenshotViewer({ screenshots, url }) {
  const [selectedViewport, setSelectedViewport] = useState(
    Object.keys(screenshots)[0] || 'desktop'
  )

  const viewportLabels = {
    desktop: 'Desktop',
    tablet: 'Tablet',
    mobile: 'Mobile'
  }

  const viewportIcons = {
    desktop: '🖥️',
    tablet: '📱',
    mobile: '📱'
  }

  if (!screenshots || Object.keys(screenshots).length === 0) {
    return (
      <div className="card text-center">
        <p className="text-gray-600">No screenshots available</p>
      </div>
    )
  }

  const currentScreenshot = screenshots[selectedViewport]

  return (
    <div className="space-y-6">
      {/* Viewport Selector */}
      <div className="card">
        <h3 className="text-xl font-semibold mb-4">Website Screenshots</h3>

        <div className="flex flex-wrap gap-4 mb-6">
          {Object.keys(screenshots).map(viewport => (
            <button
              key={viewport}
              onClick={() => setSelectedViewport(viewport)}
              className={`
                flex items-center px-4 py-2 rounded-lg font-medium transition-colors
                ${selectedViewport === viewport
                  ? 'bg-primary-100 text-primary-700 border-2 border-primary-200'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200 border-2 border-transparent'
                }
              `}
            >
              <span className="mr-2">{viewportIcons[viewport]}</span>
              {viewportLabels[viewport]}
              <span className="ml-2 text-sm text-gray-500">
                {screenshots[viewport].width}×{screenshots[viewport].height}
              </span>
            </button>
          ))}
        </div>

        {/* Screenshot Display */}
        {currentScreenshot && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="font-semibold text-gray-900">
                  {viewportLabels[selectedViewport]} View
                </h4>
                <p className="text-sm text-gray-600">
                  {currentScreenshot.width} × {currentScreenshot.height} pixels
                </p>
              </div>

              <div className="flex items-center space-x-2">
                <button
                  onClick={() => window.open(currentScreenshot.url, '_blank')}
                  className="btn btn-secondary btn-sm"
                >
                  Open Full Size
                </button>
                <a
                  href={currentScreenshot.url}
                  download={`${url.replace(/[^a-zA-Z0-9]/g, '_')}_${selectedViewport}.png`}
                  className="btn btn-primary btn-sm"
                >
                  Download
                </a>
              </div>
            </div>

            {/* Screenshot Image */}
            <div className="bg-gray-100 rounded-lg p-4">
              <div className="bg-white rounded shadow-lg overflow-hidden max-w-full">
                <img
                  src={currentScreenshot.url}
                  alt={`${viewportLabels[selectedViewport]} screenshot of ${url}`}
                  className="w-full h-auto max-h-screen object-contain"
                  style={{ maxHeight: '800px' }}
                />
              </div>
            </div>

            {/* Screenshot Info */}
            <div className="bg-gray-50 rounded-lg p-4">
              <h5 className="font-medium text-gray-900 mb-2">Screenshot Details</h5>
              <div className="grid md:grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-gray-600">Viewport:</span>
                  <span className="ml-2 font-medium">
                    {viewportLabels[selectedViewport]}
                  </span>
                </div>
                <div>
                  <span className="text-gray-600">Dimensions:</span>
                  <span className="ml-2 font-medium">
                    {currentScreenshot.width} × {currentScreenshot.height}
                  </span>
                </div>
                <div>
                  <span className="text-gray-600">File Size:</span>
                  <span className="ml-2 font-medium">
                    {(currentScreenshot.fileSize / 1024).toFixed(1)} KB
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Comparison View */}
      {Object.keys(screenshots).length > 1 && (
        <div className="card">
          <h3 className="text-xl font-semibold mb-4">Responsive Comparison</h3>

          <div className="grid gap-6">
            {Object.entries(screenshots).map(([viewport, screenshot]) => (
              <div key={viewport} className="space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="font-medium text-gray-900">
                    {viewportIcons[viewport]} {viewportLabels[viewport]}
                  </h4>
                  <span className="text-sm text-gray-500">
                    {screenshot.width} × {screenshot.height}
                  </span>
                </div>

                <div className="bg-gray-100 rounded-lg p-2">
                  <div className="bg-white rounded shadow overflow-hidden">
                    <img
                      src={screenshot.url}
                      alt={`${viewportLabels[viewport]} screenshot`}
                      className="w-full h-auto"
                      style={{ maxHeight: '400px', objectFit: 'cover', objectPosition: 'top' }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
            <h5 className="font-semibold text-blue-900 mb-2">Responsive Design Notes</h5>
            <ul className="text-sm text-blue-700 space-y-1">
              <li>• Compare how your website appears across different screen sizes</li>
              <li>• Look for layout issues, text readability, and navigation usability</li>
              <li>• Ensure important content and actions are accessible on all devices</li>
              <li>• Check that images and media scale appropriately</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}

export default ScreenshotViewer