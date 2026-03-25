/**
 * Frontend WebSocket Service
 * Handles communication with the Backend Nervous System.
 */
import { avatarState } from '../store/avatarState';

export class WebSocketService {
  private socket: WebSocket | null = null;
  private onAudioChunk: (audioBase64: string) => void;

  constructor(private clientId: string, onAudioChunk: (audioBase64: string) => void) {
    this.onAudioChunk = onAudioChunk;
  }

  public connect(url: string) {
    this.socket = new WebSocket(`${url}/ws/${this.clientId}`);

    this.socket.onopen = () => {
      console.log('Connected to Backend Nervous System');
      avatarState.setState('IDLE');
    };

    this.socket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handleEvent(data);
    };

    this.socket.onclose = () => {
      console.log('Disconnected from Backend');
      setTimeout(() => this.connect(url), 3000); // Simple retry
    };
  }

  private handleEvent(data: any) {
    switch (data.event) {
      case 'server_stream_chunk':
        if (data.audio_base64) {
          avatarState.setState('SPEAKING');
          this.onAudioChunk(data.audio_base64);
        }
        break;

      case 'server_stop_audio':
        console.log('Interruption received: Stopping audio');
        avatarState.setState('IDLE');
        // Trigger local audio stop logic
        break;

      case 'server_error':
        console.error('Backend Error:', data.message);
        avatarState.setState('ERROR');
        break;
    }
  }

  public sendInterrupt(text: string) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({
        event: 'client_interrupt',
        text: text
      }));
    }
  }

  public sendUserSpeak(text: string) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      avatarState.setState('THINKING');
      this.socket.send(JSON.stringify({
        event: 'user_speak',
        text: text
      }));
    }
  }
}
