/**
 * Avatar State Management
 */
export type AvatarState = 'IDLE' | 'THINKING' | 'SPEAKING' | 'ERROR';

export class AvatarStateManager {
  private currentState: AvatarState = 'IDLE';
  private listeners: ((state: AvatarState) => void)[] = [];

  public getState(): AvatarState {
    return this.currentState;
  }

  public setState(newState: AvatarState) {
    if (this.currentState !== newState) {
      console.log(`Avatar state transition: ${this.currentState} -> ${newState}`);
      this.currentState = newState;
      this.notifyListeners();
    }
  }

  public subscribe(listener: (state: AvatarState) => void) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter(l => l !== listener);
    };
  }

  private notifyListeners() {
    this.listeners.forEach(listener => listener(this.currentState));
  }
}

// Singleton instance
export const avatarState = new AvatarStateManager();
