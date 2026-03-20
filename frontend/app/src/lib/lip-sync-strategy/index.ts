/**
 * Lip Sync Strategy Interface
 * 
 * Defines the contract for different lip-sync methods
 * (Viseme lookup and Wav2Lip AI)
 */

import { VisemeStrategy } from './viseme-strategy.js';
import { Wav2LipStrategy } from './wav2lip-strategy.js';
import type { LipSyncMethod } from '../wav2lip';
import type { DeviceTier } from '../device-capabilities';

export type { LipSyncMethod };

export interface VisemeData {
    time: number;
    value: string;
}

export interface AudioChunk {
    audioBuffer: AudioBuffer;
    visemes: VisemeData[];
    text?: string;
}

export interface LipSyncStrategy {
    /** Unique identifier for this strategy */
    readonly method: LipSyncMethod;

    /** Human-readable name */
    readonly name: string;

    /** Initialize the strategy (load models, etc.) */
    initialize(): Promise<void>;

    /** Process audio chunk and generate lip-sync frames */
    processAudio(chunk: AudioChunk): Promise<void>;

    /** Get current frame for rendering */
    getCurrentFrame(): ImageData | null;

    /** Check if strategy is ready */
    isReady(): boolean;

    /** Clean up resources */
    dispose(): void;
}

/**
 * Factory to create the appropriate lip-sync strategy
 */
export async function createLipSyncStrategy(
    method: LipSyncMethod,
    deviceTier: DeviceTier
): Promise<LipSyncStrategy> {
    switch (method) {
        case 'wav2lip-high':
        case 'wav2lip-medium':
        case 'wav2lip-cpu':
            return new Wav2LipStrategy(method);

        case 'viseme':
        default:
            return new VisemeStrategy();
    }
}

/**
 * Get strategy by device tier
 */
export function getStrategyByTier(tier: DeviceTier): LipSyncMethod {
    switch (tier) {
        case 'high':
            return 'wav2lip-high';
        case 'medium':
            return 'wav2lip-medium';
        case 'low':
            return 'wav2lip-cpu';
        case 'minimal':
        default:
            return 'viseme';
    }
}

export default {
    createLipSyncStrategy,
    getStrategyByTier,
};
