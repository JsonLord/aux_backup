import React, { useState, useEffect } from 'react';

function CodeImplementationSection({ analysisId }) {
  const [codeData, setCodeData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('html');

  useEffect(() => {
    if (analysisId) {
      fetchImplementationCode();
    }
  }, [analysisId]);

  const fetchImplementationCode = async () => {
    try {
      setLoading(true);
      const response = await fetch(`/api/analyze/${analysisId}/code`);

      if (response.ok) {
        const data = await response.json();
        setCodeData(data.code);
        setError(null);

        // Set initial tab to first available code type
        const availableTabs = ['html', 'css', 'javascript'].filter(tab =>
          data.code[tab] && data.code[tab].length > 0
        );
        if (availableTabs.length > 0) {
          setActiveTab(availableTabs[0]);
        }
      } else if (response.status === 404) {
        setError('No implementation code available for this analysis');
      } else {
        throw new Error('Failed to fetch implementation code');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = (code) => {
    navigator.clipboard.writeText(code);
    // You could add a toast notification here
  };

  const downloadCode = (code, filename) => {
    const blob = new Blob([code], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const downloadAllCode = () => {
    if (!codeData) return;

    const zipContent = [];

    if (codeData.html && codeData.html.length > 0) {
      const htmlCode = codeData.html.map(item =>
        `<!-- ${item.title} -->\n${item.code}\n\n<!-- Instructions: ${item.instructions} -->\n`
      ).join('\n');
      zipContent.push({ name: 'improvements.html', content: htmlCode });
    }

    if (codeData.css && codeData.css.length > 0) {
      const cssCode = codeData.css.map(item =>
        `/* ${item.title} */\n${item.code}\n\n/* Instructions: ${item.instructions} */\n`
      ).join('\n');
      zipContent.push({ name: 'improvements.css', content: cssCode });
    }

    if (codeData.javascript && codeData.javascript.length > 0) {
      const jsCode = codeData.javascript.map(item =>
        `// ${item.title}\n${item.code}\n\n// Instructions: ${item.instructions}\n`
      ).join('\n');
      zipContent.push({ name: 'improvements.js', content: jsCode });
    }

    // Create implementation guide
    const guide = `# UX Implementation Guide\n\n${codeData.instructions.map(item =>
      `## ${item.recommendation}\n\n${item.steps}\n\n**Notes:** ${item.notes}\n`
    ).join('\n')}`;
    zipContent.push({ name: 'IMPLEMENTATION_GUIDE.md', content: guide });

    // For now, download each file separately (in a real app, you'd create a ZIP)
    zipContent.forEach(file => {
      const blob = new Blob([file.content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = file.name;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  };

  if (loading) {
    return (
      <div className="card">
        <div className="flex items-center justify-center p-8">
          <div className="animate-spin w-6 h-6 border-2 border-primary-600 border-t-transparent rounded-full mr-3" />
          <span>Loading implementation code...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <div className="text-center p-8">
          <div className="text-gray-500 mb-4">
            <svg className="w-12 h-12 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-gray-900 mb-2">No Implementation Code Available</h3>
          <p className="text-gray-600">{error}</p>
        </div>
      </div>
    );
  }

  if (!codeData) {
    return null;
  }

  const tabs = [
    { id: 'html', label: 'HTML', data: codeData.html },
    { id: 'css', label: 'CSS', data: codeData.css },
    { id: 'javascript', label: 'JavaScript', data: codeData.javascript },
    { id: 'instructions', label: 'Implementation Guide', data: codeData.instructions }
  ].filter(tab => tab.data && tab.data.length > 0);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-900">
          Implementation Code
        </h2>
        <button
          onClick={downloadAllCode}
          className="btn btn-secondary flex items-center"
        >
          <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          Download All Code
        </button>
      </div>

      <div className="mb-4">
        <p className="text-gray-600 mb-4">
          Ready-to-use code to implement the UX improvements identified in your analysis.
          Each code block includes implementation instructions and best practices.
        </p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 mb-6">
        <nav className="-mb-px flex space-x-8">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`py-2 px-1 border-b-2 font-medium text-sm ${
                activeTab === tab.id
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="space-y-6">
        {activeTab === 'instructions' ? (
          <div className="space-y-6">
            {codeData.instructions.map((instruction, index) => (
              <div key={index} className="bg-blue-50 border border-blue-200 rounded-lg p-6">
                <h3 className="text-lg font-semibold text-blue-900 mb-3">
                  {instruction.recommendation}
                </h3>
                <div className="text-blue-800 mb-4 whitespace-pre-line">
                  {instruction.steps}
                </div>
                {instruction.notes && (
                  <div className="bg-blue-100 border border-blue-200 rounded p-3">
                    <p className="text-sm text-blue-700">
                      <strong>Notes:</strong> {instruction.notes}
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-6">
            {codeData[activeTab]?.map((codeBlock, index) => (
              <div key={index} className="border border-gray-200 rounded-lg overflow-hidden">
                <div className="bg-gray-50 px-4 py-3 border-b border-gray-200 flex items-center justify-between">
                  <h3 className="font-semibold text-gray-900">{codeBlock.title}</h3>
                  <div className="flex space-x-2">
                    <button
                      onClick={() => copyToClipboard(codeBlock.code)}
                      className="text-gray-500 hover:text-gray-700"
                      title="Copy to clipboard"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                      </svg>
                    </button>
                    <button
                      onClick={() => downloadCode(codeBlock.code, `${codeBlock.title.toLowerCase().replace(/\s+/g, '_')}.${activeTab}`)}
                      className="text-gray-500 hover:text-gray-700"
                      title="Download file"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                    </button>
                  </div>
                </div>
                <div className="bg-gray-900 text-green-400 p-4 font-mono text-sm overflow-x-auto">
                  <pre>{codeBlock.code}</pre>
                </div>
                {codeBlock.instructions && (
                  <div className="bg-gray-50 px-4 py-3 text-sm text-gray-700">
                    <strong>Implementation:</strong> {codeBlock.instructions}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default CodeImplementationSection;