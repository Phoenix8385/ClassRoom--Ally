"use client";

import { Activity, Wifi, WifiOff } from "lucide-react";

import type { Language } from "@/store/classroom";
import type { WSStatus } from "@/lib/ws-client";

interface TopBarProps {
  status: WSStatus;
  sessionId: string;
  latencyMs: number;
  language: Language;
}

const STATUS_LABEL: Record<WSStatus, string> = {
  idle: "Idle",
  connecting: "Connecting…",
  connected: "Live",
  reconnecting: "Reconnecting…",
  disconnected: "Disconnected",
  error: "Error",
};

const STATUS_COLOR: Record<WSStatus, string> = {
  idle: "text-slate-400",
  connecting: "text-amber-400",
  connected: "text-emerald-400",
  reconnecting: "text-amber-400",
  disconnected: "text-slate-400",
  error: "text-red-400",
};

export default function TopBar({
  status,
  sessionId,
  latencyMs,
  language,
}: TopBarProps) {
  const online = status === "connected";
  return (
    <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur">
      <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold tracking-tight">
            Classroom Ally
          </span>
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-xs font-medium text-slate-300">
            {language}
          </span>
        </div>

        <div className="flex items-center gap-4 text-xs">
          <span className={`flex items-center gap-1.5 ${STATUS_COLOR[status]}`}>
            {online ? <Wifi size={14} /> : <WifiOff size={14} />}
            {STATUS_LABEL[status]}
          </span>
          {online && (
            <span className="flex items-center gap-1.5 text-slate-400">
              <Activity size={14} />
              {Math.round(latencyMs)} ms
            </span>
          )}
          <span
            className="font-mono text-slate-500"
            title={`Session ${sessionId}`}
          >
            {sessionId ? sessionId.slice(0, 8) : "—"}
          </span>
        </div>
      </div>
    </header>
  );
}
