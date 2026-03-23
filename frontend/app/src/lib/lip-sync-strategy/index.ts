/**
 * Lip Sync Strategy Interface
 * 
 * Defines the contract for different lip-sync methods
 * (Wav2Lip, DINet, WebGL)
 */

import type { DeviceTier } from '../device-capabilities';

export type LipSyncMethod = 'wav2lip' | 'dinet' | 'webgl';

export interface AudioChunk {
    audioBuffer: AudioBuffer;
    timestamp?: number;
    text?: string;
}

export interface LipSyncStrategy {
    /** Unique identifier for this strategy */
    readonly method: LipSyncMethod;

    /** Human-readable name */
    readonly name: string;

    /** Initialize the strategy (load models, etc.) */
    initialize(): Promise<void>;

    /** Process audio chunk and generate lip-sync frames/data */
    processAudio(chunk: AudioChunk): Promise<void>;

    /** Get current frame for rendering (if applicable) */
    getCurrentFrame(): ImageData | null;

    /** Check if strategy is ready */
    isReady(): boolean;

    /** Clean up resources */
    dispose(): void;
}

import { Wav2LipStrategy } from './wav2lip-strategy';
import { DinetStrategy } from './dinet-strategy';
import { WebGLStrategy } from './webgl-strategy';

/**
 * Factory to create the appropriate lip-sync strategy
 */
export async function createLipSyncStrategy(
    method: LipSyncMethod,
    deviceTier: DeviceTier
): Promise<LipSyncStrategy> {
    switch (method) {
        case 'wav2lip':
            return new Wav2LipStrategy();
        case 'dinet':
            return new DinetStrategy();
        case 'webgl':
            return new WebGLStrategy();
        default:
            return new DinetStrategy();
    }
}

/**
 * Get strategy by device tier
 */
export function getStrategyByTier(tier: DeviceTier): LipSyncMethod {
    switch (tier) {
        case 'high':
            return 'wav2lip';
        case 'medium':
        case 'low':
        case 'minimal':
        default:
            return 'dinet';
    }
}

export default {
    createLipSyncStrategy,
    getStrategyByTier,
};
