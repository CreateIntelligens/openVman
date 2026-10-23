/** Mirror every speaker source, including sources created after warm-up. */
export function installSpeakerTap(AudioNodeClass = AudioNode) {
  const original = AudioNodeClass.prototype.connect;
  const taps = new WeakMap();
  const silenceSources = [];
  let stream;
  AudioNodeClass.prototype.connect = function (destination, ...args) {
    const result = original.call(this, destination, ...args);
    if (destination === this.context.destination) {
      let tap = taps.get(this.context);
      if (!tap) {
        tap = this.context.createMediaStreamDestination();
        // MediaRecorder can wait indefinitely for its first audio packet if
        // recording starts between utterances. Keep the tap's clock running
        // with zero-valued samples; this never reaches the speaker.
        const silence = this.context.createConstantSource();
        silence.offset.value = 0;
        original.call(silence, tap);
        silence.start();
        silenceSources.push(silence);
        taps.set(this.context, tap);
      }
      original.call(this, tap);
      stream = tap.stream;
    }
    return result;
  };
  return { getStream: () => stream, restore: () => {
    AudioNodeClass.prototype.connect = original;
    silenceSources.forEach((source) => source.stop());
  } };
}
