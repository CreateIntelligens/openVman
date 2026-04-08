const TARGET_SAMPLE_RATE = 16000;
const DEFAULT_CHUNK_DURATION_MS = 100;
const WORKLET_PROCESSOR_NAME = 'openvman-pcm-capture';
const PCM_MIME_TYPE = 'audio/pcm;rate=16000';

const WORKLET_SOURCE = `
class OpenVmanPcmCaptureProcessor extends AudioWorkletProcessor {
  process(inputs, outputs) {
    const input = inputs[0];
    const output = outputs[0];

    if (output && output[0]) {
      output[0].fill(0);
    }

    if (input && input[0] && input[0].length > 0) {
      this.port.postMessage(input[0].slice());
    }

    return true;
  }
}

registerProcessor('${WORKLET_PROCESSOR_NAME}', OpenVmanPcmCaptureProcessor);
`;

export interface AudioChunkPayload {
  audioBase64: string;
  sampleRate: number;
  mimeType: string;
  timestamp: number;
}

export interface AudioStreamerConfig {
  chunkDurationMs?: number;
  onChunk: (payload: AudioChunkPayload) => void;
}

type AudioContextCtor = typeof AudioContext;

export class AudioStreamer {
  private readonly onChunk: (payload: AudioChunkPayload) => void;
  private readonly chunkSamples: number;

  private audioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private processorNode: AudioNode | null = null;
  private sinkNode: GainNode | null = null;

  private pendingSamples: number[] = [];
  private streamingEnabled = false;
  private started = false;

  constructor(config: AudioStreamerConfig) {
    this.onChunk = config.onChunk;
    this.chunkSamples = Math.max(
      1,
      Math.round(
        (TARGET_SAMPLE_RATE * (config.chunkDurationMs ?? DEFAULT_CHUNK_DURATION_MS)) / 1000,
      ),
    );
  }

  public async start(): Promise<void> {
    if (this.started) {
      return;
    }

    const AudioContextImpl = this.getAudioContextCtor();
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    this.audioContext = new AudioContextImpl();
    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume();
    }

    this.sourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
    this.sinkNode = this.audioContext.createGain();
    this.sinkNode.gain.value = 0;
    this.sinkNode.connect(this.audioContext.destination);

    if (this.supportsAudioWorklet(this.audioContext)) {
      await this.setupAudioWorklet(this.audioContext);
    } else {
      this.setupScriptProcessor(this.audioContext);
    }

    this.started = true;
  }

  public setStreamingEnabled(enabled: boolean): void {
    if (!this.started || this.streamingEnabled === enabled) {
      if (!enabled && this.pendingSamples.length > 0) {
        this.flushPendingSamples(true);
      }
      return;
    }

    this.streamingEnabled = enabled;

    if (enabled) {
      this.pendingSamples = [];
      return;
    }

    this.flushPendingSamples(true);
  }

  public stop(): void {
    this.streamingEnabled = false;
    this.pendingSamples = [];
    this.processorNode?.disconnect();
    this.sourceNode?.disconnect();
    this.sinkNode?.disconnect();
    this.mediaStream?.getTracks().forEach((track) => track.stop());
    const closePromise = this.audioContext?.close();
    closePromise?.catch((error) => {
      console.error('Failed to close AudioStreamer context:', error);
    });

    this.processorNode = null;
    this.sourceNode = null;
    this.sinkNode = null;
    this.mediaStream = null;
    this.audioContext = null;
    this.started = false;
  }

  private getAudioContextCtor(): AudioContextCtor {
    const ctor =
      window.AudioContext ||
      (window as typeof window & { webkitAudioContext?: AudioContextCtor }).webkitAudioContext;
    if (!ctor) {
      throw new Error('AudioContext is not supported in this browser');
    }

    return ctor;
  }

  private supportsAudioWorklet(audioContext: AudioContext): boolean {
    return typeof AudioWorkletNode !== 'undefined' && !!audioContext.audioWorklet;
  }

  private async setupAudioWorklet(audioContext: AudioContext): Promise<void> {
    const moduleUrl = URL.createObjectURL(
      new Blob([WORKLET_SOURCE], { type: 'application/javascript' }),
    );

    try {
      await audioContext.audioWorklet.addModule(moduleUrl);
    } finally {
      URL.revokeObjectURL(moduleUrl);
    }

    const workletNode = new AudioWorkletNode(audioContext, WORKLET_PROCESSOR_NAME, {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
    });

    workletNode.port.onmessage = (event: MessageEvent<Float32Array>) => {
      this.handleFloatSamples(event.data);
    };

    this.sourceNode?.connect(workletNode);
    workletNode.connect(this.sinkNode!);
    this.processorNode = workletNode;
  }

  private setupScriptProcessor(audioContext: AudioContext): void {
    const processor = audioContext.createScriptProcessor(2048, 1, 1);
    processor.onaudioprocess = (event: AudioProcessingEvent) => {
      const samples = event.inputBuffer.getChannelData(0);
      this.handleFloatSamples(samples);
    };

    this.sourceNode?.connect(processor);
    processor.connect(this.sinkNode!);
    this.processorNode = processor;
  }

  private handleFloatSamples(inputSamples: Float32Array): void {
    if (!this.streamingEnabled || inputSamples.length === 0 || !this.audioContext) {
      return;
    }

    const pcmSamples = resampleFloat32ToPcm16(
      inputSamples,
      this.audioContext.sampleRate,
      TARGET_SAMPLE_RATE,
    );

    if (pcmSamples.length === 0) {
      return;
    }

    for (const sample of pcmSamples) {
      this.pendingSamples.push(sample);
    }

    this.flushPendingSamples(false);
  }

  private flushPendingSamples(force: boolean): void {
    while (
      this.pendingSamples.length >= this.chunkSamples ||
      (force && this.pendingSamples.length > 0)
    ) {
      const sampleCount = force
        ? this.pendingSamples.length
        : this.chunkSamples;
      const chunk = new Int16Array(this.pendingSamples.splice(0, sampleCount));

      this.onChunk({
        audioBase64: pcm16ToBase64(chunk),
        sampleRate: TARGET_SAMPLE_RATE,
        mimeType: PCM_MIME_TYPE,
        timestamp: Date.now(),
      });
    }
  }
}

function resampleFloat32ToPcm16(
  input: Float32Array,
  inputSampleRate: number,
  outputSampleRate: number,
): Int16Array {
  if (input.length === 0) {
    return new Int16Array();
  }

  if (inputSampleRate === outputSampleRate) {
    return float32ToInt16(input);
  }

  const ratio = inputSampleRate / outputSampleRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const result = new Int16Array(outputLength);

  for (let index = 0; index < outputLength; index += 1) {
    const sourceIndex = index * ratio;
    const lowerIndex = Math.floor(sourceIndex);
    const upperIndex = Math.min(input.length - 1, lowerIndex + 1);
    const blend = sourceIndex - lowerIndex;
    const sample =
      input[lowerIndex] + (input[upperIndex] - input[lowerIndex]) * blend;
    result[index] = clampFloatToInt16(sample);
  }

  return result;
}

function float32ToInt16(input: Float32Array): Int16Array {
  const result = new Int16Array(input.length);
  for (let index = 0; index < input.length; index += 1) {
    result[index] = clampFloatToInt16(input[index]);
  }

  return result;
}

function clampFloatToInt16(sample: number): number {
  const clamped = Math.max(-1, Math.min(1, sample));
  return clamped < 0 ? Math.round(clamped * 0x8000) : Math.round(clamped * 0x7fff);
}

function pcm16ToBase64(samples: Int16Array): string {
  const bytes = new Uint8Array(samples.buffer);
  let binary = '';

  for (let index = 0; index < bytes.length; index += 0x8000) {
    const slice = bytes.subarray(index, index + 0x8000);
    binary += String.fromCharCode(...slice);
  }

  return window.btoa(binary);
}
