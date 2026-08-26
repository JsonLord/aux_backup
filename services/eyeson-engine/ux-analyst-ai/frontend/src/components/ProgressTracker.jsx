import React from 'react'

function ProgressTracker({ progress = 0 }) {
  const stages = [
    { name: 'Validating URL', threshold: 10 },
    { name: 'Capturing Screenshots', threshold: 25 },
    { name: 'Scanning Accessibility', threshold: 50 },
    { name: 'Generating AI Analysis', threshold: 75 },
    { name: 'Compiling Report', threshold: 95 },
    { name: 'Complete', threshold: 100 }
  ]

  const currentStage = stages.find(stage => progress <= stage.threshold) || stages[stages.length - 1]
  const currentStageIndex = stages.indexOf(currentStage)

  return (
    <div className="card">
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">
          Analyzing Your Website
        </h2>
        <p className="text-gray-600">
          Please wait while we analyze your website. This typically takes 1-3 minutes.
        </p>
      </div>

      {/* Progress Bar */}
      <div className="mb-8">
        <div className="flex justify-between text-sm text-gray-600 mb-2">
          <span>Progress</span>
          <span>{progress}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-3">
          <div
            className="bg-primary-600 h-3 rounded-full transition-all duration-500 ease-out"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Current Stage */}
      <div className="text-center mb-8">
        <div className="inline-flex items-center bg-primary-50 text-primary-700 px-4 py-2 rounded-full">
          <div className="animate-spin w-4 h-4 border-2 border-primary-600 border-t-transparent rounded-full mr-2" />
          <span className="font-medium">{currentStage.name}</span>
        </div>
      </div>

      {/* Stage Timeline */}
      <div className="space-y-4">
        {stages.map((stage, index) => {
          const isCompleted = progress > stage.threshold
          const isCurrent = index === currentStageIndex
          const isPending = progress < stage.threshold

          return (
            <div key={stage.name} className="flex items-center">
              <div className={`
                w-8 h-8 rounded-full flex items-center justify-center mr-4 transition-colors
                ${isCompleted ? 'bg-success-500 text-white' :
                  isCurrent ? 'bg-primary-500 text-white' :
                  'bg-gray-200 text-gray-500'}
              `}>
                {isCompleted ? (
                  <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                  </svg>
                ) : isCurrent ? (
                  <div className="w-3 h-3 bg-white rounded-full" />
                ) : (
                  <span className="text-sm font-medium">{index + 1}</span>
                )}
              </div>

              <div className="flex-1">
                <p className={`
                  font-medium transition-colors
                  ${isCompleted ? 'text-success-700' :
                    isCurrent ? 'text-primary-700' :
                    'text-gray-500'}
                `}>
                  {stage.name}
                </p>
                {isCurrent && (
                  <p className="text-sm text-gray-600">In progress...</p>
                )}
              </div>

              <div className={`
                px-2 py-1 rounded text-xs font-medium
                ${isCompleted ? 'bg-success-100 text-success-700' :
                  isCurrent ? 'bg-primary-100 text-primary-700' :
                  'bg-gray-100 text-gray-500'}
              `}>
                {isCompleted ? 'Done' : isCurrent ? 'Active' : 'Pending'}
              </div>
            </div>
          )
        })}
      </div>

      {/* Estimated Time */}
      <div className="mt-8 text-center text-sm text-gray-500">
        <p>Estimated time remaining: {Math.max(0, Math.ceil((100 - progress) / 10))} minutes</p>
      </div>

      {/* Tips */}
      <div className="mt-8 bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h3 className="font-semibold text-blue-900 mb-2">While you wait...</h3>
        <ul className="text-sm text-blue-700 space-y-1">
          <li>• We're capturing screenshots across multiple device sizes</li>
          <li>• Our AI is analyzing visual design and user experience patterns</li>
          <li>• Accessibility compliance is being checked against WCAG guidelines</li>
          <li>• You'll get a comprehensive report with actionable recommendations</li>
        </ul>
      </div>
    </div>
  )
}

export default ProgressTracker