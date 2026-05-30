// Runtime artifact loaded by AudioWorklet.addModule("/audio-worklet-processor.js").
// Keep in sync with src/lib/audio-worklet-processor.ts (the typed source of truth).

const FRAME_SIZE = 320; // 320 samples = 20 ms at 16 kHz

class ClassroomAudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(FRAME_SIZE);
    this.offset = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0];
    if (!channel) return true;

    for (let i = 0; i < channel.length; i++) {
      this.buffer[this.offset++] = channel[i];

      if (this.offset === FRAME_SIZE) {
        this.flush();
        this.offset = 0;
      }
    }
    return true;
  }

  flush() {
    let sumSquares = 0;
    const pcm = new Int16Array(FRAME_SIZE);
    for (let i = 0; i < FRAME_SIZE; i++) {
      const sample = this.buffer[i];
      sumSquares += sample * sample;
      const scaled = sample * 32768;
      pcm[i] = scaled > 32767 ? 32767 : scaled < -32768 ? -32768 : scaled;
    }
    const rms = Math.sqrt(sumSquares / FRAME_SIZE);

    this.port.postMessage({ type: "level", value: rms });
    this.port.postMessage(pcm, [pcm.buffer]);
  }
}

registerProcessor("classroom-audio-processor", ClassroomAudioProcessor);
