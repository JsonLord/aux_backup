# UX Analyst AI - Personal Development Tool

## Quick Setup for Personal Use

### 1. Install Dependencies
```bash
# Backend
cd backend
npm install

# Frontend
cd ../frontend
npm install
```

### 2. Environment Setup
Create `backend/.env`:
```
GEMINI_API_KEY=your_gemini_api_key_here
NODE_ENV=development
PORT=3005
```

### 3. Start the Tool
```bash
# Terminal 1 - Backend
cd backend
npm run dev

# Terminal 2 - Frontend (new terminal)
cd frontend
npm run dev
```

### 4. Access
- Frontend: http://localhost:5173
- Backend API: http://localhost:3005

## Usage for Your Projects

1. **Start the servers** (both backend and frontend)
2. **Enter your website URL** in the frontend
3. **Wait for analysis** (2-5 minutes depending on site complexity)
4. **Download the report** or view results in browser

## Troubleshooting

### If analysis gets stuck:
1. Check backend logs for errors
2. Restart backend server: `Ctrl+C` then `npm run dev`
3. Try a simpler website first to test

### If screenshots fail:
- The AI analysis will still work
- Reports will generate without screenshots

### Common Issues:
- **"Validating URL" forever**: Backend probably crashed, restart it
- **No screenshots**: Browser automation failed, but analysis continues
- **Report generation fails**: Check backend logs for specific errors

## What Works Well:
- ✅ AI-powered UX critique
- ✅ Screenshot capture (most sites)
- ✅ HTML report generation
- ✅ Basic progress tracking

## Known Limitations:
- ⚠️ Complex visual analysis may crash on large sites
- ⚠️ Some sites block automated browsers
- ⚠️ Memory usage can be high for large pages

## For Claude Code Sessions:
When you want me to analyze a site:
1. Start both servers
2. Tell me the URL you want analyzed
3. I can help troubleshoot any issues that come up
4. We can review the generated reports together