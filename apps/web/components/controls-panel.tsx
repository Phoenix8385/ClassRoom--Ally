"use client"

import { useState } from "react"
import { BookOpen, ChevronRight } from "lucide-react"
import { cn } from "@/lib/utils"
import { Switch } from "@/components/ui/switch"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import type { SignLanguage, SignSpeed } from "@/hooks/use-signing-session"

interface ControlsPanelProps {
  micLevels: number[]
  connected: boolean
  onToggleConnection: () => void
  speed: SignSpeed
  onSpeedChange: (s: SignSpeed) => void
  captionsOn: boolean
  onCaptionsChange: (v: boolean) => void
  language: SignLanguage
  onLanguageChange: (l: SignLanguage) => void
  collapsed: boolean
  onCollapse: () => void
}

const SPEEDS: SignSpeed[] = ["Slow", "Normal", "Fast"]

const GLOSSARY = [
  { gloss: "GOOD", meaning: "Flat hand moves down from chin." },
  { gloss: "MORNING", meaning: "Forearm rises like a sunrise." },
  { gloss: "CLASS", meaning: "Both C-hands draw a circle outward." },
  { gloss: "LEARN", meaning: "Grab info from palm to forehead." },
  { gloss: "PLANT", meaning: "Thumb pushes up through the other hand." },
  { gloss: "SUN", meaning: "Index draws a circle, hand opens downward." },
]

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[#666]">
      {children}
    </h3>
  )
}

export function ControlsPanel({
  micLevels,
  connected,
  onToggleConnection,
  speed,
  onSpeedChange,
  captionsOn,
  onCaptionsChange,
  language,
  onLanguageChange,
  collapsed,
  onCollapse,
}: ControlsPanelProps) {
  const [glossaryOpen, setGlossaryOpen] = useState(false)

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={onCollapse}
        aria-label="Expand controls panel"
        className="flex h-full w-10 shrink-0 items-center justify-center rounded-2xl border border-[#1f1f1f] bg-[#0d0d0d] text-[#888] transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
      >
        <ChevronRight className="h-5 w-5 rotate-180" />
      </button>
    )
  }

  return (
    <aside
      aria-label="Controls"
      className="flex h-full w-[280px] shrink-0 flex-col overflow-y-auto rounded-2xl border border-[#1f1f1f] bg-[#0d0d0d] p-4"
    >
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-white">Controls</h2>
        <button
          type="button"
          onClick={onCollapse}
          aria-label="Collapse controls panel"
          className="rounded-md p-1 text-[#888] transition-colors hover:bg-[#1a1a1a] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      {/* Mic level */}
      <div className="mb-5">
        <SectionLabel>Mic Level</SectionLabel>
        <div
          className="flex h-12 items-end gap-1.5"
          role="meter"
          aria-label="Microphone input level"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round((micLevels.reduce((a, b) => a + b, 0) / micLevels.length) * 100)}
        >
          {micLevels.map((level, i) => (
            <div
              key={i}
              className="flex-1 rounded-sm bg-emerald-500 transition-[height] duration-150 ease-out"
              style={{ height: `${Math.max(8, level * 100)}%` }}
              aria-hidden="true"
            />
          ))}
        </div>
      </div>

      {/* Connection status */}
      <div className="mb-5">
        <SectionLabel>Connection</SectionLabel>
        <button
          type="button"
          onClick={onToggleConnection}
          aria-label={`Connection is ${connected ? "active" : "inactive"}. Toggle.`}
          className="flex w-full items-center justify-between rounded-lg border border-[#222] bg-[#141414] px-3 py-2.5 text-left transition-colors hover:border-[#333] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
        >
          <span className="flex items-center gap-2">
            <span
              className={cn("h-2 w-2 rounded-full", connected ? "bg-emerald-500" : "bg-red-500")}
              aria-hidden="true"
            />
            <span className="text-sm text-[#ccc]">{connected ? "Connected" : "Disconnected"}</span>
          </span>
          <span className="text-xs text-[#666]">{connected ? "Live" : "Off"}</span>
        </button>
      </div>

      {/* Speed slider */}
      <div className="mb-5">
        <SectionLabel>Signing Speed</SectionLabel>
        <div
          className="flex items-center rounded-lg border border-[#222] bg-[#141414] p-1"
          role="group"
          aria-label="Signing speed"
        >
          {SPEEDS.map((s) => {
            const active = speed === s
            return (
              <button
                key={s}
                type="button"
                onClick={() => onSpeedChange(s)}
                aria-pressed={active}
                className={cn(
                  "flex-1 rounded-md py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400",
                  active ? "bg-emerald-500 text-[#0a0a0a]" : "text-[#999] hover:text-white",
                )}
              >
                {s}
              </button>
            )
          })}
        </div>
      </div>

      {/* Captions toggle */}
      <div className="mb-4 flex items-center justify-between">
        <label htmlFor="captions-toggle" className="text-sm text-[#ccc]">
          Captions
        </label>
        <Switch
          id="captions-toggle"
          checked={captionsOn}
          onCheckedChange={onCaptionsChange}
          aria-label="Toggle captions"
        />
      </div>

      {/* Language toggle */}
      <div className="mb-5">
        <SectionLabel>Language</SectionLabel>
        <div
          className="flex items-center rounded-lg border border-[#222] bg-[#141414] p-1"
          role="group"
          aria-label="Sign language"
        >
          {(["ISL", "ASL"] as const).map((l) => {
            const active = language === l
            return (
              <button
                key={l}
                type="button"
                onClick={() => onLanguageChange(l)}
                aria-pressed={active}
                className={cn(
                  "flex-1 rounded-md py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400",
                  active ? "bg-emerald-500 text-[#0a0a0a]" : "text-[#999] hover:text-white",
                )}
              >
                {l}
              </button>
            )
          })}
        </div>
      </div>

      {/* Glossary */}
      <div className="mt-auto">
        <Dialog open={glossaryOpen} onOpenChange={setGlossaryOpen}>
          <DialogTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center justify-center gap-2 rounded-lg border border-[#2a2a2a] bg-[#1a1a1a] py-2.5 text-sm font-medium text-white transition-colors hover:border-emerald-500/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
            >
              <BookOpen className="h-4 w-4" />
              Glossary
            </button>
          </DialogTrigger>
          <DialogContent className="border-[#222] bg-[#0d0d0d] text-white">
            <DialogHeader>
              <DialogTitle className="text-white">{language} Glossary</DialogTitle>
              <DialogDescription className="text-[#888]">
                Common gloss tokens and how they are signed.
              </DialogDescription>
            </DialogHeader>
            <ul className="mt-2 max-h-[50vh] space-y-2 overflow-y-auto">
              {GLOSSARY.map((g) => (
                <li
                  key={g.gloss}
                  className="rounded-lg border border-[#1f1f1f] bg-[#141414] p-3"
                >
                  <p className="font-mono text-sm font-semibold uppercase tracking-wide text-[#FFD700]">
                    {g.gloss}
                  </p>
                  <p className="mt-0.5 text-sm text-[#aaa]">{g.meaning}</p>
                </li>
              ))}
            </ul>
          </DialogContent>
        </Dialog>
      </div>
    </aside>
  )
}
