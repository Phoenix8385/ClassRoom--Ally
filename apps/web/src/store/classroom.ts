"use client";

import { create } from "zustand";
import { immer } from "zustand/middleware/immer";

import type { SignAction, WSStatus } from "@/lib/ws-client";

// ── Domain types ──────────────────────────────────────────────────────────────

export type Language = "ISL" | "ASL";
export type AvatarMode = "clips" | "avatar";

export interface TranscriptEntry {
  segmentId: string;
  text: string;
  timestamp: number;
}

export interface ConnectionState {
  status: WSStatus;
  sessionId: string | null;
  latencyMs: number;
}

export interface TranscriptState {
  current: string;
  partial: string;
  history: TranscriptEntry[];
  currentSegmentId: string | null;
}

export interface GlossState {
  tokens: string[];
  currentIndex: number;
}

export interface SignsState {
  queue: SignAction[];
  current: SignAction | null;
  isPlaying: boolean;
}

export interface SettingsState {
  language: Language;
  speed: number;
  captionsEnabled: boolean;
  avatarMode: AvatarMode;
}

export interface MicState {
  level: number;
  isActive: boolean;
  permissionDenied: boolean;
}

export interface FeedbackState {
  pendingSegmentId: string | null;
  showFeedbackUI: boolean;
}

// ── Store shape ───────────────────────────────────────────────────────────────

export interface ClassroomState {
  connection: ConnectionState;
  transcript: TranscriptState;
  gloss: GlossState;
  signs: SignsState;
  settings: SettingsState;
  mic: MicState;
  feedback: FeedbackState;
}

export interface ClassroomActions {
  // connection
  setConnectionStatus: (status: WSStatus) => void;
  setSessionId: (sessionId: string | null) => void;
  setLatency: (latencyMs: number) => void;

  // transcript
  setCurrentTranscript: (text: string) => void;
  setPartialTranscript: (text: string) => void;
  setCurrentSegmentId: (segmentId: string | null) => void;
  addTranscriptHistory: (entry: TranscriptEntry) => void;
  clearTranscript: () => void;

  // gloss
  setGlossTokens: (tokens: string[]) => void;
  setGlossIndex: (index: number) => void;
  advanceGloss: () => void;

  // signs
  enqueueSigns: (actions: SignAction[]) => void;
  shiftSign: () => SignAction | null;
  setCurrentSign: (action: SignAction | null) => void;
  setIsPlaying: (isPlaying: boolean) => void;
  clearSigns: () => void;

  // settings
  setLanguage: (language: Language) => void;
  setSpeed: (speed: number) => void;
  setCaptionsEnabled: (enabled: boolean) => void;
  setAvatarMode: (mode: AvatarMode) => void;

  // mic
  setMicLevel: (level: number) => void;
  setMicActive: (isActive: boolean) => void;
  setMicPermissionDenied: (denied: boolean) => void;

  // feedback
  setPendingFeedback: (segmentId: string | null) => void;
  setShowFeedbackUI: (show: boolean) => void;
  clearFeedback: () => void;

  // global
  reset: () => void;
}

export type ClassroomStore = ClassroomState & ClassroomActions;

// ── Initial state ─────────────────────────────────────────────────────────────

const initialState: ClassroomState = {
  connection: { status: "idle", sessionId: null, latencyMs: 0 },
  transcript: { current: "", partial: "", history: [], currentSegmentId: null },
  gloss: { tokens: [], currentIndex: 0 },
  signs: { queue: [], current: null, isPlaying: false },
  settings: {
    language: "ISL",
    speed: 1,
    captionsEnabled: true,
    avatarMode: "clips",
  },
  mic: { level: 0, isActive: false, permissionDenied: false },
  feedback: { pendingSegmentId: null, showFeedbackUI: false },
};

// ── Store ─────────────────────────────────────────────────────────────────────

export const useClassroomStore = create<ClassroomStore>()(
  immer((set, get) => ({
    ...initialState,

    // connection
    setConnectionStatus: (status) =>
      set((s) => {
        s.connection.status = status;
      }),
    setSessionId: (sessionId) =>
      set((s) => {
        s.connection.sessionId = sessionId;
      }),
    setLatency: (latencyMs) =>
      set((s) => {
        s.connection.latencyMs = latencyMs;
      }),

    // transcript
    setCurrentTranscript: (text) =>
      set((s) => {
        s.transcript.current = text;
        s.transcript.partial = "";
      }),
    setPartialTranscript: (text) =>
      set((s) => {
        s.transcript.partial = text;
      }),
    setCurrentSegmentId: (segmentId) =>
      set((s) => {
        s.transcript.currentSegmentId = segmentId;
      }),
    addTranscriptHistory: (entry) =>
      set((s) => {
        s.transcript.history.push(entry);
      }),
    clearTranscript: () =>
      set((s) => {
        s.transcript.current = "";
        s.transcript.partial = "";
        s.transcript.history = [];
        s.transcript.currentSegmentId = null;
      }),

    // gloss
    setGlossTokens: (tokens) =>
      set((s) => {
        s.gloss.tokens = tokens;
        s.gloss.currentIndex = 0;
      }),
    setGlossIndex: (index) =>
      set((s) => {
        s.gloss.currentIndex = index;
      }),
    advanceGloss: () =>
      set((s) => {
        if (s.gloss.currentIndex < s.gloss.tokens.length - 1) {
          s.gloss.currentIndex += 1;
        }
      }),

    // signs
    enqueueSigns: (actions) =>
      set((s) => {
        s.signs.queue.push(...actions);
      }),
    shiftSign: () => {
      const next = get().signs.queue[0] ?? null;
      set((s) => {
        s.signs.current = s.signs.queue.shift() ?? null;
      });
      return next;
    },
    setCurrentSign: (action) =>
      set((s) => {
        s.signs.current = action;
      }),
    setIsPlaying: (isPlaying) =>
      set((s) => {
        s.signs.isPlaying = isPlaying;
      }),
    clearSigns: () =>
      set((s) => {
        s.signs.queue = [];
        s.signs.current = null;
        s.signs.isPlaying = false;
      }),

    // settings
    setLanguage: (language) =>
      set((s) => {
        s.settings.language = language;
      }),
    setSpeed: (speed) =>
      set((s) => {
        s.settings.speed = speed;
      }),
    setCaptionsEnabled: (enabled) =>
      set((s) => {
        s.settings.captionsEnabled = enabled;
      }),
    setAvatarMode: (mode) =>
      set((s) => {
        s.settings.avatarMode = mode;
      }),

    // mic
    setMicLevel: (level) =>
      set((s) => {
        s.mic.level = level;
      }),
    setMicActive: (isActive) =>
      set((s) => {
        s.mic.isActive = isActive;
      }),
    setMicPermissionDenied: (denied) =>
      set((s) => {
        s.mic.permissionDenied = denied;
      }),

    // feedback
    setPendingFeedback: (segmentId) =>
      set((s) => {
        s.feedback.pendingSegmentId = segmentId;
      }),
    setShowFeedbackUI: (show) =>
      set((s) => {
        s.feedback.showFeedbackUI = show;
      }),
    clearFeedback: () =>
      set((s) => {
        s.feedback.pendingSegmentId = null;
        s.feedback.showFeedbackUI = false;
      }),

    // global
    reset: () =>
      set((s) => {
        Object.assign(s, structuredClone(initialState));
      }),
  })),
);
