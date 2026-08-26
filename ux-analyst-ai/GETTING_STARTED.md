# Getting Started with UX Analyst AI

This guide will help you set up and run UX Analyst AI locally in just a few minutes.

## 📋 Prerequisites

1. **Node.js 18+** - [Download here](https://nodejs.org/)
2. **Google Gemini API Key** - [Get one here](https://makersuite.google.com/app/apikey)

## 🚀 Quick Setup

### 1. Get Your Gemini API Key

1. Visit [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the generated key (starts with `AIza...`)

### 2. Clone and Install

```bash
# Clone the repository
git clone <repository-url>
cd ux-analyst-ai

# Install all dependencies (backend + frontend)
npm run install:all
```

### 3. Configure Environment

```bash
# Copy the environment template
cp .env.example .env

# Edit the .env file and add your API key
# Replace 'your_gemini_api_key_here' with your actual key
```

Your `.env` file should look like:
```bash
GEMINI_API_KEY=AIzaSyC1234567890abcdefghijklmnopqrstuvwxyz
```

### 4. Test Gemini Integration (Optional)

```bash
# Test that your API key works
cd backend
node test-gemini.js
```

You should see:
```
🎉 All tests passed! Gemini integration is working correctly.
```

### 5. Start the Application

```bash
# Start both backend and frontend
npm run dev
```

This will start:
- **Backend API** on http://localhost:3000
- **Frontend** on http://localhost:5173

### 6. Try Your First Analysis

1. Open http://localhost:5173 in your browser
2. Enter any website URL (try `https://example.com`)
3. Click "Start UX Analysis"
4. Watch the real-time progress!

## 🔧 Development Commands

```bash
# Install all dependencies
npm run install:all

# Start both backend and frontend
npm run dev

# Start only backend (port 3000)
npm run dev:backend

# Start only frontend (port 5173)
npm run dev:frontend

# Build frontend for production
npm run build

# Run backend tests
npm test
```

## 🐳 Docker Setup (Alternative)

If you prefer Docker:

```bash
# Build frontend first
cd frontend && npm run build && cd ..

# Set your API key
export GEMINI_API_KEY=your_api_key_here

# Run with Docker Compose
docker-compose up -d

# Access at http://localhost:3000
```

## 🎯 What You Can Analyze

The UX Analyst AI can analyze any public website and provides:

- **Visual Design Assessment** - Typography, color, layout critique
- **Accessibility Analysis** - WCAG compliance checking
- **Usability Review** - Navigation, user flow, and UX patterns
- **Mobile Responsiveness** - Cross-device experience evaluation
- **Performance Insights** - Visual performance indicators

## 🔍 Understanding the Analysis

The system captures screenshots across different device sizes and uses Gemini's vision capabilities to:

1. **Analyze Visual Hierarchy** - How well the design guides user attention
2. **Check Accessibility** - Color contrast, text size, interactive elements
3. **Evaluate Usability** - Navigation clarity, content organization
4. **Assess Mobile Experience** - Layout adaptation and touch-friendliness
5. **Generate Recommendations** - Prioritized, actionable improvement suggestions

## 📊 Analysis Types

- **Quick Analysis (~1 minute)** - Basic UX overview with key insights
- **Comprehensive Analysis (~3 minutes)** - Full UX + accessibility audit with detailed recommendations

## 🚨 Troubleshooting

### Common Issues

**"GEMINI_API_KEY not found"**
- Make sure you copied `.env.example` to `.env`
- Verify your API key is correctly set in the `.env` file
- Don't include quotes around the API key

**"API_KEY_INVALID"**
- Double-check your API key from Google AI Studio
- Ensure you have Gemini API access enabled

**Screenshots not loading**
- Check that the `data/screenshots` directory exists
- Ensure sufficient disk space
- Try analyzing a different website

**Analysis stuck at "Capturing Screenshots"**
- Some websites block automated access
- Try a different URL
- Check your internet connection

### Getting Help

1. **Check the logs** - Look at the browser console and terminal output
2. **Test Gemini integration** - Run `node backend/test-gemini.js`
3. **Verify environment** - Visit http://localhost:3000/api/health

## 💡 Tips for Best Results

1. **Use public websites** - Private or login-required sites won't work
2. **Try well-known sites first** - Test with sites like `https://github.com` or `https://stackoverflow.com`
3. **Wait for completion** - Analysis takes 1-3 minutes depending on the type
4. **Check multiple viewports** - Enable desktop, tablet, and mobile for comprehensive analysis

## 🎉 You're Ready!

You now have UX Analyst AI running locally. Try analyzing your own website or any site you're curious about. The AI will provide detailed, actionable feedback to improve user experience and accessibility.

Happy analyzing! 🚀