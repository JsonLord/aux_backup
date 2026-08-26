const sharp = require('sharp');
const fs = require('fs').promises;
const path = require('path');

class VisualDesignAnalyzer {
  constructor() {
    this.colorThresholds = {
      lowContrast: 3.0,
      normalContrast: 4.5,
      highContrast: 7.0
    };

    this.layoutThresholds = {
      minWhitespace: 0.15, // 15% minimum whitespace
      maxContentDensity: 0.7, // 70% max content density
      minTouchTargetSize: 44 // 44px minimum touch target
    };
  }

  async analyzeVisualDesign(screenshotPath, viewport = 'desktop') {
    try {
      const imageBuffer = await fs.readFile(screenshotPath);
      const image = sharp(imageBuffer);
      const metadata = await image.metadata();

      const analysis = {
        viewport,
        dimensions: {
          width: metadata.width,
          height: metadata.height
        },
        colorAnalysis: await this.analyzeColors(image, imageBuffer),
        layoutAnalysis: await this.analyzeLayout(image, metadata),
        typographyAnalysis: await this.analyzeTypography(imageBuffer),
        spacingAnalysis: await this.analyzeSpacing(image, metadata),
        visualHierarchy: await this.analyzeVisualHierarchy(imageBuffer),
        issues: [],
        score: 0
      };

      // Calculate overall visual design score
      analysis.score = this.calculateVisualScore(analysis);

      // Identify issues
      analysis.issues = this.identifyVisualIssues(analysis);

      return analysis;

    } catch (error) {
      console.error('Visual design analysis error:', error);
      throw new Error(`Failed to analyze visual design: ${error.message}`);
    }
  }

  async analyzeColors(image, imageBuffer) {
    try {
      // Extract dominant colors
      const { dominant } = await image.stats();

      // Get color palette using histogram analysis
      const colorPalette = await this.extractColorPalette(imageBuffer);

      // Analyze contrast ratios (simplified approach)
      const contrastAnalysis = await this.analyzeContrast(imageBuffer);

      return {
        dominantColor: {
          r: Math.round(dominant.r),
          g: Math.round(dominant.g),
          b: Math.round(dominant.b)
        },
        colorPalette,
        contrastRatios: contrastAnalysis,
        colorHarmony: this.assessColorHarmony(colorPalette),
        accessibility: this.assessColorAccessibility(contrastAnalysis)
      };

    } catch (error) {
      console.error('Color analysis error:', error);
      return {
        dominantColor: { r: 0, g: 0, b: 0 },
        colorPalette: [],
        contrastRatios: { average: 0, minimum: 0, maximum: 0 },
        colorHarmony: 'unknown',
        accessibility: 'poor'
      };
    }
  }

  async extractColorPalette(imageBuffer) {
    // Simplified color extraction - in production, you'd use more sophisticated algorithms
    try {
      const image = sharp(imageBuffer);

      // Resize for faster processing
      const smallImage = await image.resize(100, 100).raw().toBuffer();
      const colors = new Map();

      // Ensure we have a valid buffer
      if (!smallImage || smallImage.length === 0) {
        return [];
      }

      // Sample every 4th pixel for performance
      for (let i = 0; i < smallImage.length - 2; i += 12) {
        const r = smallImage[i] || 0;
        const g = smallImage[i + 1] || 0;
        const b = smallImage[i + 2] || 0;

        // Group similar colors
        const colorKey = `${Math.floor(r/32)*32},${Math.floor(g/32)*32},${Math.floor(b/32)*32}`;
        colors.set(colorKey, (colors.get(colorKey) || 0) + 1);
      }

      // Return top 5 colors
      const entries = Array.from(colors.entries() || []);
      return entries
        .sort(([,a], [,b]) => b - a)
        .slice(0, 5)
        .map(([color, count]) => {
          const [r, g, b] = color.split(',').map(Number);
          return {
            color: { r, g, b },
            frequency: count,
            hex: this.rgbToHex(r, g, b)
          };
        });

    } catch (error) {
      console.error('Color palette extraction error:', error);
      return [];
    }
  }

  async analyzeContrast(imageBuffer) {
    // Simplified contrast analysis
    try {
      const image = sharp(imageBuffer);
      const { channels } = await image.stats();

      // Calculate luminance variance as a proxy for contrast
      const luminanceVariance = channels.reduce((sum, channel) => {
        return sum + (channel.max - channel.min);
      }, 0) / channels.length;

      const normalizedContrast = Math.min(luminanceVariance / 255 * 10, 10);

      return {
        average: normalizedContrast,
        minimum: normalizedContrast * 0.7,
        maximum: normalizedContrast * 1.3,
        assessment: this.assessContrastLevel(normalizedContrast)
      };

    } catch (error) {
      console.error('Contrast analysis error:', error);
      return {
        average: 0,
        minimum: 0,
        maximum: 0,
        assessment: 'poor'
      };
    }
  }

  async analyzeLayout(image, metadata) {
    try {
      // Analyze layout using edge detection and region analysis
      const edgeImage = await image
        .greyscale()
        .convolve({
          width: 3,
          height: 3,
          kernel: [-1, -1, -1, -1, 8, -1, -1, -1, -1]
        })
        .raw()
        .toBuffer();

      const layoutMetrics = this.calculateLayoutMetrics(edgeImage, metadata);

      return {
        whitespaceRatio: layoutMetrics.whitespace,
        contentDensity: layoutMetrics.density,
        symmetry: layoutMetrics.symmetry,
        balance: layoutMetrics.balance,
        gridAlignment: layoutMetrics.gridAlignment,
        assessment: this.assessLayout(layoutMetrics)
      };

    } catch (error) {
      console.error('Layout analysis error:', error);
      return {
        whitespaceRatio: 0,
        contentDensity: 0,
        symmetry: 0,
        balance: 0,
        gridAlignment: 0,
        assessment: 'poor'
      };
    }
  }

  calculateLayoutMetrics(edgeBuffer, metadata) {
    const totalPixels = metadata.width * metadata.height;
    let edgePixels = 0;

    // Count edge pixels (simplified)
    for (let i = 0; i < edgeBuffer.length; i++) {
      if (edgeBuffer[i] > 50) edgePixels++;
    }

    const contentDensity = edgePixels / totalPixels;
    const whitespaceRatio = 1 - contentDensity;

    // Simplified symmetry calculation
    const symmetry = this.calculateSymmetry(edgeBuffer, metadata.width, metadata.height);

    return {
      whitespace: whitespaceRatio,
      density: contentDensity,
      symmetry: symmetry,
      balance: (symmetry + whitespaceRatio) / 2,
      gridAlignment: this.estimateGridAlignment(edgeBuffer, metadata.width, metadata.height)
    };
  }

  calculateSymmetry(buffer, width, height) {
    // Calculate horizontal symmetry
    let symmetryScore = 0;
    const halfWidth = Math.floor(width / 2);

    for (let y = 0; y < height; y++) {
      for (let x = 0; x < halfWidth; x++) {
        const leftPixel = buffer[y * width + x];
        const rightPixel = buffer[y * width + (width - 1 - x)];
        const diff = Math.abs(leftPixel - rightPixel);
        symmetryScore += (255 - diff) / 255;
      }
    }

    return symmetryScore / (halfWidth * height);
  }

  estimateGridAlignment(buffer, width, height) {
    // Simplified grid alignment detection
    const gridSize = 20; // 20px grid
    let alignmentScore = 0;
    let totalChecks = 0;

    for (let y = gridSize; y < height; y += gridSize) {
      for (let x = gridSize; x < width; x += gridSize) {
        const pixelIndex = y * width + x;
        if (pixelIndex < buffer.length) {
          alignmentScore += buffer[pixelIndex] > 50 ? 1 : 0;
          totalChecks++;
        }
      }
    }

    return totalChecks > 0 ? alignmentScore / totalChecks : 0;
  }

  async analyzeTypography(imageBuffer) {
    // Simplified typography analysis
    try {
      const image = sharp(imageBuffer);

      // Convert to grayscale and apply text detection filters
      const textRegions = await this.detectTextRegions(image);

      return {
        textRegions: textRegions.length,
        estimatedFontSizes: this.estimateFontSizes(textRegions),
        readabilityScore: this.calculateReadabilityScore(textRegions),
        hierarchy: this.analyzeTextHierarchy(textRegions)
      };

    } catch (error) {
      console.error('Typography analysis error:', error);
      return {
        textRegions: 0,
        estimatedFontSizes: [],
        readabilityScore: 0,
        hierarchy: 'poor'
      };
    }
  }

  async detectTextRegions(image) {
    // Simplified text region detection using morphological operations
    try {
      const textImage = await image
        .greyscale()
        .threshold(128)
        .raw()
        .toBuffer();

      // Find connected components that might be text
      const regions = this.findConnectedComponents(textImage);

      return regions.filter(region => this.isLikelyText(region));

    } catch (error) {
      console.error('Text region detection error:', error);
      return [];
    }
  }

  findConnectedComponents(buffer) {
    // Simplified connected component analysis
    const regions = [];
    const visited = new Set();
    const width = Math.sqrt(buffer.length); // Assuming square for simplicity

    for (let i = 0; i < buffer.length; i++) {
      if (buffer[i] > 0 && !visited.has(i)) {
        const region = this.floodFill(buffer, i, width, visited);
        if (region.size > 10) { // Minimum region size
          regions.push({
            size: region.size,
            bounds: this.calculateBounds(region, width)
          });
        }
      }
    }

    return regions;
  }

  floodFill(buffer, start, width, visited) {
    const region = new Set();
    const stack = [start];
    const MAX_REGION_SIZE = 50000; // Prevent Set overflow
    const MAX_VISITED_SIZE = 100000; // Prevent visited Set overflow

    while (stack.length > 0 && region.size < MAX_REGION_SIZE && visited.size < MAX_VISITED_SIZE) {
      const current = stack.pop();
      if (visited.has(current) || buffer[current] === 0) continue;

      // Check visited size before adding
      if (visited.size < MAX_VISITED_SIZE) {
        visited.add(current);
      }

      if (region.size < MAX_REGION_SIZE) {
        region.add(current);
      }

      // Add neighbors only if we haven't hit limits
      if (visited.size < MAX_VISITED_SIZE && region.size < MAX_REGION_SIZE) {
        const neighbors = [
          current - 1, current + 1,
          current - width, current + width
        ];

        neighbors.forEach(neighbor => {
          if (neighbor >= 0 && neighbor < buffer.length && !visited.has(neighbor)) {
            stack.push(neighbor);
          }
        });
      }
    }

    return region;
  }

  calculateBounds(region, width) {
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;

    for (const pixel of region) {
      const x = pixel % width;
      const y = Math.floor(pixel / width);

      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    }

    return { minX, maxX, minY, maxY, width: maxX - minX, height: maxY - minY };
  }

  isLikelyText(region) {
    const { width, height } = region.bounds;
    const aspectRatio = width / height;

    // Text regions typically have certain aspect ratios
    return aspectRatio > 0.1 && aspectRatio < 20 && width > 5 && height > 5;
  }

  estimateFontSizes(textRegions) {
    return textRegions.map(region => {
      // Estimate font size based on region height
      const estimatedSize = Math.round(region.bounds.height * 0.75);
      return {
        estimatedSize,
        region: region.bounds,
        category: this.categorizeFontSize(estimatedSize)
      };
    });
  }

  categorizeFontSize(size) {
    if (size < 12) return 'small';
    if (size < 16) return 'normal';
    if (size < 24) return 'large';
    return 'heading';
  }

  calculateReadabilityScore(textRegions) {
    if (textRegions.length === 0) return 0;

    let score = 0;
    textRegions.forEach(region => {
      const { width, height } = region.bounds;
      const aspectRatio = width / height;

      // Good readability indicators
      if (height >= 12) score += 0.3; // Minimum readable size
      if (aspectRatio > 2 && aspectRatio < 15) score += 0.4; // Good line aspect ratio
      if (region.size > 100) score += 0.3; // Sufficient text area
    });

    return Math.min(score / textRegions.length, 1);
  }

  analyzeTextHierarchy(textRegions) {
    const sizes = textRegions.map(r => r.bounds.height).sort((a, b) => b - a);
    const uniqueSizes = [...new Set(sizes)];

    if (uniqueSizes.length >= 3) return 'good';
    if (uniqueSizes.length === 2) return 'fair';
    return 'poor';
  }

  async analyzeSpacing(image, metadata) {
    try {
      // Analyze whitespace distribution
      const spacingMetrics = await this.calculateSpacingMetrics(image, metadata);

      return {
        verticalSpacing: spacingMetrics.vertical,
        horizontalSpacing: spacingMetrics.horizontal,
        consistency: spacingMetrics.consistency,
        balance: spacingMetrics.balance
      };

    } catch (error) {
      console.error('Spacing analysis error:', error);
      return {
        verticalSpacing: 0,
        horizontalSpacing: 0,
        consistency: 0,
        balance: 0
      };
    }
  }

  async calculateSpacingMetrics(image, metadata) {
    // Simplified spacing analysis
    const edgeImage = await image
      .greyscale()
      .blur(1)
      .threshold(200)
      .raw()
      .toBuffer();

    const verticalSpaces = this.analyzeVerticalSpacing(edgeImage, metadata.width, metadata.height);
    const horizontalSpaces = this.analyzeHorizontalSpacing(edgeImage, metadata.width, metadata.height);

    return {
      vertical: verticalSpaces.average,
      horizontal: horizontalSpaces.average,
      consistency: (verticalSpaces.consistency + horizontalSpaces.consistency) / 2,
      balance: this.calculateSpacingBalance(verticalSpaces, horizontalSpaces)
    };
  }

  analyzeVerticalSpacing(buffer, width, height) {
    const rowSums = [];

    for (let y = 0; y < height; y++) {
      let rowSum = 0;
      for (let x = 0; x < width; x++) {
        rowSum += buffer[y * width + x];
      }
      rowSums.push(rowSum / width);
    }

    const spaces = this.findSpaces(rowSums);
    return this.calculateSpaceMetrics(spaces);
  }

  analyzeHorizontalSpacing(buffer, width, height) {
    const colSums = [];

    for (let x = 0; x < width; x++) {
      let colSum = 0;
      for (let y = 0; y < height; y++) {
        colSum += buffer[y * width + x];
      }
      colSums.push(colSum / height);
    }

    const spaces = this.findSpaces(colSums);
    return this.calculateSpaceMetrics(spaces);
  }

  findSpaces(values) {
    const spaces = [];
    let spaceStart = -1;
    const threshold = 200; // Whitespace threshold

    for (let i = 0; i < values.length; i++) {
      if (values[i] > threshold && spaceStart === -1) {
        spaceStart = i;
      } else if (values[i] <= threshold && spaceStart !== -1) {
        spaces.push(i - spaceStart);
        spaceStart = -1;
      }
    }

    return spaces.filter(space => space > 5); // Minimum space size
  }

  calculateSpaceMetrics(spaces) {
    if (spaces.length === 0) {
      return { average: 0, consistency: 0 };
    }

    const average = spaces.reduce((sum, space) => sum + space, 0) / spaces.length;
    const variance = spaces.reduce((sum, space) => sum + Math.pow(space - average, 2), 0) / spaces.length;
    const consistency = Math.max(0, 1 - (Math.sqrt(variance) / average));

    return { average, consistency };
  }

  calculateSpacingBalance(vertical, horizontal) {
    const ratio = Math.min(vertical.average, horizontal.average) / Math.max(vertical.average, horizontal.average);
    return ratio * ((vertical.consistency + horizontal.consistency) / 2);
  }

  async analyzeVisualHierarchy(imageBuffer) {
    try {
      // Analyze visual weight distribution
      const image = sharp(imageBuffer);
      const hierarchyMetrics = await this.calculateHierarchyMetrics(image);

      return {
        clarity: hierarchyMetrics.clarity,
        contrast: hierarchyMetrics.contrast,
        progression: hierarchyMetrics.progression,
        focusPoints: hierarchyMetrics.focusPoints
      };

    } catch (error) {
      console.error('Visual hierarchy analysis error:', error);
      return {
        clarity: 0,
        contrast: 0,
        progression: 0,
        focusPoints: 0
      };
    }
  }

  async calculateHierarchyMetrics(image) {
    // Apply visual saliency detection
    const saliencyMap = await this.generateSaliencyMap(image);

    return {
      clarity: this.assessHierarchyClarity(saliencyMap),
      contrast: this.assessVisualContrast(saliencyMap),
      progression: this.assessVisualProgression(saliencyMap),
      focusPoints: this.countFocusPoints(saliencyMap)
    };
  }

  async generateSaliencyMap(image) {
    // Simplified saliency detection using edge detection and contrast
    const saliencyBuffer = await image
      .greyscale()
      .convolve({
        width: 3,
        height: 3,
        kernel: [-1, -2, -1, 0, 0, 0, 1, 2, 1]
      })
      .raw()
      .toBuffer();

    return saliencyBuffer;
  }

  assessHierarchyClarity(saliencyMap) {
    if (!saliencyMap || saliencyMap.length === 0) return 0;

    // Calculate distribution of visual attention
    const histogram = new Array(256).fill(0);

    for (let i = 0; i < saliencyMap.length; i++) {
      const value = Math.max(0, Math.min(255, Math.floor(saliencyMap[i])));
      histogram[value]++;
    }

    // Good hierarchy has clear peaks and valleys
    const peaks = this.findPeaks(histogram);
    return Math.min(peaks.length / 5, 1); // Normalize to 0-1
  }

  assessVisualContrast(saliencyMap) {
    if (!saliencyMap || saliencyMap.length === 0) return 0;

    let max = 0;
    let min = 255;

    for (let i = 0; i < saliencyMap.length; i++) {
      if (saliencyMap[i] > max) max = saliencyMap[i];
      if (saliencyMap[i] < min) min = saliencyMap[i];
    }

    return (max - min) / 255;
  }

  assessVisualProgression(saliencyMap) {
    // Analyze if visual elements create a logical flow
    const quadrants = this.divideIntoQuadrants(saliencyMap);
    const progression = this.calculateProgression(quadrants);
    return progression;
  }

  countFocusPoints(saliencyMap) {
    if (!saliencyMap || saliencyMap.length === 0) return 0;

    // Count distinct areas of high visual interest
    const threshold = 200;
    let focusCount = 0;

    for (let i = 0; i < saliencyMap.length; i++) {
      if (saliencyMap[i] > threshold) focusCount++;
    }

    return Math.min(focusCount / saliencyMap.length * 10, 1);
  }

  findPeaks(histogram) {
    const peaks = [];
    for (let i = 1; i < histogram.length - 1; i++) {
      if (histogram[i] > histogram[i-1] && histogram[i] > histogram[i+1] && histogram[i] > 100) {
        peaks.push(i);
      }
    }
    return peaks;
  }

  divideIntoQuadrants(buffer) {
    const size = Math.sqrt(buffer.length);
    const halfSize = Math.floor(size / 2);
    const quadrants = [[], [], [], []];

    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const index = y * size + x;
        const quadrant = (y < halfSize ? 0 : 2) + (x < halfSize ? 0 : 1);
        quadrants[quadrant].push(buffer[index]);
      }
    }

    return quadrants.map(q => q.reduce((sum, val) => sum + val, 0) / q.length);
  }

  calculateProgression(quadrants) {
    // Check for visual flow patterns (simplified)
    const patterns = [
      [0, 1, 2, 3], // Z-pattern
      [0, 2, 1, 3], // F-pattern
      [1, 0, 3, 2]  // Reverse Z
    ];

    let bestScore = 0;
    for (const pattern of patterns) {
      let score = 0;
      for (let i = 0; i < pattern.length - 1; i++) {
        const current = quadrants[pattern[i]];
        const next = quadrants[pattern[i + 1]];
        if (current >= next) score += 0.25;
      }
      bestScore = Math.max(bestScore, score);
    }

    return bestScore;
  }

  calculateVisualScore(analysis) {
    const weights = {
      color: 0.25,
      layout: 0.25,
      typography: 0.20,
      spacing: 0.15,
      hierarchy: 0.15
    };

    const scores = {
      color: this.scoreColorAnalysis(analysis.colorAnalysis),
      layout: this.scoreLayoutAnalysis(analysis.layoutAnalysis),
      typography: this.scoreTypographyAnalysis(analysis.typographyAnalysis),
      spacing: this.scoreSpacingAnalysis(analysis.spacingAnalysis),
      hierarchy: this.scoreHierarchyAnalysis(analysis.visualHierarchy)
    };

    return Object.entries(weights).reduce((total, [key, weight]) => {
      return total + (scores[key] * weight);
    }, 0) * 100; // Convert to 0-100 scale
  }

  scoreColorAnalysis(colorAnalysis) {
    let score = 0;

    // Color harmony
    if (colorAnalysis.colorHarmony === 'excellent') score += 0.4;
    else if (colorAnalysis.colorHarmony === 'good') score += 0.3;
    else if (colorAnalysis.colorHarmony === 'fair') score += 0.2;

    // Contrast
    if (colorAnalysis.contrastRatios.average > this.colorThresholds.highContrast) score += 0.4;
    else if (colorAnalysis.contrastRatios.average > this.colorThresholds.normalContrast) score += 0.3;
    else if (colorAnalysis.contrastRatios.average > this.colorThresholds.lowContrast) score += 0.1;

    // Accessibility
    if (colorAnalysis.accessibility === 'excellent') score += 0.2;
    else if (colorAnalysis.accessibility === 'good') score += 0.15;
    else if (colorAnalysis.accessibility === 'fair') score += 0.1;

    return Math.min(score, 1);
  }

  scoreLayoutAnalysis(layoutAnalysis) {
    let score = 0;

    // Whitespace
    if (layoutAnalysis.whitespaceRatio >= this.layoutThresholds.minWhitespace) score += 0.3;

    // Content density
    if (layoutAnalysis.contentDensity <= this.layoutThresholds.maxContentDensity) score += 0.2;

    // Balance and symmetry
    score += layoutAnalysis.balance * 0.25;
    score += layoutAnalysis.symmetry * 0.25;

    return Math.min(score, 1);
  }

  scoreTypographyAnalysis(typographyAnalysis) {
    let score = 0;

    // Readability
    score += typographyAnalysis.readabilityScore * 0.4;

    // Hierarchy
    if (typographyAnalysis.hierarchy === 'good') score += 0.4;
    else if (typographyAnalysis.hierarchy === 'fair') score += 0.2;

    // Text regions presence
    if (typographyAnalysis.textRegions > 0) score += 0.2;

    return Math.min(score, 1);
  }

  scoreSpacingAnalysis(spacingAnalysis) {
    let score = 0;

    score += spacingAnalysis.consistency * 0.4;
    score += spacingAnalysis.balance * 0.3;
    score += Math.min(spacingAnalysis.verticalSpacing / 50, 1) * 0.15;
    score += Math.min(spacingAnalysis.horizontalSpacing / 50, 1) * 0.15;

    return Math.min(score, 1);
  }

  scoreHierarchyAnalysis(hierarchyAnalysis) {
    let score = 0;

    score += hierarchyAnalysis.clarity * 0.3;
    score += hierarchyAnalysis.contrast * 0.3;
    score += hierarchyAnalysis.progression * 0.2;
    score += hierarchyAnalysis.focusPoints * 0.2;

    return Math.min(score, 1);
  }

  identifyVisualIssues(analysis) {
    const issues = [];

    // Color issues
    if (analysis.colorAnalysis.contrastRatios.average < this.colorThresholds.normalContrast) {
      issues.push({
        category: 'Color',
        severity: 'High',
        description: 'Low color contrast detected',
        recommendation: 'Increase contrast between text and background colors to meet WCAG AA standards (4.5:1 ratio)',
        location: 'Global'
      });
    }

    if (analysis.colorAnalysis.accessibility === 'poor') {
      issues.push({
        category: 'Color',
        severity: 'High',
        description: 'Poor color accessibility',
        recommendation: 'Ensure color is not the only means of conveying information',
        location: 'Global'
      });
    }

    // Layout issues
    if (analysis.layoutAnalysis.whitespaceRatio < this.layoutThresholds.minWhitespace) {
      issues.push({
        category: 'Layout',
        severity: 'Medium',
        description: 'Insufficient whitespace',
        recommendation: 'Increase spacing between elements to improve visual breathing room',
        location: 'Global'
      });
    }

    if (analysis.layoutAnalysis.contentDensity > this.layoutThresholds.maxContentDensity) {
      issues.push({
        category: 'Layout',
        severity: 'Medium',
        description: 'Content is too dense',
        recommendation: 'Reduce content density or reorganize layout for better scanability',
        location: 'Global'
      });
    }

    // Typography issues
    if (analysis.typographyAnalysis.readabilityScore < 0.5) {
      issues.push({
        category: 'Typography',
        severity: 'High',
        description: 'Poor text readability',
        recommendation: 'Increase font size, improve line spacing, or enhance text contrast',
        location: 'Text elements'
      });
    }

    if (analysis.typographyAnalysis.hierarchy === 'poor') {
      issues.push({
        category: 'Typography',
        severity: 'Medium',
        description: 'Weak typographic hierarchy',
        recommendation: 'Create clearer distinction between heading levels and body text',
        location: 'Text elements'
      });
    }

    // Spacing issues
    if (analysis.spacingAnalysis.consistency < 0.5) {
      issues.push({
        category: 'Spacing',
        severity: 'Medium',
        description: 'Inconsistent spacing',
        recommendation: 'Establish and maintain consistent spacing patterns throughout the design',
        location: 'Global'
      });
    }

    // Visual hierarchy issues
    if (analysis.visualHierarchy.clarity < 0.4) {
      issues.push({
        category: 'Visual Hierarchy',
        severity: 'High',
        description: 'Unclear visual hierarchy',
        recommendation: 'Strengthen visual hierarchy through size, color, and positioning',
        location: 'Global'
      });
    }

    return issues;
  }

  assessColorHarmony(colorPalette) {
    if (colorPalette.length < 2) return 'insufficient';

    // Simplified harmony assessment based on color relationships
    const harmony = this.calculateColorHarmony(colorPalette);

    if (harmony > 0.8) return 'excellent';
    if (harmony > 0.6) return 'good';
    if (harmony > 0.4) return 'fair';
    return 'poor';
  }

  calculateColorHarmony(colorPalette) {
    // Simplified harmony calculation based on hue relationships
    const hues = colorPalette.map(c => this.rgbToHsl(c.color.r, c.color.g, c.color.b).h);

    let harmonyScore = 0;
    const relationships = [60, 120, 180]; // Complementary, triadic, etc.

    for (let i = 0; i < hues.length - 1; i++) {
      for (let j = i + 1; j < hues.length; j++) {
        const diff = Math.abs(hues[i] - hues[j]);
        const normalizedDiff = Math.min(diff, 360 - diff);

        for (const relationship of relationships) {
          if (Math.abs(normalizedDiff - relationship) < 30) {
            harmonyScore += 0.3;
          }
        }
      }
    }

    return Math.min(harmonyScore, 1);
  }

  assessColorAccessibility(contrastAnalysis) {
    if (contrastAnalysis.average >= this.colorThresholds.highContrast) return 'excellent';
    if (contrastAnalysis.average >= this.colorThresholds.normalContrast) return 'good';
    if (contrastAnalysis.average >= this.colorThresholds.lowContrast) return 'fair';
    return 'poor';
  }

  assessContrastLevel(contrast) {
    if (contrast >= 7) return 'high';
    if (contrast >= 4.5) return 'normal';
    if (contrast >= 3) return 'low';
    return 'poor';
  }

  assessLayout(layoutMetrics) {
    const score = (layoutMetrics.whitespace + layoutMetrics.balance + layoutMetrics.symmetry) / 3;

    if (score >= 0.8) return 'excellent';
    if (score >= 0.6) return 'good';
    if (score >= 0.4) return 'fair';
    return 'poor';
  }

  // Utility functions
  rgbToHex(r, g, b) {
    return "#" + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
  }

  rgbToHsl(r, g, b) {
    r /= 255;
    g /= 255;
    b /= 255;

    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    let h, s, l = (max + min) / 2;

    if (max === min) {
      h = s = 0;
    } else {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);

      switch (max) {
        case r: h = (g - b) / d + (g < b ? 6 : 0); break;
        case g: h = (b - r) / d + 2; break;
        case b: h = (r - g) / d + 4; break;
      }

      h /= 6;
    }

    return { h: h * 360, s: s * 100, l: l * 100 };
  }
}

module.exports = VisualDesignAnalyzer;