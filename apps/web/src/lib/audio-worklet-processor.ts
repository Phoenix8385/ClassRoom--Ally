/**
 * Canonical, typed source for the classroom audio worklet.
 *
 * IMPORTANT: This `.ts` is the source of truth, but it is NOT what the browser
 * loads at runtime. `AudioWorklet.addModule()` requires a URL-loadable plain-JS
 * ES module, and bundlers will not transpile a worklet for you. The runtime copy
 * lives at `public/audio-worklet-processor.js` and MUST be kept in sync with this
 * file. `audio-capture.ts` loads `/audio-worklet-processor.js`.
 *
 * Worklet globals (`AudioWorkletProcessor`, `registerProcessor`, `sampleRate`)
 * are not in the default TS DOM lib, so they are declared here.
 */

declare const sampleRate: number;

declare const AudioWorkletProcessor: {
  prototype: AudioWorkletProcessorBase;
  new (): AudioWorkletProcessorBase;
};

interface AudioWorkletProcessorBase {
  readonly port: MessagePort;
  process(
    inputs: Float32Array[][],
    outputs: Float32Array[][],
    parameters: Record<string, Float32Array>,
  ): boolean;
}

declare function registerProcessor(
  name: string,
  processorCtor: new () => AudioWorkletProcessorBase,
): void;

/** 320 samples = 20 ms at 16 kHz. */
const FRAME_SIZE = 320;

class ClassroomAudioProcessor extends AudioWorkletProcessor {
  private readonly buffer = new Float32Array(FRAME_SIZE);
  private offset = 0;

  process(inputs: Float32Array[][]): boolean {
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

  private flush(): void {
    // RMS over the float frame (0..1), computed before the Int16 transfer.
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
    // Transfer the underlying buffer to avoid a copy.
    this.port.postMessage(pcm, [pcm.buffer]);
  }
}

registerProcessor("classroom-audio-processor", ClassroomAudioProcessor);

// Reference the imported sample rate so strict/no-unused settings stay happy;
// the worklet runs at the AudioContext rate (16 kHz as requested).
void sampleRate;

export {};
