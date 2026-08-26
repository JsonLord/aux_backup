# UX Analyst AI - MVP Development Specification
## For Claude Code Implementation

### Project Overview
Build an AI-powered UX analysis tool that provides instant, expert-level feedback on website design and usability. The MVP focuses on visual UX critique with basic accessibility scanning, designed to complement existing accessibility tools rather than replace them.

---

## MVP Architecture

### Tech Stack
```yaml
Backend:
  - Node.js with Express
  - Puppeteer for screenshot capture
  - OpenCV.js for computer vision analysis
  - Claude API for AI critique generation
  - Axe-core for accessibility scanning

Frontend:
  - React with Vite
  - Tailwind CSS for styling
  - React Query for state management
  - Chart.js for analytics visualization

Storage:
  - SQLite for development (PostgreSQL for production)
  - Local file storage for screenshots
  - JSON for analysis results

Deployment:
  - Docker containerization
  - Environment-based configuration
  - Health check endpoints
```

### Core Components

#### 1. Screenshot Capture Service
```javascript
// services/screenshotService.js
class ScreenshotService {
  async captureScreenshot(url, options = {}) {
    /*
    Requirements:
    - Capture full page screenshots
    - Multiple viewport sizes (desktop, tablet, mobile)
    - Handle loading states and dynamic content
    - Generate responsive variants
    - Error handling for invalid URLs
    
    Options:
    - viewport: { width, height }
    - device: 'desktop' | 'tablet' | 'mobile'
    - waitFor: selector or timeout
    - fullPage: boolean
    */
  }

  async captureMultipleViewports(url) {
    /*
    Capture screenshots for:
    - Desktop: 1920x1080
    - Tablet: 768x1024  
    - Mobile: 375x667
    
    Return object with all variants
    */
  }
}
```

#### 2. Computer Vision Analyzer
```javascript
// services/visionService.js
class VisionAnalyzer {
  async analyzeVisualHierarchy(screenshot) {
    /*
    Use OpenCV to detect:
    - Color distribution and contrast
    - Text regions and sizes
    - Button and interactive element locations
    - Visual weight distribution
    - Whitespace analysis
    
    Return structured data about visual elements
    */
  }

  async detectUIComponents(screenshot) {
    /*
    Identify common UI patterns:
    - Headers, navbars, footers
    - Buttons, forms, CTAs
    - Content sections
    - Image vs text regions
    */
  }

  async analyzeAccessibilityVisual(screenshot) {
    /*
    Visual-specific accessibility checks:
    - Color contrast in actual rendered context
    - Text size relative to viewport
    - Touch target spacing and size
    - Focus indicator visibility
    */
  }
}
```

#### 3. AI Critique Engine
```javascript
// services/aiCritiqueService.js
class AICritiqueService {
  async generateUXCritique(analysisData) {
    /*
    Send to Claude API with structured prompt:
    
    Input:
    - Visual analysis results
    - Accessibility scan results  
    - Screenshot metadata
    - URL context (if provided)
    
    Output:
    - Detailed UX recommendations
    - Priority scoring (High/Medium/Low)
    - Specific improvement suggestions
    - Code examples where applicable
    */
  }

  async generateReport(critiques, screenshots) {
    /*
    Compile comprehensive report with:
    - Executive summary
    - Detailed findings by category
    - Before/after suggestions
    - Actionable next steps
    */
  }
}
```

#### 4. Analysis Orchestrator
```javascript
// services/analysisService.js
class AnalysisService {
  async analyzeWebsite(url, options = {}) {
    /*
    Main orchestration method:
    
    1. Validate URL and capture screenshots
    2. Run accessibility scan with axe-core
    3. Perform computer vision analysis
    4. Generate AI critique
    5. Compile results into structured report
    6. Store results in database
    7. Return analysis ID and summary
    */
  }

  async getAnalysisResult(analysisId) {
    /*
    Retrieve stored analysis results
    Include screenshots, report data, and metadata
    */
  }
}
```

---

## API Endpoints

### Core Analysis API
```javascript
// API Routes Structure

POST /api/analyze
/*
Body: {
  url: string,
  options?: {
    includeAccessibility: boolean,
    viewports: string[], // ['desktop', 'tablet', 'mobile']
    waitFor?: string,
    analysisType: 'quick' | 'comprehensive'
  }
}

Response: {
  analysisId: string,
  status: 'processing' | 'completed' | 'failed',
  estimatedCompletion: number, // seconds
  url: string
}
*/

GET /api/analyze/:id
/*
Response: {
  id: string,
  url: string,
  status: 'processing' | 'completed' | 'failed',
  progress: number, // 0-100
  results?: {
    summary: AnalysisSummary,
    screenshots: Screenshot[],
    accessibility: AccessibilityResults,
    ux: UXCritique,
    recommendations: Recommendation[]
  },
  createdAt: string,
  completedAt?: string
}
*/

GET /api/analyze/:id/report
/*
Return formatted HTML report for sharing/printing
*/

GET /api/analyze/:id/screenshots/:viewport
/*
Return screenshot image for specific viewport
*/
```

### Health & Status
```javascript
GET /api/health
/*
Response: {
  status: 'healthy' | 'degraded' | 'unhealthy',
  services: {
    database: boolean,
    puppeteer: boolean,
    claude: boolean,
    opencv: boolean
  },
  version: string
}
*/
```

---

## Database Schema

### SQLite Schema
```sql
-- Analysis tracking
CREATE TABLE analyses (
  id TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'processing',
  progress INTEGER DEFAULT 0,
  options TEXT, -- JSON string
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME,
  error_message TEXT
);

-- Screenshot storage metadata
CREATE TABLE screenshots (
  id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL,
  viewport TEXT NOT NULL, -- 'desktop', 'tablet', 'mobile'
  file_path TEXT NOT NULL,
  width INTEGER,
  height INTEGER,
  file_size INTEGER,
  FOREIGN KEY (analysis_id) REFERENCES analyses (id)
);

-- Analysis results
CREATE TABLE analysis_results (
  id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL,
  result_type TEXT NOT NULL, -- 'accessibility', 'ux', 'visual'
  result_data TEXT NOT NULL, -- JSON string
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (analysis_id) REFERENCES analyses (id)
);

-- Usage tracking for analytics
CREATE TABLE usage_stats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  analysis_id TEXT NOT NULL,
  url_domain TEXT,
  analysis_duration INTEGER, -- milliseconds
  viewports_analyzed INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (analysis_id) REFERENCES analyses (id)
);
```

---

## Frontend Components

### Main Analysis Interface
```jsx
// components/AnalysisForm.jsx
export function AnalysisForm() {
  /*
  Features:
  - URL input with validation
  - Viewport selection checkboxes
  - Analysis type radio buttons (Quick/Comprehensive)
  - Real-time analysis progress
  - Results preview when complete
  */
}

// components/AnalysisResults.jsx  
export function AnalysisResults({ analysisId }) {
  /*
  Display:
  - Screenshot carousel with viewport switcher
  - UX critique with expandable sections
  - Accessibility issues with severity levels
  - Downloadable report generation
  - Social sharing capabilities
  */
}

// components/ReportViewer.jsx
export function ReportViewer({ analysis }) {
  /*
  Comprehensive report view:
  - Executive summary with key metrics
  - Detailed findings by category
  - Before/after recommendations
  - Print-friendly formatting
  */
}
```

### Supporting Components
```jsx
// components/ScreenshotViewer.jsx
export function ScreenshotViewer({ screenshots }) {
  /*
  - Responsive image display
  - Viewport switching
  - Zoom/pan functionality
  - Annotation overlay support
  */
}

// components/CritiqueCard.jsx
export function CritiqueCard({ critique }) {
  /*
  - Priority level indicator
  - Expandable details
  - Code examples
  - Impact assessment
  */
}

// components/ProgressTracker.jsx
export function ProgressTracker({ progress, stage }) {
  /*
  Real-time progress display:
  - Screenshot capture: 25%
  - Accessibility scan: 50%
  - Visual analysis: 75%
  - AI critique: 100%
  */
}
```

---

## Configuration & Environment

### Environment Variables
```bash
# .env file structure
NODE_ENV=development
PORT=3000

# Database
DATABASE_URL=sqlite:./data/uxanalyst.db

# Claude AI
CLAUDE_API_KEY=your_claude_api_key_here
CLAUDE_MODEL=claude-3-sonnet-20240229

# Screenshot service
SCREENSHOT_STORAGE_PATH=./data/screenshots
MAX_SCREENSHOT_SIZE=10485760  # 10MB

# Analysis settings
MAX_CONCURRENT_ANALYSES=3
ANALYSIS_TIMEOUT_MS=300000    # 5 minutes
DEFAULT_VIEWPORT_WIDTH=1920
DEFAULT_VIEWPORT_HEIGHT=1080

# Rate limiting
RATE_LIMIT_WINDOW_MS=900000   # 15 minutes
RATE_LIMIT_MAX_REQUESTS=10

# Accessibility
AXE_RULES_CONFIG=./config/axe-rules.json
```

### Docker Configuration
```dockerfile
# Dockerfile
FROM node:18-alpine

# Install system dependencies for Puppeteer and OpenCV
RUN apk add --no-cache \
    chromium \
    nss \
    freetype \
    freetype-dev \
    harfbuzz \
    ca-certificates \
    ttf-freefont \
    python3 \
    make \
    g++

# Set Puppeteer to use installed Chromium
ENV PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium-browser

WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production

COPY . .
EXPOSE 3000

CMD ["npm", "start"]
```

---

## Analysis Flow Implementation

### Core Analysis Pipeline
```javascript
// Detailed implementation flow
class AnalysisPipeline {
  async execute(url, options) {
    const analysisId = generateId();
    
    try {
      // 1. Initialize analysis record
      await this.initializeAnalysis(analysisId, url, options);
      
      // 2. Capture screenshots (25% progress)
      const screenshots = await this.captureScreenshots(url, options.viewports);
      await this.updateProgress(analysisId, 25, 'Screenshots captured');
      
      // 3. Run accessibility scan (50% progress)  
      const accessibilityResults = await this.runAccessibilityScan(url);
      await this.updateProgress(analysisId, 50, 'Accessibility scan complete');
      
      // 4. Analyze visuals with CV (75% progress)
      const visualAnalysis = await this.analyzeVisuals(screenshots);
      await this.updateProgress(analysisId, 75, 'Visual analysis complete');
      
      // 5. Generate AI critique (100% progress)
      const aiCritique = await this.generateCritique({
        screenshots,
        accessibilityResults,
        visualAnalysis,
        url
      });
      
      // 6. Compile final report
      const report = await this.compileReport({
        screenshots,
        accessibilityResults,
        visualAnalysis,
        aiCritique
      });
      
      await this.finalizeAnalysis(analysisId, report);
      return { analysisId, status: 'completed' };
      
    } catch (error) {
      await this.handleAnalysisError(analysisId, error);
      throw error;
    }
  }
}
```

---

## Testing Requirements

### Unit Tests
```javascript
// Test coverage requirements
describe('Screenshot Service', () => {
  // Test URL validation
  // Test viewport handling
  // Test error scenarios
  // Test file storage
});

describe('Vision Analyzer', () => {
  // Test image processing
  // Test UI component detection
  // Test accessibility analysis
  // Test performance
});

describe('AI Critique Service', () => {
  // Test prompt generation
  // Test response parsing
  // Test error handling
  // Mock Claude API responses
});
```

### Integration Tests
```javascript
// End-to-end test scenarios
describe('Full Analysis Pipeline', () => {
  test('analyzes public website successfully', async () => {
    // Test with example.com
    // Verify all stages complete
    // Check report generation
  });
  
  test('handles invalid URLs gracefully', async () => {
    // Test error handling
    // Verify proper error messages
  });
  
  test('respects rate limiting', async () => {
    // Test concurrent request limits
  });
});
```

---

## MVP Deliverables

### Phase 1: Core Analysis (Week 1-2)
- [ ] Screenshot capture service with multiple viewports
- [ ] Basic OpenCV visual analysis 
- [ ] Axe-core accessibility scanning integration
- [ ] Claude AI critique generation
- [ ] SQLite database setup with core schema
- [ ] REST API with analysis endpoints
- [ ] Basic error handling and logging

### Phase 2: Frontend & Reports (Week 3-4)
- [ ] React frontend with analysis form
- [ ] Real-time progress tracking
- [ ] Screenshot viewer with viewport switching
- [ ] Critique display with categorization
- [ ] Downloadable HTML reports
- [ ] Basic responsive design
- [ ] Docker containerization

### Testing & Polish (Week 4)
- [ ] Unit test coverage >80%
- [ ] Integration tests for full pipeline
- [ ] Performance optimization
- [ ] Documentation and setup guides
- [ ] Production deployment preparation

---

## Future Roadmap

### Phase 3: Enhanced Features (Month 2)
- [ ] **Documentation Testing Integration** 
  - Parse documentation (markdown/HTML)
  - Execute step-by-step instructions
  - Validate docs against reality
  - Combined UX + docs analysis reports
- [ ] Competitive benchmarking
- [ ] Custom design system rules
- [ ] Team collaboration features
- [ ] Advanced visual analytics

### Phase 4: Scale & Integrate (Month 3)
- [ ] Figma plugin development
- [ ] GitHub PR integration
- [ ] Slack/Teams notifications
- [ ] Advanced AI model fine-tuning
- [ ] Performance monitoring dashboard

### Phase 5: Enterprise (Month 4+)
- [ ] Multi-tenant architecture
- [ ] SSO and enterprise auth
- [ ] Custom AI training
- [ ] On-premise deployment
- [ ] Advanced analytics and reporting

---

## Success Criteria

### MVP Success Metrics
- [ ] Successfully analyze 95% of public websites
- [ ] Generate meaningful UX critique within 2 minutes
- [ ] Identify 80%+ of common accessibility issues
- [ ] Provide actionable recommendations for improvements
- [ ] Handle concurrent analyses without performance degradation

### Technical Requirements
- [ ] API response time <5 seconds for analysis initiation
- [ ] Screenshot capture <30 seconds per viewport
- [ ] AI critique generation <60 seconds
- [ ] Support for modern browsers and responsive designs
- [ ] Graceful handling of edge cases and errors

This specification provides Claude Code with everything needed to build a production-ready MVP that you can immediately test on your own projects while setting up the foundation for the broader UX analysis platform.