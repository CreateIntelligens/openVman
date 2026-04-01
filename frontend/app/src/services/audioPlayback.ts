/**
 * Frontend Audio Playback Service
 * Manages an ordered queue of audio chunks and coordinates with the LipSyncManager.
 */
export class AudioPlaybackService {
  private audioContext: AudioContext;
  private queue: Array<{ buffer: AudioBuffer; text: string }> = [];
  private isPlaying: boolean = false;
  private currentSource: AudioBufferSourceNode | null = null;
  private onPlaybackStarted?: (text: string) => void;
  private onQueueEmpty?: () => void;

  constructor() {
    this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
  }

  public async queueAudio(base64Data: string, text: string) {
    try {
      const arrayBuffer = this.base64ToArrayBuffer(base64Data);
      const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);
      this.queue.push({ buffer: audioBuffer, text });
      
      if (!this.isPlaying) {
        this.playNext();
      }
    } catch (e) {
      console.error('Failed to decode audio chunk:', e);
    }
  }

  public stopAll() {
    if (this.currentSource) {
      this.currentSource.stop();
      this.currentSource = null;
    }
    this.queue = [];
    this.isPlaying = false;
    console.log('Audio playback stopped and queue cleared');
  }

  private async playNext() {
    if (this.queue.length === 0) {
      this.isPlaying = false;
      if (this.onQueueEmpty) this.onQueueEmpty();
      return;
    }

    this.isPlaying = true;
    const { buffer, text } = this.queue.shift()!;
    
    if (this.onPlaybackStarted) this.onPlaybackStarted(text);

    const source = this.audioContext.createBufferSource();
    source.buffer = buffer;
    source.connect(this.audioContext.destination);
    
    this.currentSource = source;
    
    source.onended = () => {
      this.currentSource = null;
      this.playNext();
    };

    source.start(0);
  }

  private base64ToArrayBuffer(base64: string): ArrayBuffer {
    const binaryString = window.atob(base64);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    return bytes.buffer;
  }

  public setCallbacks(onPlaybackStarted: (text: string) => void, onQueueEmpty: () => void) {
    this.onPlaybackStarted = onPlaybackStarted;
    this.onQueueEmpty = onQueueEmpty;
  }

  public getAudioContext() {
    return this.audioContext;
  }
}
