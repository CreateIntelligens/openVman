/**
 * Simple Web Audio based VAD (Voice Activity Detection)
 */
export class VADService {
  private audioContext: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private analyzer: AnalyserNode | null = null;
  private scriptProcessor: ScriptProcessorNode | null = null;
  
  private isSpeaking: boolean = false;
  private silenceTimer: number | null = null;
  
  constructor(
    private onSpeechStart: () => void,
    private onSpeechEnd: () => void,
    private threshold: number = -50, // dB
    private silenceDelay: number = 1000 // ms
  ) {}

  public async start() {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.audioContext = new AudioContext();
      const source = this.audioContext.createMediaStreamSource(this.stream);
      
      this.analyzer = this.audioContext.createAnalyser();
      this.analyzer.fftSize = 2048;
      source.connect(this.analyzer);
      
      // Using ScriptProcessor for simplicity, though it's deprecated. 
      // AudioWorklet would be the modern way.
      this.scriptProcessor = this.audioContext.createScriptProcessor(2048, 1, 1);
      this.scriptProcessor.connect(this.audioContext.destination);
      this.analyzer.connect(this.scriptProcessor);
      
      this.scriptProcessor.onaudioprocess = () => {
        const data = new Float32Array(this.analyzer!.frequencyBinCount);
        this.analyzer!.getFloatTimeDomainData(data);
        
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
          sum += data[i] * data[i];
        }
        const rms = Math.sqrt(sum / data.length);
        const db = 20 * Math.log10(rms);
        
        if (db > this.threshold) {
          this.handleSpeech();
        } else {
          this.handleSilence();
        }
      };
    } catch (e) {
      console.error('Failed to start VAD:', e);
    }
  }

  private handleSpeech() {
    if (!this.isSpeaking) {
      this.isSpeaking = true;
      this.onSpeechStart();
    }
    
    if (this.silenceTimer) {
      clearTimeout(this.silenceTimer);
      this.silenceTimer = null;
    }
  }

  private handleSilence() {
    if (this.isSpeaking && !this.silenceTimer) {
      this.silenceTimer = window.setTimeout(() => {
        this.isSpeaking = false;
        this.onSpeechEnd();
        this.silenceTimer = null;
      }, this.silenceDelay);
    }
  }

  public stop() {
    if (this.scriptProcessor) this.scriptProcessor.disconnect();
    if (this.analyzer) this.analyzer.disconnect();
    if (this.stream) this.stream.getTracks().forEach(t => t.stop());
    if (this.audioContext) this.audioContext.close();
  }
}
