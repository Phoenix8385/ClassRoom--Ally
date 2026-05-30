# ADR 002 — WebSocket over WebRTC for Real-Time Communication

## Status: Accepted

## Context

Classroom Ally streams data in real time between the backend and browser clients in several flows:

- Live transcription chunks from the faster-whisper pipeline to the frontend
- ISL sign cue events (which sign to render next) to the avatar renderer
- Teacher annotation and highlight events broadcast to students
- Heartbeat and session state synchronisation

The system needs a real-time transport layer that is reliable, low-latency enough for classroom use, and operationally manageable by a small team. Two primary candidates were evaluated: **WebSocket** (RFC 6455, persistent TCP connection via a server) and **WebRTC** (peer-to-peer or SFU-mediated UDP channels).

Classroom Ally targets school deployments where concurrent users per session are well under 30 (one teacher + up to ~29 students in a typical Indian classroom).

## Decision

Use **WebSocket** (via the Next.js API route WebSocket upgrade, backed by a Node.js `ws` server or a lightweight standalone WebSocket service) as the sole real-time transport layer.

All real-time messages — transcription deltas, sign cues, annotation events, session state — are encoded as JSON frames sent over a single persistent WebSocket connection per client.

## Rationale

- **Concurrency ceiling removes the P2P argument**: WebRTC's main advantage is eliminating server bandwidth for media at scale. With fewer than 30 concurrent users, the server-side bandwidth for text-frame and cue-event traffic is negligible. The scalability gains of WebRTC do not materialise at this load.
- **No peer-to-peer requirement**: Classroom Ally does not stream audio or video between peers. All media (microphone audio) flows from the teacher's browser to the backend transcription service, and the output (text + sign cues) flows back to all students. This is a hub-and-spoke pattern, which WebSocket handles naturally.
- **Operational simplicity**: WebSocket connections are visible in standard HTTP server logs, proxied by any reverse proxy (Nginx, Caddy, Vercel Edge), and debuggable in Chrome DevTools. WebRTC requires STUN/TURN infrastructure, ICE candidate negotiation, and SDP offer/answer handling — all of which add operational surface area with no benefit at this scale.
- **Firewall and network compatibility**: School networks frequently block UDP traffic or restrict ports. WebSocket runs over TCP 443 (WSS) and traverses corporate and school firewalls without special configuration. WebRTC's UDP-first approach regularly fails in such environments and falls back to TCP TURN relays, which erases its latency advantage.
- **Simpler server implementation**: A WebSocket server is a few dozen lines of Node.js. An SFU (Selective Forwarding Unit) for WebRTC would require a dedicated media server (mediasoup, Janus, Livekit) — a separate infrastructure component to deploy, monitor, and scale.

## Alternatives Rejected

| Alternative | Reason Rejected |
|---|---|
| **WebRTC (browser-to-browser P2P)** | No P2P use case exists. All data routes through the server. P2P would bypass the transcription backend, not complement it. |
| **WebRTC with SFU (Livekit, mediasoup)** | Adds a dedicated media server to the infrastructure. Justified for video conferencing at scale; not justified for text-frame and cue-event traffic under 30 users. |
| **Server-Sent Events (SSE)** | Unidirectional (server → client only). Cannot carry client→server annotation events or session control messages without a separate HTTP channel. Adds complexity without simplifying anything. |
| **HTTP long-polling** | Higher latency, more server connections per logical session, not suitable for sub-second transcription chunk delivery. |
| **gRPC streaming** | Excellent for service-to-service; browser support requires grpc-web proxy. Adds infrastructure complexity for marginal benefit over WebSocket at this scale. |

## Consequences

**Positive**
- Single, well-understood transport for all real-time flows — easier to debug and monitor.
- No STUN/TURN infrastructure to operate or pay for.
- Works reliably on school/corporate networks that block UDP.
- Next.js API routes support WebSocket upgrades; no separate service needed for development.
- Standard browser DevTools show all frames — rapid iteration during development.

**Negative**
- TCP head-of-line blocking means a lost packet stalls the entire stream; for transcription deltas this is acceptable (a brief pause), but would be unacceptable for real-time audio/video (not a current use case).
- Vertical scale limit: a single WebSocket server process handles all connections. At significantly higher concurrency (hundreds of sessions), a message broker (Redis pub/sub, NATS) or horizontal WebSocket sharding would be needed. Acceptable given the stated 30-user ceiling.
- If a future requirement adds live video streaming between classroom participants, this decision will need to be revisited and WebRTC added alongside WebSocket.
