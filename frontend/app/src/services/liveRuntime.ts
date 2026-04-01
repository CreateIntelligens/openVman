/**
 * Frontend Live Runtime
 * Orchestrates ASR, VAD, WebSocket, and Audio Playback.
 */
import { ASRService } from './asr';
import { VADService } from './vad';
import { WebSocketService } from './websocket';
import { AudioPlaybackService } from './audioPlayback';
import type { LipSyncManager } from '../lib/lip-sync-manager';

export interface LiveRuntimeConfig {
  clientId: string;
  authToken: string;
  vadThreshold?: number;
  silenceDelay?: number;
  silenceWindowMs?: number;
}

export class LiveRuntime {
  private asr: ASRService;
  private vad: VADService;
  private ws: WebSocketService;
  private playback: AudioPlaybackService;
  private lipSync: LipSyncManager | null = null;
  
  private lastPartialAsr: string = '';
  private isInterrupted: boolean = false;
  private submissionTimer: number | null = null;
  private silenceWindowMs: number;

  constructor(config: LiveRuntimeConfig) {
    this.silenceWindowMs = config.silenceWindowMs || 1500;
    this.playback = new AudioPlaybackService();
    
    this.ws = new WebSocketService(
      config.clientId, 
      config.authToken,
      (chunk) => this.handleAudioChunk(chunk),
      () => this.handleStopAudio()
    );

    this.asr = new ASRService((text, isFinal) => this.handleAsrResult(text, isFinal));
    
    this.vad = new VADService(
      () => this.handleSpeechStart(),
      () => this.handleSpeechEnd(),
      config.vadThreshold || -50,
      config.silenceDelay || 1000
    );

    this.playback.setCallbacks(
      (text) => console.log('Playing:', text),
      () => console.log('Playback queue empty')
    );
  }

  public async start(wsUrl: string, lipSyncManager: LipSyncManager) {
    this.lipSync = lipSyncManager;
    this.ws.connect(wsUrl);
    this.asr.start();
    await this.vad.start();
    
    // Sync lip-sync mode to server
    this.ws.setLipSyncMode(lipSyncManager.getMethod());
  }

  private handleSpeechStart() {
    console.log('Speech started - sending interrupt signal');
    this.isInterrupted = true;
    this.ws.sendInterrupt(this.lastPartialAsr);
    // Local immediate stop
    this.handleStopAudio();
  }

  private handleSpeechEnd() {
    console.log('Speech ended - starting silence timer');
    this.resetSubmissionTimer();
  }

  private handleAsrResult(text: string, isFinal: boolean) {
    this.lastPartialAsr = text;
    
    if (isFinal) {
      // If we get a final result, we can wait a bit more or submit immediately.
      // Let's use the timer for consistency.
      this.resetSubmissionTimer();
    } else {
      // Even for partials, if they stop coming, we should eventually submit.
      this.resetSubmissionTimer();
    }
  }

  private resetSubmissionTimer() {
    if (this.submissionTimer) {
      window.clearTimeout(this.submissionTimer);
    }
    
    this.submissionTimer = window.setTimeout(() => {
      this.submitUserSpeak();
    }, this.silenceWindowMs);
  }

  private submitUserSpeak() {
    const text = this.lastPartialAsr.trim();
    if (text) {
      console.log('Auto-submitting user speak:', text);
      this.ws.sendUserSpeak(text);
      this.lastPartialAsr = '';
      this.isInterrupted = false;
    }
    this.submissionTimer = null;
  }

  private handleAudioChunk(chunk: any) {
    if (this.isInterrupted) return; // Ignore chunks if we just interrupted
    
    this.playback.queueAudio(chunk.audio_base64, chunk.text);
    
    // Wire to LipSyncManager
    if (this.lipSync) {
      this.lipSync.processAudioChunk(chunk.audio_base64);
    }
  }

  private handleStopAudio() {
    this.playback.stopAll();
    if (this.lipSync) {
      this.lipSync.stop();
    }
  }

  public stop() {
    this.asr.stop();
    this.vad.stop();
    this.playback.stopAll();
  }
}
