/**
 * Lip Sync Manager
 * 
 * Main entry point for the adaptive lip-sync system.
 * Coordinates device detection, strategy selection, and rendering.
 */

import {
    detectAllCapabilities,
    determineDeviceTier,
    getRecommendedLipSyncMethod,
    type DeviceCapabilities,
    type DeviceTier
} from '../device-capabilities';
import {
    createLipSyncStrategy,
    getStrategyByTier,
    type LipSyncStrategy,
    type LipSyncMethod,
    type AudioChunk
} from '../lip-sync-strategy';
import { VideoSyncManager } from '../video-sync';

export interface LipSyncManagerConfig {
    /** Override automatic device detection */
    forcedMethod?: LipSyncMethod;
    /** Callback when method changes */
    onMethodChange?: (method: LipSyncMethod, tier: DeviceTier) => void;
    /** Callback for errors */
    onError?: (error: Error) => void;
}

export class LipSyncManager {
    private capabilities: DeviceCapabilities | null = null;
    private tier: DeviceTier = 'minimal';
    private method: LipSyncMethod = 'dinet';
    private strategy: LipSyncStrategy | null = null;
    private config: LipSyncManagerConfig;
    private isInitialized = false;

    // Audio context for decoding
    private audioContext: AudioContext | null = null;

    // Video sync and timing
    private syncManager: VideoSyncManager;
    private canvas: HTMLCanvasElement | null = null;
    private renderLoopId: number | null = null;

    // Callbacks for protocol
    private sendToServer: ((message: any) => void) | null = null;

    constructor(config: LipSyncManagerConfig = {}) {
        this.config = config;
        this.syncManager = new VideoSyncManager();
    }

    /**
     * Initialize the lip-sync manager
     */
    async initialize(): Promise<void> {
        if (this.isInitialized) return;

        try {
            // Detect device capabilities
            this.capabilities = await detectAllCapabilities();
            this.tier = determineDeviceTier(this.capabilities);

            // Determine lip-sync method
            if (this.config.forcedMethod) {
                this.method = this.config.forcedMethod;
            } else {
                this.method = getRecommendedLipSyncMethod(this.tier);
            }

            // Notify of method change
            this.config.onMethodChange?.(this.method, this.tier);

            // Create and initialize strategy
            this.strategy = await createLipSyncStrategy(this.method, this.tier);
            await this.strategy.initialize();

            this.isInitialized = true;
            console.log(`LipSync initialized: ${this.strategy.name} (tier: ${this.tier})`);
        } catch (error) {
            // Fallback to minimal on error
            console.warn('LipSync initialization failed, falling back to DINet (Edge Inference):', error);
            await this.fallbackToMinimal();
            this.config.onError?.(error as Error);
        }
    }

    /**
     * Fallback strategy
     */
    private async fallbackToMinimal(): Promise<void> {
        try {
            this.method = 'dinet';
            this.tier = 'minimal';

            this.strategy?.dispose();
            this.strategy = await createLipSyncStrategy('dinet', 'minimal');
            await this.strategy.initialize();

            this.config.onMethodChange?.(this.method, this.tier);
        } catch (error) {
            console.error('Failed to fallback:', error);
            throw error;
        }
    }

    /**
     * Set the canvas for rendering
     */
    setCanvas(canvas: HTMLCanvasElement): void {
        this.canvas = canvas;

        // Also set on strategy if applicable
        if (this.strategy) {
            // Type assertion for strategies that support canvas
            (this.strategy as { setCanvas?: (canvas: HTMLCanvasElement) => void }).setCanvas?.(canvas);
        }
    }

    /**
     * Set the video element for sync
     */
    setVideoElement(videoElement: HTMLVideoElement): void {
        this.syncManager.setVideoElement(videoElement);
    }

    /**
     * Process incoming audio chunk from WebSocket
     */
    async processAudioChunk(audioBase64: string, timestamp?: number): Promise<void> {
        if (!this.strategy || !this.audioContext) {
            throw new Error('LipSync not initialized');
        }

        // Decode audio from base64
        const audioBuffer = await this.decodeAudio(audioBase64);

        const chunk: AudioChunk = {
            audioBuffer,
            timestamp
        };

        await this.strategy.processAudio(chunk);

        // Notify server of mode (protocol optimization)
        this.notifyServerOfMode();
    }

    /**
     * Set the function to send messages to the server
     */
    setServerNotifier(notifier: (msg: any) => void): void {
        this.sendToServer = notifier;
        this.notifyServerOfMode();
    }

    /**
     * Notify server of the current lip-sync mode
     */
    private notifyServerOfMode(): void {
        if (this.sendToServer && this.isInitialized) {
            this.sendToServer({
                type: 'SET_LIP_SYNC_MODE',
                payload: {
                    mode: this.method,
                    need_visemes: false
                }
            });
        }
    }

    /**
     * Decode base64 audio to AudioBuffer
     */
    private async decodeAudio(base64: string): Promise<AudioBuffer> {
        if (!this.audioContext) {
            this.audioContext = new AudioContext();
        }

        // Convert base64 to ArrayBuffer
        const binaryString = atob(base64);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i);
        }

        return this.audioContext.decodeAudioData(bytes.buffer);
    }

    /**
     * Start the render loop
     */
    startRenderLoop(): void {
        if (this.renderLoopId !== null) return;

        const render = () => {
            if (this.syncManager.active && this.canvas) {
                this.render();
            }
            this.renderLoopId = requestAnimationFrame(render);
        };

        this.renderLoopId = requestAnimationFrame(render);
    }

    /**
     * Stop the render loop
     */
    stopRenderLoop(): void {
        if (this.renderLoopId !== null) {
            cancelAnimationFrame(this.renderLoopId);
            this.renderLoopId = null;
        }
    }

    /**
     * Render current frame
     */
    private render(): void {
        if (!this.strategy || !this.canvas || !this.ctx) return;

        const currentTime = this.getCurrentAudioTime();

        // Different strategies handle rendering differently
        if (this.method === 'wav2lip' || this.method === 'dinet') {
            // Advance frame based on time
            (this.strategy as { advanceToFrame?: (time: number) => void }).advanceToFrame?.(currentTime);
            (this.strategy as { render?: () => void }).render?.();
        } else if (this.method === 'webgl') {
            // WebGL rendering would happen on a separate canvas or WebGL context entirely, usually bypassed here.
            (this.strategy as { render?: (time: number) => void }).render?.(currentTime);
        }

        // Get frame and render to canvas
        const frame = this.strategy.getCurrentFrame();
        if (frame && this.ctx) {
            this.ctx.putImageData(frame, 0, 0);
        }
    }

    /**
     * Get current audio playback time using VideoSyncManager
     */
    private getCurrentAudioTime(): number {
        return this.syncManager.getCurrentTime();
    }

    /**
     * Get canvas context
     */
    private get ctx(): CanvasRenderingContext2D | null {
        return this.canvas?.getContext('2d') ?? null;
    }

    /**
     * Start playback
     */
    play(): void {
        this.syncManager.start();
        this.startRenderLoop();
    }

    /**
     * Pause playback
     */
    pause(): void {
        this.syncManager.stop();
    }

    /**
     * Stop playback
     */
    stop(): void {
        this.syncManager.stop();
        this.syncManager.seek(0);
        this.stopRenderLoop();
    }

    /**
     * Get current method
     */
    getMethod(): LipSyncMethod {
        return this.method;
    }

    /**
     * Get device tier
     */
    getTier(): DeviceTier {
        return this.tier;
    }

    /**
     * Get device capabilities
     */
    getCapabilities(): DeviceCapabilities | null {
        return this.capabilities;
    }

    /**
     * Check if initialized
     */
    get initialized(): boolean {
        return this.isInitialized;
    }

    /**
     * Manually switch to a different method
     */
    async switchMethod(method: LipSyncMethod): Promise<void> {
        if (this.method === method) return;

        try {
            this.method = method;
            this.strategy?.dispose();

            this.strategy = await createLipSyncStrategy(method, this.tier);
            await this.strategy.initialize();

            if (this.canvas) {
                (this.strategy as { setCanvas?: (canvas: HTMLCanvasElement) => void }).setCanvas?.(this.canvas);
            }

            this.config.onMethodChange?.(this.method, this.tier);
        } catch (error) {
            console.error('Failed to switch method:', error);
            this.config.onError?.(error as Error);
        }
    }

    /**
     * Clean up resources
     */
    dispose(): void {
        this.stopRenderLoop();
        this.strategy?.dispose();
        this.audioContext?.close();
        this.strategy = null;
        this.audioContext = null;
        this.isInitialized = false;
    }
}

export default LipSyncManager;
