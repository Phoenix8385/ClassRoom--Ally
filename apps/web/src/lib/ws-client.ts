"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useClassroomStore } from "@/store/classroom";

// ── Shared domain types ───────────────────────────────────────────────────────

export type SignActionType = "clip" | "keypoints" | "fingerspell";

export interface SignAction {
  token: string;
  type: SignActionType;
  /** Server-side path ("data/isl_clips/hello.mp4") — not loadable by the browser. */
  clip_path: string | null;
  /** Published path under public/signs ("/signs/hello.mp4"). Use this to play. */
  clip_web_path?: string | null;
  letters: string[] | null;
  duration_ms: number;
  /** Canonical glossary word the token resolved to; "" when fingerspelled. */
  word?: string;
  found_in_glossary?: boolean;
}

export interface Timing {
  asr_ms: number;
  gloss_ms: number;
  total_ms: number;
}

// ── Server → client message protocol (discriminated union on `type`) ──────────

export interface ConnectedMsg {
  type: "connected";
  session_id: string;
  timestamp: string;
}

export interface PartialTranscriptMsg {
  type: "partial";
  text: string;
  segment_id: string;
  start_ms: number;
  asr_ms: number;
  gloss_ms: number;
  total_ms: number;
}

export interface FinalTranscriptMsg {
  type: "final";
  text: string;
  segment_id: string;
  asr_ms: number;
  gloss_ms: number;
  total_ms: number;
}

export interface GlossMsg {
  type: "gloss";
  tokens: string[];
  segment_id: string;
  asr_ms: number;
  gloss_ms: number;
  total_ms: number;
}

export interface SignSequenceMsg {
  type: "sign_sequence";
  segment_id: string;
  actions: SignAction[];
  timing: Timing;
}

export interface PingMsg {
  type: "ping";
}

export interface ErrorMsg {
  type: "error";
  message: string;
  code?: string;
}

export type ServerMessage =
  | ConnectedMsg
  | PartialTranscriptMsg
  | FinalTranscriptMsg
  | GlossMsg
  | SignSequenceMsg
  | PingMsg
  | ErrorMsg;

// Client → server messages
export type ClientMessage = { type: "pong" };

// ── Connection status ─────────────────────────────────────────────────────────

export type WSStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

// ── Backoff schedule ──────────────────────────────────────────────────────────

export const MAX_RECONNECT_ATTEMPTS = 10;
const BASE_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;
const LATENCY_WINDOW = 10;

/**
 * Close codes that reconnecting cannot fix. 4004 is WS_SESSION_REJECTED in
 * services/api/app/routers/ws.py — the session id is malformed or absent from
 * the database, so every retry would be refused identically.
 */
const FATAL_CLOSE_CODES: ReadonlySet<number> = new Set([4004]);

/**
 * Exponential backoff: 1s, 2s, 4s, 8s, 16s, then capped at 30s.
 * `attempt` is 0-indexed.
 */
export function backoffDelay(attempt: number): number {
  return Math.min(BASE_DELAY_MS * 2 ** attempt, MAX_DELAY_MS);
}

// ── Callbacks ─────────────────────────────────────────────────────────────────

export interface WSClientCallbacks {
  onStatusChange?: (status: WSStatus) => void;
  onConnected?: (msg: ConnectedMsg) => void;
  onPartial?: (msg: PartialTranscriptMsg) => void;
  onFinal?: (msg: FinalTranscriptMsg) => void;
  onGloss?: (msg: GlossMsg) => void;
  onSignSequence?: (msg: SignSequenceMsg) => void;
  onError?: (msg: ErrorMsg) => void;
  /** Rolling average latency (ms) over the last LATENCY_WINDOW sign sequences. */
  onLatency?: (avgMs: number) => void;
}

export interface WSClientOptions {
  /** Base URL, e.g. ws://localhost:8000 — the path is appended automatically. */
  url: string;
  sessionId: string;
  callbacks?: WSClientCallbacks;
  /** Injectable for tests; defaults to the global WebSocket. */
  WebSocketImpl?: typeof WebSocket;
  maxReconnectAttempts?: number;
}

// ── Client ────────────────────────────────────────────────────────────────────

export class WSClient {
  private readonly url: string;
  private readonly sessionId: string;
  private readonly callbacks: WSClientCallbacks;
  private readonly WS: typeof WebSocket;
  private readonly maxAttempts: number;

  private socket: WebSocket | null = null;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private manualClose = false;
  private fatalClose = false;
  private status: WSStatus = "idle";
  private latencySamples: number[] = [];

  constructor(options: WSClientOptions) {
    this.url = options.url.replace(/\/+$/, "");
    this.sessionId = options.sessionId;
    this.callbacks = options.callbacks ?? {};
    this.WS = options.WebSocketImpl ?? (globalThis.WebSocket as typeof WebSocket);
    this.maxAttempts = options.maxReconnectAttempts ?? MAX_RECONNECT_ATTEMPTS;
  }

  get currentStatus(): WSStatus {
    return this.status;
  }

  connect(): void {
    this.manualClose = false;
    this.fatalClose = false; // an explicit call is the user retrying on purpose
    this.reconnectAttempts = 0;
    this.openSocket();
  }

  /** True once the server refused this session id outright (see FATAL_CLOSE_CODES). */
  get isFatal(): boolean {
    return this.fatalClose;
  }

  disconnect(): void {
    this.manualClose = true;
    this.clearReconnectTimer();
    if (this.socket) {
      this.socket.onclose = null;
      this.socket.onerror = null;
      this.socket.onmessage = null;
      this.socket.onopen = null;
      try {
        this.socket.close();
      } catch {
        /* ignore */
      }
      this.socket = null;
    }
    this.setStatus("disconnected");
  }

  private openSocket(): void {
    this.setStatus(this.reconnectAttempts === 0 ? "connecting" : "reconnecting");

    const endpoint = `${this.url}/ws/stream/${this.sessionId}`;
    const ws = new this.WS(endpoint);
    this.socket = ws;

    ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.setStatus("connected");
    };
    ws.onmessage = (event: MessageEvent) => {
      this.handleRawMessage(typeof event.data === "string" ? event.data : "");
    };
    ws.onerror = () => {
      // A close event normally follows; status is finalised there.
      if (this.status === "connecting" || this.status === "reconnecting") {
        this.setStatus("error");
      }
    };
    ws.onclose = (event: CloseEvent) => {
      this.handleClose(event);
    };
  }

  private handleClose(event?: { code?: number; reason?: string }): void {
    this.socket = null;
    if (this.manualClose) {
      this.setStatus("disconnected");
      return;
    }
    if (event?.code !== undefined && FATAL_CLOSE_CODES.has(event.code)) {
      // The server already sent an `error` frame explaining itself; retrying
      // would just replay the same rejection on a backoff curve.
      this.fatalClose = true;
      this.setStatus("error");
      return;
    }
    if (this.reconnectAttempts >= this.maxAttempts) {
      this.setStatus("error");
      return;
    }
    const delay = backoffDelay(this.reconnectAttempts);
    this.reconnectAttempts += 1;
    this.setStatus("reconnecting");
    this.reconnectTimer = setTimeout(() => this.openSocket(), delay);
  }

  /** Public for unit testing. Parses and dispatches a single raw frame. */
  handleRawMessage(raw: string): void {
    let parsed: ServerMessage;
    try {
      parsed = JSON.parse(raw) as ServerMessage;
    } catch {
      return;
    }

    switch (parsed.type) {
      case "connected":
        this.callbacks.onConnected?.(parsed);
        break;
      case "partial":
        this.callbacks.onPartial?.(parsed);
        break;
      case "final":
        this.callbacks.onFinal?.(parsed);
        break;
      case "gloss":
        this.callbacks.onGloss?.(parsed);
        break;
      case "sign_sequence":
        this.trackLatency(parsed.timing.total_ms);
        this.callbacks.onSignSequence?.(parsed);
        break;
      case "ping":
        this.send({ type: "pong" });
        break;
      case "error":
        this.callbacks.onError?.(parsed);
        break;
      default:
        // Unknown / ignored frame (e.g. server-side pong echoes).
        break;
    }
  }

  private trackLatency(totalMs: number): void {
    this.latencySamples.push(totalMs);
    if (this.latencySamples.length > LATENCY_WINDOW) {
      this.latencySamples.shift();
    }
    const avg =
      this.latencySamples.reduce((a, b) => a + b, 0) /
      this.latencySamples.length;
    this.callbacks.onLatency?.(Math.round(avg));
  }

  private send(msg: ClientMessage): void {
    const open = (this.WS as unknown as { OPEN?: number }).OPEN ?? 1;
    if (this.socket && this.socket.readyState === open) {
      this.socket.send(JSON.stringify(msg));
    }
  }

  /**
   * Send a raw binary audio frame (PCM Int16) to the server. The backend
   * reads these off the socket as `message["bytes"]`. No-op if not open.
   */
  sendBinaryFrame(frame: ArrayBufferLike | ArrayBufferView): void {
    const open = (this.WS as unknown as { OPEN?: number }).OPEN ?? 1;
    if (this.socket && this.socket.readyState === open) {
      this.socket.send(frame as ArrayBufferView);
    }
  }

  /** True when the underlying socket is open and ready to send. */
  get isOpen(): boolean {
    const open = (this.WS as unknown as { OPEN?: number }).OPEN ?? 1;
    return this.socket?.readyState === open;
  }

  private setStatus(status: WSStatus): void {
    if (status === this.status) return;
    this.status = status;
    this.callbacks.onStatusChange?.(status);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}

// ── React hook ────────────────────────────────────────────────────────────────

export interface UseClassroomWS {
  connect: () => void;
  disconnect: () => void;
  status: WSStatus;
  /** The underlying client, e.g. to hand to `startCapture`. Null until mounted. */
  getClient: () => WSClient | null;
}

export function useClassroomWS(sessionId: string): UseClassroomWS {
  const clientRef = useRef<WSClient | null>(null);
  const [status, setStatus] = useState<WSStatus>("idle");

  useEffect(() => {
    if (!sessionId) return;

    const baseUrl = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

    const client = new WSClient({
      url: baseUrl,
      sessionId,
      callbacks: {
        onStatusChange: (s) => {
          setStatus(s);
          useClassroomStore.getState().setConnectionStatus(s);
        },
        onConnected: (m) => {
          useClassroomStore.getState().setSessionId(m.session_id);
        },
        onPartial: (m) => {
          const store = useClassroomStore.getState();
          store.setCurrentSegmentId(m.segment_id);
          store.setPartialTranscript(m.text);
        },
        onFinal: (m) => {
          const store = useClassroomStore.getState();
          store.setCurrentTranscript(m.text);
          store.addTranscriptHistory({
            segmentId: m.segment_id,
            text: m.text,
            timestamp: Date.now(),
          });
        },
        onGloss: (m) => {
          useClassroomStore.getState().setGlossTokens(m.tokens);
        },
        onSignSequence: (m) => {
          useClassroomStore.getState().enqueueSigns(m.actions);
        },
        onLatency: (ms) => {
          useClassroomStore.getState().setLatency(ms);
        },
        onError: (m) => {
          // Surface to console; UI-level error handling can subscribe later.
          console.error("[ws] server error:", m.message, m.code ?? "");
        },
      },
    });

    clientRef.current = client;
    return () => {
      client.disconnect();
      clientRef.current = null;
    };
  }, [sessionId]);

  const connect = useCallback(() => clientRef.current?.connect(), []);
  const disconnect = useCallback(() => clientRef.current?.disconnect(), []);
  const getClient = useCallback(() => clientRef.current, []);

  return { connect, disconnect, status, getClient };
}
