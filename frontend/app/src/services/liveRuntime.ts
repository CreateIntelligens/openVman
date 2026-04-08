/**
 * Frontend Live Runtime
 * Orchestrates ASR, VAD, WebSocket, and Audio Playback.
 */
import { ASRService } from './asr';
import { VADService } from './vad';
import { WebSocketService } from './websocket';
import { AudioPlaybackService } from './audioPlayback';
import { AudioStreamer } from './audioStreamer';
import type { LipSyncManager } from '../lib/lip-sync-manager';
import type { ServerStreamChunkEvent } from '@contracts/generated/typescript/protocol-contracts';

export type LiveRuntimeMode = 'brain_tts' | 'gemini_live';

export interface LiveRuntimeConfig {
  clientId: string;
  authToken: string;
  mode?: LiveRuntimeMode;
  vadThreshold?: number;
  silenceDelay?: number;
  silenceWindowMs?: number;
  onTranscript?: (text: string, isFinal: boolean) => void;
}

export class LiveRuntime {
  private asr: ASRService;
  private vad: VADService;
  private ws: WebSocketService;
  private playback: AudioPlaybackService;
  private audioStreamer: AudioStreamer | null;
  private lipSync: LipSyncManager | null = null;
  private readonly mode: LiveRuntimeMode;
  private readonly onTranscript?: (text: string, isFinal: boolean) => void;
  
  private lastPartialAsr: string = '';
  private isInterrupted: boolean = false;
  private submissionTimer: number | null = null;
  private silenceWindowMs: number;
  private audioTurnOpen: boolean = false;

  constructor(config: LiveRuntimeConfig) {
    this.mode = config.mode || 'brain_tts';
    this.onTranscript = config.onTranscript;
    this.silenceWindowMs = config.silenceWindowMs || 1500;
    this.playback = new AudioPlaybackService();
    
    this.ws = new WebSocketService(
      config.clientId, 
      config.authToken,
      (chunk) => this.handleAudioChunk(chunk),
      () => this.handleStopAudio()
    );

    this.audioStreamer = this.mode === 'gemini_live'
      ? new AudioStreamer({
          onChunk: ({ audioBase64, sampleRate, mimeType }) => {
            this.ws.sendAudioChunk(audioBase64, sampleRate, mimeType);
          },
        })
      : null;

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
    await this.audioStreamer?.start();
    
    // Sync lip-sync mode to server
    this.ws.setLipSyncMode(lipSyncManager.getMethod());
  }

  private clearSubmissionTimer() {
    if (this.submissionTimer) {
      window.clearTimeout(this.submissionTimer);
      this.submissionTimer = null;
    }
  }

  private handleSpeechStart() {
    console.log('Speech started - sending interrupt signal');
    this.clearSubmissionTimer();
    this.isInterrupted = true;
    this.ws.sendInterrupt(this.lastPartialAsr);
    // Local immediate stop
    this.handleStopAudio();

    if (this.mode === 'gemini_live') {
      this.audioTurnOpen = true;
      this.audioStreamer?.setStreamingEnabled(true);
    }
  }

  private handleSpeechEnd() {
    console.log('Speech ended - starting silence timer');
    if (this.mode === 'gemini_live') {
      this.audioStreamer?.setStreamingEnabled(false);
      if (this.audioTurnOpen) {
        this.ws.sendAudioEnd();
        this.audioTurnOpen = false;
      }
      this.isInterrupted = false;
      return;
    }

    this.resetSubmissionTimer();
  }

  private handleAsrResult(text: string, isFinal: boolean) {
    this.lastPartialAsr = text;
    this.onTranscript?.(text, isFinal);

    if (this.mode === 'gemini_live') {
      return;
    }
    
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
    this.clearSubmissionTimer();
    
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

  private handleAudioChunk(chunk: ServerStreamChunkEvent) {
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
    this.clearSubmissionTimer();
    this.audioStreamer?.stop();
    this.audioTurnOpen = false;
    this.ws.disconnect();
    this.asr.stop();
    this.vad.stop();
    this.playback.stopAll();
  }

  public sendTypedText(text: string) {
    const normalizedText = text.trim();
    if (!normalizedText) {
      return;
    }

    this.clearSubmissionTimer();
    this.audioStreamer?.setStreamingEnabled(false);
    this.audioTurnOpen = false;
    this.lastPartialAsr = '';
    this.isInterrupted = false;
    this.ws.sendUserSpeak(normalizedText);
  }
}
