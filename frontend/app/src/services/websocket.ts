/**
 * Frontend WebSocket Service
 * Handles communication with the Backend Nervous System.
 */
import { avatarState } from '../store/avatarState';
import type { 
  ClientEvent, 
  ServerEvent,
  ClientInitEvent,
  ClientInterruptEvent,
  UserSpeakEvent,
  SetLipSyncModeEvent
} from '@contracts/generated/typescript/protocol-contracts';

export class WebSocketService {
  private socket: WebSocket | null = null;
  private onAudioChunk: (data: any) => void;
  private onStopAudio: () => void;
  private sessionId: string | null = null;

  constructor(
    private clientId: string, 
    private authToken: string,
    onAudioChunk: (data: any) => void,
    onStopAudio: () => void
  ) {
    this.onAudioChunk = onAudioChunk;
    this.onStopAudio = onStopAudio;
  }

  public connect(url: string) {
    this.socket = new WebSocket(`${url}/ws/${this.clientId}`);

    this.socket.onopen = () => {
      console.log('Connected to Backend Nervous System');
      this.sendInit();
    };

    this.socket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as ServerEvent;
        this.handleEvent(data);
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    this.socket.onclose = () => {
      console.log('Disconnected from Backend');
      avatarState.setState('IDLE');
      // Exponential backoff would be better here
      setTimeout(() => this.connect(url), 3000); 
    };
  }

  private handleEvent(data: ServerEvent) {
    switch (data.event) {
      case 'server_init_ack':
        this.sessionId = data.session_id;
        console.log(`Handshake complete. Session ID: ${this.sessionId}`);
        avatarState.setState('IDLE');
        break;

      case 'server_stream_chunk':
        avatarState.setState('SPEAKING');
        this.onAudioChunk(data);
        break;

      case 'server_stop_audio':
        console.log('Stop signal received:', data.reason);
        this.onStopAudio();
        avatarState.setState('IDLE');
        break;

      case 'server_error':
        console.error('Backend Error:', data.message);
        avatarState.setState('ERROR');
        break;
    }
  }

  private sendInit() {
    const event: ClientInitEvent = {
      event: 'client_init',
      client_id: this.clientId,
      protocol_version: '1.0.0',
      auth_token: this.authToken,
      timestamp: Date.now()
    };
    this.send(event);
  }

  public sendInterrupt(partialAsr: string) {
    if (!this.sessionId) return;
    const event: ClientInterruptEvent = {
      event: 'client_interrupt',
      timestamp: Date.now(),
      partial_asr: partialAsr
    };
    this.send(event);
  }

  public sendUserSpeak(text: string) {
    if (!this.sessionId) return;
    avatarState.setState('THINKING');
    const event: UserSpeakEvent = {
      event: 'user_speak',
      text: text,
      timestamp: Date.now()
    };
    this.send(event);
  }

  public setLipSyncMode(mode: 'dinet' | 'wav2lip' | 'webgl') {
    if (!this.sessionId) return;
    const event: SetLipSyncModeEvent = {
      event: 'set_lip_sync_mode',
      session_id: this.sessionId,
      mode: mode,
      timestamp: Date.now()
    };
    this.send(event);
  }

  private send(event: ClientEvent) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(event));
    } else {
      console.warn('WebSocket not open. Cannot send event:', event.event);
    }
  }
}
