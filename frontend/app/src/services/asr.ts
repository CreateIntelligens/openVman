/**
 * Frontend ASR Service using Web Speech API
 */
export class ASRService {
  private recognition: any;
  private isListening: boolean = false;

  constructor(private onResult: (text: string, isFinal: boolean) => void) {
    if (typeof window !== 'undefined') {
      const SpeechRecognition = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
      if (SpeechRecognition) {
        this.recognition = new SpeechRecognition();
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.lang = 'zh-TW';

        this.recognition.onresult = (event: any) => {
          let interimTranscript = '';
          let finalTranscript = '';

          for (let i = event.resultIndex; i < event.results.length; ++i) {
            if (event.results[i].isFinal) {
              finalTranscript += event.results[i][0].transcript;
            } else {
              interimTranscript += event.results[i][0].transcript;
            }
          }

          if (finalTranscript) {
            this.onResult(finalTranscript, true);
          } else if (interimTranscript) {
            this.onResult(interimTranscript, false);
          }
        };

        this.recognition.onerror = (event: any) => {
          console.error('ASR Error:', event.error);
        };
      }
    }
  }

  public start() {
    if (this.recognition && !this.isListening) {
      this.recognition.start();
      this.isListening = true;
    }
  }

  public stop() {
    if (this.recognition && this.isListening) {
      this.recognition.stop();
      this.isListening = false;
    }
  }
}
