/** Thin REST client for the FastAPI backend. WebSocket traffic lives in ws-client.ts. */

const API_BASE = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

/** Mirrors SessionResponse in services/api/app/routers/sessions.py. */
export interface SessionResponse {
  id: string;
  teacher_name: string;
  language: string;
  status: string;
}

export type Language = "ISL" | "ASL";

/**
 * Register a classroom session with the backend.
 *
 * The returned `id` is the only session id the WebSocket endpoint will accept —
 * it looks the row up in Postgres and rejects anything it cannot resolve, so a
 * client-invented UUID is refused. Always route with the id this returns.
 */
export async function createSession(
  teacherName: string,
  language: Language = "ISL",
): Promise<SessionResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ teacher_name: teacherName, language }),
    });
  } catch {
    throw new Error(
      `Cannot reach the server at ${API_BASE}. Is the API running?`,
    );
  }

  if (!response.ok) {
    throw new Error(`Could not start a session (HTTP ${response.status}).`);
  }
  return (await response.json()) as SessionResponse;
}
