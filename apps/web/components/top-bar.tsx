"use client"

import { Settings } from "lucide-react"
import { cn } from "@/lib/utils"
import type { SignLanguage } from "@/hooks/use-signing-session"

interface TopBarProps {
  connected: boolean
  language: SignLanguage
  onLanguageChange: (lang: SignLanguage) => void
  latencyMs: number
  onOpenSettings: () => void
}

export function TopBar({
  connected,
  language,
  onLanguageChange,
  latencyMs,
  onOpenSettings,
}: TopBarProps) {
  const latencyTone =
    latencyMs < 150 ? "text-emerald-400" : latencyMs < 250 ? "text-amber-400" : "text-red-400"

  return (
    <header
      className="flex h-14 shrink-0 items-center justify-between border-b border-[#1f1f1f] bg-[#0a0a0a] px-4"
      role="banner"
    >
      {/* Left: connection status */}
      <div className="flex min-w-0 items-center gap-2">
        <span
          className={cn(
            "h-2.5 w-2.5 shrink-0 rounded-full",
            connected ? "bg-emerald-500" : "bg-red-500",
          )}
          aria-hidden="true"
        />
        <span className="truncate text-sm font-medium text-[#cccccc]">
          {connected ? "Connected" : "Disconnected"}
        </span>
        <span className="sr-only">
          Speech recognition is {connected ? "connected" : "disconnected"}
        </span>
      </div>

      {/* Center: title */}
      <h1 className="absolute left-1/2 -translate-x-1/2 text-base font-bold text-white">
        Classroom Ally
      </h1>

      {/* Right: language toggle + settings + latency */}
      <div className="flex items-center gap-3">
        <div
          className="flex items-center rounded-md border border-[#2a2a2a] bg-[#141414] p-0.5"
          role="group"
          aria-label="Sign language selection"
        >
          {(["ISL", "ASL"] as const).map((lang) => {
            const active = language === lang
            return (
              <button
                key={lang}
                type="button"
                onClick={() => onLanguageChange(lang)}
                aria-pressed={active}
                className={cn(
                  "rounded px-2.5 py-1 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0a0a0a]",
                  active ? "bg-emerald-500 text-[#0a0a0a]" : "text-[#aaaaaa] hover:text-white",
                )}
              >
                {lang}
              </button>
            )
          })}
        </div>

        <button
          type="button"
          onClick={onOpenSettings}
          aria-label="Open settings"
          className="rounded-md p-1.5 text-[#aaaaaa] transition-colors hover:bg-[#1a1a1a] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0a0a0a]"
        >
          <Settings className="h-5 w-5" />
        </button>

        <span
          className={cn(
            "rounded-md border border-[#2a2a2a] bg-[#141414] px-2 py-1 font-mono text-xs tabular-nums",
            latencyTone,
          )}
          aria-label={`Latency ${latencyMs} milliseconds`}
        >
          {latencyMs}ms
        </span>
      </div>
    </header>
  )
}
