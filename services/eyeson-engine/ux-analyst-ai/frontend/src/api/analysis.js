import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// Add request interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error)

    if (error.response?.data?.error) {
      throw new Error(error.response.data.error)
    }

    if (error.code === 'ECONNABORTED') {
      throw new Error('Request timeout - please try again')
    }

    throw new Error(error.message || 'Network error occurred')
  }
)

export const startAnalysis = async ({ url, options }) => {
  const response = await api.post('/analyze', {
    url,
    options
  })
  return response.data
}

export const getAnalysisResult = async (analysisId) => {
  const response = await api.get(`/analyze/${analysisId}`)
  return response.data
}

export const getAnalysisReport = async (analysisId) => {
  const response = await api.get(`/analyze/${analysisId}/report`)
  return response.data
}

export const getHealthStatus = async () => {
  const response = await api.get('/health')
  return response.data
}

export const getActiveAnalyses = async () => {
  const response = await api.get('/analyze')
  return response.data
}