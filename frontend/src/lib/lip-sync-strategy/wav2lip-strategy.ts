/**
 * Wav2Lip Strategy Implementation
 * 
 * Uses TensorFlow.js for AI-powered lip-sync
 */

import type { LipSyncStrategy, AudioChunk } from './index';
import type { LipSyncMethod, Wav2LipModel } from '../wav2lip';
import { createWav2LipModel } from '../wav2lip';

export class Wav2LipStrategy implements LipSyncStrategy {
    readonly method: LipSyncMethod;
    readonly name: string;

    private model: Wav2LipModel | null = null;
    private _isReady = false;
    private currentFrame: ImageData | null = null;
    private frames: ImageData[] = [];
    private frameIndex = 0;
    private canvas: HTMLCanvasElement | null = null;
    private ctx: CanvasRenderingContext2D | null = null;

    constructor(method: LipSyncMethod) {
        this.method = method;
        this.name = `Wav2Lip (${method})`;
    }

    async initialize(): Promise<void> {
        try {
            this.model = await createWav2LipModel(this.method);
            this._isReady = true;
        } catch (error) {
            console.error('Failed to initialize Wav2Lip:', error);
            throw error;
        }
    }

    async processAudio(chunk: AudioChunk): Promise<void> {
        if (!this.model) {
            throw new Error('Model not initialized');
        }

        // Generate frames from audio using Wav2Lip
        const result = await this.model.generate(chunk.audioBuffer);

        // Convert frames to ImageData for rendering
        this.frames = result.frames.map(f => f.imageData);
        this.frameIndex = 0;
    }

    /**
     * Advance to the next frame based on current audio time
     */
    advanceToFrame(audioTime: number, fps: number = 25): void {
        const targetFrame = Math.floor(audioTime * fps);
        if (targetFrame < this.frames.length) {
            this.frameIndex = targetFrame;
            this.currentFrame = this.frames[this.frameIndex];
        }
    }

    getCurrentFrame(): ImageData | null {
        return this.currentFrame;
    }

    isReady(): boolean {
        return this._isReady;
    }

    /**
     * Set the canvas for rendering
     */
    setCanvas(canvas: HTMLCanvasElement): void {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
    }

    /**
     * Render current frame to canvas with feathered blending
     */
    render(): void {
        if (!this.ctx || !this.canvas || !this.currentFrame) return;

        // Clear canvas (the canvas is usually transparent over the video)
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Create temporary canvas to render ImageData
        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = this.currentFrame.width;
        tempCanvas.height = this.currentFrame.height;
        const tempCtx = tempCanvas.getContext('2d');
        if (tempCtx) {
            tempCtx.putImageData(this.currentFrame, 0, 0);

            this.ctx.save();
            
            // Define ROI (Region of Interest) - center of the mouth region
            const cx = this.canvas.width / 2;
            const cy = this.canvas.height / 2;
            const radius = Math.min(this.canvas.width, this.canvas.height) / 2;

            // Apply Radial Gradient Feathering
            const gradient = this.ctx.createRadialGradient(
                cx, cy, radius * 0.5, // Inner radius (fully opaque)
                cx, cy, radius        // Outer radius (fully transparent)
            );
            gradient.addColorStop(0, 'rgba(0,0,0,1)');
            gradient.addColorStop(0.8, 'rgba(0,0,0,0.8)');
            gradient.addColorStop(1, 'rgba(0,0,0,0)');

            // Use the gradient as a mask
            this.ctx.beginPath();
            this.ctx.arc(cx, cy, radius, 0, Math.PI * 2);
            this.ctx.fillStyle = gradient;
            this.ctx.globalCompositeOperation = 'destination-in';
            
            // Draw the frame
            // Note: We Draw the image first then apply the mask operation
            this.ctx.globalCompositeOperation = 'source-over';
            this.ctx.drawImage(tempCanvas, 0, 0, this.canvas.width, this.canvas.height);
            
            // Overlay the mask
            const maskCanvas = document.createElement('canvas');
            maskCanvas.width = this.canvas.width;
            maskCanvas.height = this.canvas.height;
            const maskCtx = maskCanvas.getContext('2d');
            if (maskCtx) {
                maskCtx.fillStyle = gradient;
                maskCtx.fillRect(0, 0, maskCanvas.width, maskCanvas.height);
                
                this.ctx.globalCompositeOperation = 'destination-in';
                this.ctx.drawImage(maskCanvas, 0, 0);
            }

            this.ctx.restore();
        }
    }

    dispose(): void {
        if (this.model) {
            this.model.dispose();
            this.model = null;
        }
        this.frames = [];
        this.currentFrame = null;
        this._isReady = false;
    }
}

export default Wav2LipStrategy;
