/**
 * Video Sync Manager
 * 
 * Handles high-precision synchronization between audio, 
 * lip-sync frames, and HTML5 Video playback.
 */

export class VideoSyncManager {
    private videoElement: HTMLVideoElement | null = null;
    private audioContext: AudioContext | null = null;
    private audioStartTime: number = 0;
    
    private startTime: number = 0;
    private isPlaying: boolean = false;
    private lastSyncTime: number = 0;

    constructor(videoElement?: HTMLVideoElement) {
        if (videoElement) {
            this.setVideoElement(videoElement);
        }
    }

    /**
     * Set the video element to sync with
     */
    setVideoElement(videoElement: HTMLVideoElement): void {
        this.videoElement = videoElement;
    }

    /**
     * Set the audio context for precise audio timing
     */
    setAudioContext(audioContext: AudioContext, startTimeOffset: number = 0): void {
        this.audioContext = audioContext;
        this.audioStartTime = audioContext.currentTime - startTimeOffset;
    }

    /**
     * Start the sync clock
     */
    start(): void {
        this.isPlaying = true;
        this.startTime = performance.now();
    }

    /**
     * Stop the sync clock
     */
    stop(): void {
        this.isPlaying = false;
    }

    /**
     * Get current reference time (in seconds)
     */
    getCurrentTime(): number {
        if (!this.isPlaying) return this.lastSyncTime;

        let currentTime: number;

        if (this.videoElement && !this.videoElement.paused) {
            // Use video's current time if available and playing
            // This ensures we stay in sync even if the video buffers or stalls
            currentTime = this.videoElement.currentTime;
        } else if (this.audioContext && this.audioContext.state === 'running') {
            // Use precise WebAudio clock
            currentTime = this.audioContext.currentTime - this.audioStartTime;
        } else {
            // Fallback to performance clock
            currentTime = (performance.now() - this.startTime) / 1000;
        }

        this.lastSyncTime = currentTime;
        return currentTime;
    }

    /**
     * Seek to a specific time
     */
    seek(time: number): void {
        this.lastSyncTime = time;
        if (this.videoElement) {
            this.videoElement.currentTime = time;
        }
        this.startTime = performance.now() - (time * 1000);
    }

    /**
     * Check if playing
     */
    get active(): boolean {
        return this.isPlaying;
    }
}

export default VideoSyncManager;
