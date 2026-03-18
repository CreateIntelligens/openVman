/**
 * Visual Blending Utilities
 * 
 * Handles ROI (Region of Interest) extraction and visual effects
 * for seamless lip-sync overlay on the avatar video.
 */

export interface ROIRegion {
    x: number;
    y: number;
    width: number;
    height: number;
}

export interface BlendConfig {
    /** ROI for mouth area */
    roi: ROIRegion;
    /** Feather radius for edge blending */
    featherRadius: number;
    /** Opacity of the overlay (0-1) */
    opacity: number;
}

/**
 * Default mouth ROI configuration
 * These values should be customized per avatar in manifest.json
 */
export const DEFAULT_MOUTH_ROI: ROIRegion = {
    x: 420,
    y: 1100,
    width: 240,
    height: 160
};

export const DEFAULT_BLEND_CONFIG: BlendConfig = {
    roi: DEFAULT_MOUTH_ROI,
    featherRadius: 20,
    opacity: 1.0
};

/**
 * Create a radial gradient for feathered edge blending
 */
export function createFeatheredMask(
    ctx: CanvasRenderingContext2D,
    roi: ROIRegion,
    featherRadius: number
): void {
    const { x, y, width, height } = roi;
    const centerX = x + width / 2;
    const centerY = y + height / 2;
    const radius = Math.max(width, height) / 2;

    // Create radial gradient from center
    const gradient = ctx.createRadialGradient(
        centerX, centerY, 0,
        centerX, centerY, radius + featherRadius
    );

    // Full opacity at center
    gradient.addColorStop(0, 'rgba(255, 255, 255, 1)');
    // Full opacity at inner edge
    gradient.addColorStop((radius - featherRadius) / (radius + featherRadius), 'rgba(255, 255, 255, 1)');
    // Transparent at outer edge (feathering)
    gradient.addColorStop(1, 'rgba(255, 255, 255, 0)');

    ctx.fillStyle = gradient;
    ctx.fillRect(x - featherRadius, y - featherRadius, width + featherRadius * 2, height + featherRadius * 2);
}

/**
 * Extract ROI from source canvas
 */
export function extractROI(
    sourceCtx: CanvasRenderingContext2D,
    roi: ROIRegion
): ImageData {
    return sourceCtx.getImageData(roi.x, roi.y, roi.width, roi.height);
}

/**
 * Apply ROI to destination canvas with blending
 */
export function applyROIWithBlend(
    destCtx: CanvasRenderingContext2D,
    sourceImageData: ImageData,
    roi: ROIRegion,
    blendConfig: BlendConfig
): void {
    const { x, y, width, height } = roi;

    // Create temporary canvas for the ROI content
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = width;
    tempCanvas.height = height;
    const tempCtx = tempCanvas.getContext('2d');

    if (!tempCtx) return;

    // Put the image data
    tempCtx.putImageData(sourceImageData, 0, 0);

    // Apply opacity
    destCtx.globalAlpha = blendConfig.opacity;

    // Draw with feathered mask
    // First, save context state
    destCtx.save();

    // Create clipping region for ROI
    destCtx.beginPath();
    destCtx.rect(x, y, width, height);
    destCtx.clip();

    // Draw the ROI content
    destCtx.drawImage(tempCanvas, x, y);

    // Apply feathering
    destCtx.globalCompositeOperation = 'destination-in';
    createFeatheredMask(destCtx, roi, blendConfig.featherRadius);

    // Restore context
    destCtx.restore();
    destCtx.globalAlpha = 1.0;
    destCtx.globalCompositeOperation = 'source-over';
}

/**
 * Create a simple rectangular mask (no feathering)
 */
export function applyROISimple(
    destCtx: CanvasRenderingContext2D,
    sourceImageData: ImageData,
    roi: ROIRegion,
    opacity: number = 1.0
): void {
    const { x, y, width, height } = roi;

    // Create temporary canvas
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = width;
    tempCanvas.height = height;
    const tempCtx = tempCanvas.getContext('2d');

    if (!tempCtx) return;

    tempCtx.putImageData(sourceImageData, 0, 0);

    destCtx.globalAlpha = opacity;
    destCtx.drawImage(tempCanvas, x, y);
    destCtx.globalAlpha = 1.0;
}

/**
 * Visual blending manager for lip-sync overlays
 */
export class VisualBlender {
    private config: BlendConfig;

    constructor(config: Partial<BlendConfig> = {}) {
        this.config = { ...DEFAULT_BLEND_CONFIG, ...config };
    }

    /**
     * Update blend configuration
     */
    setConfig(config: Partial<BlendConfig>): void {
        this.config = { ...this.config, ...config };
    }

    /**
     * Get current ROI
     */
    getROI(): ROIRegion {
        return this.config.roi;
    }

    /**
     * Apply blended overlay to canvas
     */
    blend(
        destCtx: CanvasRenderingContext2D,
        lipSyncFrame: ImageData
    ): void {
        applyROIWithBlend(destCtx, lipSyncFrame, this.config.roi, this.config);
    }

    /**
     * Apply simple (non-feathered) overlay
     */
    blendSimple(
        destCtx: CanvasRenderingContext2D,
        lipSyncFrame: ImageData
    ): void {
        applyROISimple(destCtx, lipSyncFrame, this.config.roi, this.config.opacity);
    }
}

export default VisualBlender;
