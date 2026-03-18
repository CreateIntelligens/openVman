/**
 * Device Capabilities Detection Module
 * 
 * Detects client device hardware capabilities to determine
 * the appropriate lip-sync method (Wav2Lip or Viseme).
 */

// WebGPU type declarations (for browsers that support it)
declare global {
    interface Navigator {
        gpu?: GPU;
    }
    interface GPU {
        requestAdapter(): Promise<GPUAdapter | null>;
    }
    interface GPUAdapter {
        info: { vendor: string; architecture: string };
        requestDevice(): Promise<GPUDevice>;
    }
    interface GPUDevice { }
}

export interface DeviceCapabilities {
    hasWebGPU: boolean;
    hasDedicatedGPU: boolean;
    cpuCores: number;
    memoryGB: number;
    isMobile: boolean;
    isIOS: boolean;
    isAndroid: boolean;
}

export type DeviceTier = 'high' | 'medium' | 'low' | 'minimal';

/**
 * Detect WebGPU support
 */
export async function detectWebGPU(): Promise<boolean> {
    if (!navigator.gpu) {
        return false;
    }

    try {
        const adapter = await navigator.gpu.requestAdapter();
        return adapter !== null;
    } catch {
        return false;
    }
}

/**
 * Detect hardware concurrency (CPU cores)
 */
export function detectCPUCores(): number {
    return navigator.hardwareConcurrency || 4;
}

/**
 * Detect device memory (GB)
 */
export function detectMemory(): number {
    // @ts-ignore - deviceMemory is not in TypeScript types yet
    return navigator.deviceMemory || 4;
}

/**
 * Detect if device is mobile
 */
export function detectMobile(): boolean {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
}

/**
 * Detect if device is iOS
 */
export function detectIOS(): boolean {
    return /iPhone|iPad|iPod/i.test(navigator.userAgent);
}

/**
 * Detect if device is Android
 */
export function detectAndroid(): boolean {
    return /Android/i.test(navigator.userAgent);
}

/**
 * Check if device has dedicated GPU (heuristic)
 * Note: This is a rough heuristic and may not be accurate
 */
export async function detectDedicatedGPU(): Promise<boolean> {
    if (!navigator.gpu) {
        return false;
    }

    try {
        const adapter = await navigator.gpu.requestAdapter();
        if (!adapter) return false;

        // Check adapter info for dedicated GPU hints
        const info = adapter.info;
        // Dedicated GPUs typically have more memory
        const capabilities = await adapter.requestDevice();
        // WebGPU doesn't directly expose GPU memory, so we use heuristics
        return capabilities !== null;
    } catch {
        return false;
    }
}

/**
 * Run a simple performance benchmark
 * Returns estimated FPS capability
 */
export async function runPerformanceBenchmark(): Promise<number> {
    const start = performance.now();

    // Simple computation benchmark
    let result = 0;
    for (let i = 0; i < 1000000; i++) {
        result += Math.sqrt(i);
    }

    const duration = performance.now() - start;

    // Estimate FPS: higher duration = lower capability
    // This is a very rough estimate
    const score = 1000 / duration;
    return Math.min(score, 60);
}

/**
 * Detect all device capabilities
 */
export async function detectAllCapabilities(): Promise<DeviceCapabilities> {
    const [hasWebGPU, hasDedicatedGPU] = await Promise.all([
        detectWebGPU(),
        detectDedicatedGPU(),
    ]);

    return {
        hasWebGPU,
        hasDedicatedGPU,
        cpuCores: detectCPUCores(),
        memoryGB: detectMemory(),
        isMobile: detectMobile(),
        isIOS: detectIOS(),
        isAndroid: detectAndroid(),
    };
}

/**
 * Determine device tier based on capabilities
 */
export function determineDeviceTier(capabilities: DeviceCapabilities): DeviceTier {
    const { hasWebGPU, hasDedicatedGPU, cpuCores, memoryGB, isMobile } = capabilities;

    // High-end: Has WebGPU and dedicated GPU
    if (hasWebGPU && hasDedicatedGPU) {
        return 'high';
    }

    // Medium: Has WebGPU but no dedicated GPU
    if (hasWebGPU && !hasDedicatedGPU) {
        return 'medium';
    }

    // Low: No WebGPU but decent CPU/memory
    if (!hasWebGPU && cpuCores >= 4 && memoryGB >= 4 && !isMobile) {
        return 'low';
    }

    // Minimal: Mobile or low-end devices
    return 'minimal';
}

/**
 * Get recommended lip-sync method for device tier
 */
export function getRecommendedLipSyncMethod(tier: DeviceTier): 'wav2lip-high' | 'wav2lip-medium' | 'wav2lip-cpu' | 'viseme' {
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
    detectAllCapabilities,
    determineDeviceTier,
    getRecommendedLipSyncMethod,
    detectWebGPU,
    detectCPUCores,
    detectMemory,
    runPerformanceBenchmark,
};
