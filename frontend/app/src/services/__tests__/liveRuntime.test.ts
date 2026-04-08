import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mock all dependency modules before importing LiveRuntime
// ---------------------------------------------------------------------------

const mockWsSend = vi.fn();
const mockWsSendInterrupt = vi.fn();
const mockWsSendUserSpeak = vi.fn();
const mockWsSendAudioChunk = vi.fn();
const mockWsSendAudioEnd = vi.fn();
const mockWsConnect = vi.fn();
const mockWsDisconnect = vi.fn();
const mockWsSetLipSyncMode = vi.fn();

let capturedOnAudioChunk: ((data: unknown) => void) | null = null;
let capturedOnStopAudio: (() => void) | null = null;

vi.mock('../websocket', () => ({
  WebSocketService: vi.fn().mockImplementation(
    (_clientId: string, _authToken: string, onAudioChunk: (data: unknown) => void, onStopAudio: () => void) => {
      capturedOnAudioChunk = onAudioChunk;
      capturedOnStopAudio = onStopAudio;
      return {
        connect: mockWsConnect,
        disconnect: mockWsDisconnect,
        sendInterrupt: mockWsSendInterrupt,
        sendUserSpeak: mockWsSendUserSpeak,
        sendAudioChunk: mockWsSendAudioChunk,
        sendAudioEnd: mockWsSendAudioEnd,
        setLipSyncMode: mockWsSetLipSyncMode,
        send: mockWsSend,
      };
    },
  ),
}));

let capturedAsrCallback: ((text: string, isFinal: boolean) => void) | null = null;
const mockAsrStart = vi.fn();
const mockAsrStop = vi.fn();

vi.mock('../asr', () => ({
  ASRService: vi.fn().mockImplementation((onResult: (text: string, isFinal: boolean) => void) => {
    capturedAsrCallback = onResult;
    return { start: mockAsrStart, stop: mockAsrStop };
  }),
}));

let capturedVadOnSpeechStart: (() => void) | null = null;
let capturedVadOnSpeechEnd: (() => void) | null = null;
const mockVadStart = vi.fn().mockResolvedValue(undefined);
const mockVadStop = vi.fn();

vi.mock('../vad', () => ({
  VADService: vi.fn().mockImplementation(
    (onSpeechStart: () => void, onSpeechEnd: () => void) => {
      capturedVadOnSpeechStart = onSpeechStart;
      capturedVadOnSpeechEnd = onSpeechEnd;
      return { start: mockVadStart, stop: mockVadStop };
    },
  ),
}));

const mockPlaybackQueueAudio = vi.fn();
const mockPlaybackStopAll = vi.fn();
const mockPlaybackSetCallbacks = vi.fn();

vi.mock('../audioPlayback', () => ({
  AudioPlaybackService: vi.fn().mockImplementation(() => ({
    queueAudio: mockPlaybackQueueAudio,
    stopAll: mockPlaybackStopAll,
    setCallbacks: mockPlaybackSetCallbacks,
  })),
}));

const mockStreamerStart = vi.fn().mockResolvedValue(undefined);
const mockStreamerStop = vi.fn();
const mockStreamerSetStreamingEnabled = vi.fn();

vi.mock('../audioStreamer', () => ({
  AudioStreamer: vi.fn().mockImplementation(() => ({
    start: mockStreamerStart,
    stop: mockStreamerStop,
    setStreamingEnabled: mockStreamerSetStreamingEnabled,
  })),
}));

vi.mock('../../store/avatarState', () => ({
  avatarState: { setState: vi.fn() },
}));

vi.mock('@contracts/generated/typescript/protocol-contracts', () => ({}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------
import { LiveRuntime } from '../liveRuntime';

const mockLipSync = {
  getMethod: vi.fn().mockReturnValue('webgl' as const),
  processAudioChunk: vi.fn(),
  stop: vi.fn(),
};

beforeEach(() => {
  vi.useFakeTimers();
  capturedOnAudioChunk = null;
  capturedOnStopAudio = null;
  capturedAsrCallback = null;
  capturedVadOnSpeechStart = null;
  capturedVadOnSpeechEnd = null;
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LiveRuntime — brain_tts mode (default)', () => {
  it('does not create AudioStreamer', async () => {
    const { AudioStreamer } = await import('../audioStreamer');
    const mock = vi.mocked(AudioStreamer);
    const before = mock.mock.calls.length;

    const rt = new LiveRuntime({ clientId: 'c1', authToken: 't1' });
    expect(mock.mock.calls.length).toBe(before); // no new call

    // Gemini mode should create one
    new LiveRuntime({ clientId: 'c2', authToken: 't2', mode: 'gemini_live' });
    expect(mock.mock.calls.length).toBe(before + 1);
    void rt;
  });

  it('submits user_speak after silence window', () => {
    const rt = new LiveRuntime({
      clientId: 'c1',
      authToken: 't1',
      silenceWindowMs: 500,
    });
    void rt;

    capturedAsrCallback?.('你好', true);
    expect(mockWsSendUserSpeak).not.toHaveBeenCalled();

    vi.advanceTimersByTime(500);
    expect(mockWsSendUserSpeak).toHaveBeenCalledWith('你好');
  });

  it('does not send client_audio_end on speech end', () => {
    const rt = new LiveRuntime({ clientId: 'c1', authToken: 't1' });
    void rt;

    capturedAsrCallback?.('test', false);
    capturedVadOnSpeechEnd?.();
    vi.advanceTimersByTime(2000);

    expect(mockWsSendAudioEnd).not.toHaveBeenCalled();
  });
});

describe('LiveRuntime — gemini_live mode', () => {
  function createGeminiRuntime() {
    return new LiveRuntime({
      clientId: 'c1',
      authToken: 't1',
      mode: 'gemini_live',
      silenceWindowMs: 500,
    });
  }

  it('starts AudioStreamer on start()', async () => {
    const rt = createGeminiRuntime();
    await rt.start('ws://localhost', mockLipSync as any);
    expect(mockStreamerStart).toHaveBeenCalledOnce();
    rt.stop();
  });

  it('stops AudioStreamer on stop()', async () => {
    const rt = createGeminiRuntime();
    await rt.start('ws://localhost', mockLipSync as any);
    rt.stop();
    expect(mockStreamerStop).toHaveBeenCalledOnce();
  });

  it('suppresses ASR-derived user_speak submission', () => {
    const rt = createGeminiRuntime();
    void rt;

    capturedAsrCallback?.('你好', true);
    vi.advanceTimersByTime(5000);
    expect(mockWsSendUserSpeak).not.toHaveBeenCalled();
  });

  it('notifies onTranscript callback for display', () => {
    const onTranscript = vi.fn();
    const rt = new LiveRuntime({
      clientId: 'c1',
      authToken: 't1',
      mode: 'gemini_live',
      onTranscript,
    });
    void rt;

    capturedAsrCallback?.('你好', false);
    expect(onTranscript).toHaveBeenCalledWith('你好', false);
  });

  it('enables streaming on speech start and disables on speech end', () => {
    const rt = createGeminiRuntime();
    void rt;

    capturedVadOnSpeechStart?.();
    expect(mockStreamerSetStreamingEnabled).toHaveBeenCalledWith(true);

    capturedVadOnSpeechEnd?.();
    expect(mockStreamerSetStreamingEnabled).toHaveBeenCalledWith(false);
  });

  it('sends client_audio_end on speech end', () => {
    const rt = createGeminiRuntime();
    void rt;

    capturedVadOnSpeechStart?.();
    capturedVadOnSpeechEnd?.();
    expect(mockWsSendAudioEnd).toHaveBeenCalledOnce();
  });

  it('does not send client_audio_end if no audio turn was opened', () => {
    const rt = createGeminiRuntime();
    void rt;

    // speech end without prior speech start
    capturedVadOnSpeechEnd?.();
    expect(mockWsSendAudioEnd).not.toHaveBeenCalled();
  });

  it('preserves typed text fallback via sendTypedText', () => {
    const rt = createGeminiRuntime();
    rt.sendTypedText('打字輸入');
    expect(mockWsSendUserSpeak).toHaveBeenCalledWith('打字輸入');
  });

  it('sendTypedText ignores empty/whitespace text', () => {
    const rt = createGeminiRuntime();
    rt.sendTypedText('   ');
    expect(mockWsSendUserSpeak).not.toHaveBeenCalled();
  });

  it('sendTypedText disables audio streaming and resets turn', () => {
    const rt = createGeminiRuntime();
    void rt;

    capturedVadOnSpeechStart?.();
    rt.sendTypedText('override');

    expect(mockStreamerSetStreamingEnabled).toHaveBeenCalledWith(false);
    expect(mockWsSendUserSpeak).toHaveBeenCalledWith('override');
  });
});

describe('LiveRuntime — shared behavior', () => {
  it('sends interrupt on speech start in both modes', () => {
    for (const mode of ['brain_tts', 'gemini_live'] as const) {
      vi.clearAllMocks();
      const rt = new LiveRuntime({ clientId: 'c1', authToken: 't1', mode });
      void rt;

      capturedAsrCallback?.('partial', false);
      capturedVadOnSpeechStart?.();
      expect(mockWsSendInterrupt).toHaveBeenCalledWith('partial');
    }
  });

  it('stops playback on server_stop_audio in both modes', () => {
    for (const mode of ['brain_tts', 'gemini_live'] as const) {
      vi.clearAllMocks();
      const rt = new LiveRuntime({ clientId: 'c1', authToken: 't1', mode });
      void rt;

      capturedOnStopAudio?.();
      expect(mockPlaybackStopAll).toHaveBeenCalled();
    }
  });
});
