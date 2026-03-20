/**
 * Viseme Strategy Implementation
 * 
 * Uses the existing Viseme lookup table method
 * (6 mouth shape sprites)
 */

import type { LipSyncStrategy, AudioChunk, VisemeData } from './index';

export class VisemeStrategy implements LipSyncStrategy {
    readonly method = 'viseme' as const;
    readonly name = 'Viseme Lookup Table';

    private _isReady = false;
    private currentViseme: string = 'closed';
    private mouthSprites: Map<string, HTMLImageElement> = new Map();
    private canvas: HTMLCanvasElement | null = null;
    private ctx: CanvasRenderingContext2D | null = null;

    // Mouth sprite configuration (from manifest.json)
    private spriteConfig = {
        offset: { x: 420, y: 1100 },
        size: { w: 240, h: 160 }
    };

    async initialize(): Promise<void> {
        // Load mouth sprites
        await this.loadSprites();
        this._isReady = true;
    }

    private async loadSprites(): Promise<void> {
        const spriteNames = ['closed', 'A', 'E', 'I', 'O', 'U'];

        for (const name of spriteNames) {
            const img = new Image();
            // In a real implementation, these would be loaded from assets
            // For now, we'll create placeholder data URLs
            img.src = `data:image/svg+xml,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"240\" height=\"160\"><text x=\"120\" y=\"80\" text-anchor=\"middle\">${name}</text></svg>`;
            await new Promise<void>((resolve) => {
                img.onload = () => resolve();
                img.onerror = () => resolve(); // Continue even if fails
            });
            this.mouthSprites.set(name, img);
        }
    }

    async processAudio(chunk: AudioChunk): Promise<void> {
        // Viseme data is already provided by the server
        // We just need to store it for the render loop
    }

    /**
     * Update current viseme based on audio playback time
     */
    updateViseme(visemes: VisemeData[], currentTime: number): void {
        let activeViseme = visemes[0];

        for (let i = 0; i < visemes.length; i++) {
            if (currentTime >= visemes[i].time) {
                activeViseme = visemes[i];
            } else {
                break;
            }
        }

        this.currentViseme = activeViseme?.value || 'closed';
    }

    getCurrentFrame(): ImageData | null {
        if (!this.ctx || !this.canvas) return null;

        // Clear canvas
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw current mouth sprite
        const sprite = this.mouthSprites.get(this.currentViseme);
        if (sprite) {
            this.ctx.drawImage(
                sprite,
                this.spriteConfig.offset.x,
                this.spriteConfig.offset.y,
                this.spriteConfig.size.w,
                this.spriteConfig.size.h
            );
        }

        return this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height);
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
     * Update sprite configuration
     */
    setSpriteConfig(config: { offset: { x: number; y: number }; size: { w: number; h: number } }): void {
        this.spriteConfig = config;
    }

    dispose(): void {
        this.mouthSprites.clear();
        this._isReady = false;
    }
}

export default VisemeStrategy;
