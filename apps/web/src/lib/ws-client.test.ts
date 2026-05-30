import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  backoffDelay,
  MAX_RECONNECT_ATTEMPTS,
  WSClient,
  type ConnectedMsg,
  type ErrorMsg,
  type FinalTranscriptMsg,
  type GlossMsg,
  type PartialTranscriptMsg,
  type SignSequenceMsg,
} from "./ws-client";

// ── Mock WebSocket ────────────────────────────────────────────────────────────

class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  static instances: MockWebSocket[] = [];

  url: string;
  readyState = MockWebSocket.CONNECTING;
  sent: string[] = [];

  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({});
  }

  // ── test helpers ──
  simulateOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.({});
  }

  simulateMessage(payload: unknown): void {
    const data = typeof payload === "string" ? payload : JSON.stringify(payload);
    this.onmessage?.({ data });
  }

  simulateServerClose(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({});
  }

  static reset(): void {
    MockWebSocket.instances = [];
  }

  static last(): MockWebSocket {
    return MockWebSocket.instances[MockWebSocket.instances.length - 1];
  }
}

const WS = MockWebSocket as unknown as typeof WebSocket;

function makeClient(callbacks = {}, maxReconnectAttempts?: number) {
  return new WSClient({
    url: "ws://localhost:8000/",
    sessionId: "sess-123",
    WebSocketImpl: WS,
    callbacks,
    maxReconnectAttempts,
  });
}

beforeEach(() => {
  MockWebSocket.reset();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

// ── backoff schedule ──────────────────────────────────────────────────────────

describe("backoffDelay", () => {
  it("follows 1s,2s,4s,8s,16s then caps at 30s", () => {
    expect(backoffDelay(0)).toBe(1_000);
    expect(backoffDelay(1)).toBe(2_000);
    expect(backoffDelay(2)).toBe(4_000);
    expect(backoffDelay(3)).toBe(8_000);
    expect(backoffDelay(4)).toBe(16_000);
    expect(backoffDelay(5)).toBe(30_000); // 32s capped
    expect(backoffDelay(9)).toBe(30_000);
  });
});

// ── connection + endpoint ─────────────────────────────────────────────────────

describe("WSClient.connect", () => {
  it("opens a socket at the correct stream endpoint", () => {
    const client = makeClient();
    client.connect();
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.last().url).toBe("ws://localhost:8000/ws/stream/sess-123");
  });

  it("reports connecting then connected", () => {
    const statuses: string[] = [];
    const client = makeClient({ onStatusChange: (s: string) => statuses.push(s) });
    client.connect();
    MockWebSocket.last().simulateOpen();
    expect(statuses).toEqual(["connecting", "connected"]);
  });
});

// ── reconnection logic ────────────────────────────────────────────────────────

describe("WSClient reconnection", () => {
  it("schedules a reconnect with exponential backoff on unexpected close", () => {
    const statuses: string[] = [];
    const client = makeClient({ onStatusChange: (s: string) => statuses.push(s) });
    client.connect();
    MockWebSocket.last().simulateOpen();

    // server drops the connection
    MockWebSocket.last().simulateServerClose();
    expect(statuses).toContain("reconnecting");
    expect(MockWebSocket.instances).toHaveLength(1);

    // first backoff is 1s
    vi.advanceTimersByTime(999);
    expect(MockWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("uses increasing delays across successive failures", () => {
    const client = makeClient();
    client.connect();

    // Fail repeatedly without ever opening; each close schedules the next try.
    MockWebSocket.last().simulateServerClose(); // attempt 0 -> wait 1s
    vi.advanceTimersByTime(1_000);
    expect(MockWebSocket.instances).toHaveLength(2);

    MockWebSocket.last().simulateServerClose(); // attempt 1 -> wait 2s
    vi.advanceTimersByTime(1_999);
    expect(MockWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(3);

    MockWebSocket.last().simulateServerClose(); // attempt 2 -> wait 4s
    vi.advanceTimersByTime(4_000);
    expect(MockWebSocket.instances).toHaveLength(4);
  });

  it("gives up after MAX_RECONNECT_ATTEMPTS and reports error", () => {
    const statuses: string[] = [];
    const client = makeClient({ onStatusChange: (s: string) => statuses.push(s) });
    client.connect();

    // Drive through every allowed reconnect attempt.
    for (let i = 0; i < MAX_RECONNECT_ATTEMPTS; i++) {
      MockWebSocket.last().simulateServerClose();
      vi.advanceTimersByTime(backoffDelay(i));
    }
    // One more close with no attempts left -> error, no new socket.
    const before = MockWebSocket.instances.length;
    MockWebSocket.last().simulateServerClose();
    vi.advanceTimersByTime(60_000);

    expect(MockWebSocket.instances.length).toBe(before);
    expect(statuses[statuses.length - 1]).toBe("error");
  });

  it("resets the attempt counter after a successful reconnect", () => {
    const client = makeClient();
    client.connect();

    MockWebSocket.last().simulateServerClose(); // attempt 0
    vi.advanceTimersByTime(1_000);
    MockWebSocket.last().simulateOpen(); // success -> counter resets

    MockWebSocket.last().simulateServerClose(); // should wait 1s again, not 2s
    vi.advanceTimersByTime(999);
    const count = MockWebSocket.instances.length;
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances.length).toBe(count + 1);
  });

  it("does not reconnect after a manual disconnect", () => {
    const statuses: string[] = [];
    const client = makeClient({ onStatusChange: (s: string) => statuses.push(s) });
    client.connect();
    MockWebSocket.last().simulateOpen();

    client.disconnect();
    vi.advanceTimersByTime(60_000);

    expect(MockWebSocket.instances).toHaveLength(1);
    expect(statuses[statuses.length - 1]).toBe("disconnected");
  });
});

// ── message handling ──────────────────────────────────────────────────────────

describe("WSClient message handling", () => {
  it("dispatches each server message to the matching callback", () => {
    const onConnected = vi.fn();
    const onPartial = vi.fn();
    const onFinal = vi.fn();
    const onGloss = vi.fn();
    const onSignSequence = vi.fn();
    const onError = vi.fn();

    const client = makeClient({
      onConnected,
      onPartial,
      onFinal,
      onGloss,
      onSignSequence,
      onError,
    });
    client.connect();
    const ws = MockWebSocket.last();
    ws.simulateOpen();

    const connected: ConnectedMsg = {
      type: "connected",
      session_id: "sess-123",
      timestamp: "2026-01-01T00:00:00Z",
    };
    const partial: PartialTranscriptMsg = {
      type: "partial",
      text: "hello",
      segment_id: "seg-1",
      start_ms: 0,
      asr_ms: 10,
      gloss_ms: 0,
      total_ms: 10,
    };
    const final: FinalTranscriptMsg = {
      type: "final",
      text: "hello world",
      segment_id: "seg-1",
      asr_ms: 12,
      gloss_ms: 5,
      total_ms: 17,
    };
    const gloss: GlossMsg = {
      type: "gloss",
      tokens: ["HELLO", "WORLD"],
      segment_id: "seg-1",
      asr_ms: 12,
      gloss_ms: 5,
      total_ms: 17,
    };
    const signSeq: SignSequenceMsg = {
      type: "sign_sequence",
      segment_id: "seg-1",
      actions: [],
      timing: { asr_ms: 12, gloss_ms: 5, total_ms: 30 },
    };
    const error: ErrorMsg = { type: "error", message: "boom", code: "E1" };

    ws.simulateMessage(connected);
    ws.simulateMessage(partial);
    ws.simulateMessage(final);
    ws.simulateMessage(gloss);
    ws.simulateMessage(signSeq);
    ws.simulateMessage(error);

    expect(onConnected).toHaveBeenCalledWith(connected);
    expect(onPartial).toHaveBeenCalledWith(partial);
    expect(onFinal).toHaveBeenCalledWith(final);
    expect(onGloss).toHaveBeenCalledWith(gloss);
    expect(onSignSequence).toHaveBeenCalledWith(signSeq);
    expect(onError).toHaveBeenCalledWith(error);
  });

  it("auto-responds to ping with pong", () => {
    const client = makeClient();
    client.connect();
    const ws = MockWebSocket.last();
    ws.simulateOpen();

    ws.simulateMessage({ type: "ping" });

    expect(ws.sent).toContain(JSON.stringify({ type: "pong" }));
  });

  it("ignores malformed JSON without throwing", () => {
    const onError = vi.fn();
    const client = makeClient({ onError });
    client.connect();
    const ws = MockWebSocket.last();
    ws.simulateOpen();

    expect(() => ws.simulateMessage("{not valid json")).not.toThrow();
    expect(onError).not.toHaveBeenCalled();
  });

  it("reports a rolling-average latency from sign sequences", () => {
    const onLatency = vi.fn();
    const client = makeClient({ onLatency });
    client.connect();
    const ws = MockWebSocket.last();
    ws.simulateOpen();

    const seq = (total_ms: number): SignSequenceMsg => ({
      type: "sign_sequence",
      segment_id: "s",
      actions: [],
      timing: { asr_ms: 0, gloss_ms: 0, total_ms },
    });

    ws.simulateMessage(seq(100)); // avg 100
    ws.simulateMessage(seq(200)); // avg 150
    ws.simulateMessage(seq(300)); // avg 200

    expect(onLatency).toHaveBeenNthCalledWith(1, 100);
    expect(onLatency).toHaveBeenNthCalledWith(2, 150);
    expect(onLatency).toHaveBeenNthCalledWith(3, 200);
  });

  it("only averages the last 10 samples", () => {
    const onLatency = vi.fn();
    const client = makeClient({ onLatency });
    client.connect();
    const ws = MockWebSocket.last();
    ws.simulateOpen();

    const seq = (total_ms: number): SignSequenceMsg => ({
      type: "sign_sequence",
      segment_id: "s",
      actions: [],
      timing: { asr_ms: 0, gloss_ms: 0, total_ms },
    });

    // 10 samples of 0, then one of 1100 -> window drops the oldest 0,
    // leaving nine 0s and one 1100 => avg 110.
    for (let i = 0; i < 10; i++) ws.simulateMessage(seq(0));
    ws.simulateMessage(seq(1_100));

    expect(onLatency).toHaveBeenLastCalledWith(110);
  });
});
