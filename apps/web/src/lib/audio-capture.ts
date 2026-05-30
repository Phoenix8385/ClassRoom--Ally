"use client";

import { useClassroomStore } from "@/store/classroom";
import type { WSClient } from "./ws-client";

const WORKLET_URL = "/audio-worklet-processor.js";
const PROCESSOR_NAME = "classroom-audio-processor";
const TARGET_SAMPLE_RATE = 16_000;

interface LevelMessage {
  type: "level";
  value: number;
}

// Module-level singletons — only one capture pipeline runs at a time.
let audioContext: AudioContext | null = null;
let mediaStream: MediaStream | null = null;
let sourceNode: MediaStreamAudioSourceNode | null = null;
let workletNode: AudioWorkletNode | null = null;

function isLevelMessage(data: unknown): data is LevelMessage {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as { type?: unknown }).type === "level"
  );
}

/**
 * Begin capturing microphone audio, downsample to 16 kHz mono PCM in the
 * worklet, and stream Int16 frames to the server via `wsClient`.
 *
 * Throws on getUserMedia failure (after flagging permission denial in the store).
 */
export async function startCapture(wsClient: WSClient): Promise<void> {
  const store = useClassroomStore.getState();

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: TARGET_SAMPLE_RATE,
        echoCancellation: true,
        noiseSuppression: true,
      },
      video: false,
    });
  } catch (err) {
    if (
      err instanceof DOMException &&
      (err.name === "NotAllowedError" || err.name === "SecurityError")
    ) {
      store.setMicPermissionDenied(true);
    }
    throw err;
  }

  store.setMicPermissionDenied(false);

  audioContext = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
  await audioContext.audioWorklet.addModule(WORKLET_URL);

  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  workletNode = new AudioWorkletNode(audioContext, PROCESSOR_NAME);

  workletNode.port.onmessage = (event: MessageEvent) => {
    const data = event.data;
    if (isLevelMessage(data)) {
      useClassroomStore.getState().setMicLevel(data.value);
    } else {
      // Otherwise it's the raw Int16Array audio frame.
      wsClient.sendBinaryFrame(data as Int16Array);
    }
  };

  // Source → worklet only. Deliberately NOT connected to destination, so the
  // teacher's mic is never played back through their own speakers.
  sourceNode.connect(workletNode);

  store.setMicActive(true);
}

/** Tear down the capture pipeline and release the microphone. */
export async function stopCapture(): Promise<void> {
  const store = useClassroomStore.getState();

  if (workletNode) {
    workletNode.port.onmessage = null;
    workletNode.disconnect();
    workletNode = null;
  }
  if (sourceNode) {
    sourceNode.disconnect();
    sourceNode = null;
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
  if (audioContext) {
    await audioContext.close();
    audioContext = null;
  }

  store.setMicActive(false);
  store.setMicLevel(0);
}
