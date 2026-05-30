# ADR 004 — Next.js 15 App Router over Plain React SPA

## Status: Accepted

## Context

Classroom Ally's frontend serves three distinct surfaces:

1. **Teacher dashboard** — session control, live transcript view, annotation tools.
2. **Student view** — real-time captions, ISL avatar renderer, classroom content display.
3. **Admin/setup pages** — school configuration, user management, device pairing.

The team needed to choose a frontend framework and rendering strategy. The two primary candidates were:

1. **Plain React SPA** (Vite or Create React App) — a client-side rendered single-page application, typically deployed as static files on a CDN or simple file server.
2. **Next.js 15 with the App Router** — a React meta-framework supporting Server Components, Server Actions, streaming SSR, and static generation, with first-class deployment on Vercel.

## Decision

Use **Next.js 15 with the App Router** as the frontend framework. Server Components are used for initial data-heavy pages (dashboard skeleton, admin tables). Client Components are used for interactive, real-time surfaces (ISL avatar, live transcript, WebSocket-connected widgets). The application is deployed on **Vercel** for the hosted/demo environment and can be self-hosted via `next start` for on-premises school deployments.

## Rationale

**Server Components for initial load performance**
The student view must be usable on low-bandwidth school connections (2–4 Mbps shared Wi-Fi). Server Components render the page shell, navigation, and static content on the server and send HTML to the browser, eliminating the blank-screen flash and large JS bundle download required by a pure SPA. The ISL avatar and live transcript widgets are Client Components that hydrate after the initial paint — students see a usable page faster.

**Colocation of API routes and frontend**
Classroom Ally's backend surface is modest: WebSocket upgrade, transcription proxy, sign lookup, session management. Next.js API routes (and Route Handlers in App Router) allow these to live in the same repository and deployment unit as the frontend. A plain React SPA would require a separately deployed backend (Express, FastAPI, etc.), adding infrastructure complexity and CORS configuration.

**Vercel deployment**
The project needs a zero-config hosted demo for school pilots and evaluations. Vercel's native Next.js support means `git push` deploys both the frontend and API routes with automatic SSL, edge caching for static assets, and preview deployments per PR. Deploying a React SPA + separate API server to achieve the same result requires more orchestration (e.g., separate Render/Railway service + Netlify/Cloudflare Pages, with CORS wiring).

**Streaming and Suspense**
The App Router's built-in support for React Suspense and streaming responses allows the transcript and admin pages to progressively stream in data rather than waiting for all data to load before rendering — important for pages that aggregate session history.

**Self-hosting compatibility**
For on-premises school deployments (required by the privacy constraints in ADR-003), `next start` runs the full application as a Node.js server. No separate static file server or API server is needed. A plain SPA would require deploying a static file server alongside the backend API separately.

## Alternatives Rejected

| Alternative | Reason Rejected |
|---|---|
| **Plain React SPA (Vite + React Router)** | No server-side rendering; initial load is a blank screen until JS downloads and executes — poor on slow school networks. API layer must be a separate deployed service, increasing infrastructure complexity. No built-in Vercel integration for API routes. |
| **Remix** | Comparable feature set to Next.js App Router. Next.js has larger ecosystem, more community plugins (particularly for real-time and avatar libraries), and Vercel's first-party support guarantees long-term maintenance alignment. Team familiarity also favours Next.js. |
| **SvelteKit** | Excellent performance characteristics but requires the team to learn a non-React ecosystem. ISL avatar libraries and real-time component patterns are overwhelmingly React-ecosystem. Switching languages mid-stack increases onboarding cost. |
| **Next.js 15 Pages Router (legacy)** | Pages Router lacks React Server Components and the collocated layout/loading/error file conventions of App Router. App Router is the officially recommended path in Next.js 13+; new projects should not start on the legacy router. |
| **Astro** | Optimised for content-heavy, mostly-static sites. Classroom Ally's student view and teacher dashboard are highly interactive real-time applications — Astro's island architecture would require wrapping almost every component as a client island, defeating its main advantage. |

## Consequences

**Positive**
- Faster initial page load on low-bandwidth connections due to Server Components HTML delivery.
- Single deployment unit (frontend + API routes) simplifies hosting and local development.
- Vercel preview deployments per PR enable fast stakeholder feedback during school pilots.
- Built-in image optimisation, font optimisation, and static asset caching reduce CDN configuration effort.
- Streaming SSR for data-heavy pages improves perceived performance without manual loading state management.

**Negative**
- App Router has a steeper learning curve than a plain React SPA; the mental model of Server vs. Client Components requires explicit attention, especially when integrating third-party libraries that assume a browser environment (e.g., MediaPipe, WebSocket clients) — these must be explicitly marked `"use client"`.
- Next.js version upgrades (e.g., 15 → 16) occasionally include breaking changes in the App Router's caching and data-fetching behaviour, requiring periodic migration effort.
- Self-hosted `next start` requires a Node.js runtime on the school server. A pure SPA could be served by any static file server (Nginx, Apache). This is a minor constraint given that the transcription sidecar (ADR-003) already requires Python/Node on the same machine.
- Vendor alignment with Vercel means some features (Edge Middleware, ISR, On-Demand Revalidation) work best or only on Vercel infrastructure. Self-hosted deployments may require workarounds for advanced caching features.
