"use client"

import { useState } from "react"
import { ThumbsUp, ThumbsDown, Flag } from "lucide-react"
import { cn } from "@/lib/utils"

type Vote = "up" | "down" | null

export function FeedbackRow() {
  const [vote, setVote] = useState<Vote>(null)

  return (
    <div className="flex items-center gap-1.5" role="group" aria-label="Sign accuracy feedback">
      <button
        type="button"
        onClick={() => setVote((v) => (v === "up" ? null : "up"))}
        aria-label="Sign was correct"
        aria-pressed={vote === "up"}
        className={cn(
          "rounded-md p-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#111111]",
          vote === "up"
            ? "bg-emerald-500/20 text-emerald-400"
            : "text-[#888] hover:bg-[#1c1c1c] hover:text-white",
        )}
      >
        <ThumbsUp className="h-5 w-5" />
      </button>

      <button
        type="button"
        onClick={() => setVote((v) => (v === "down" ? null : "down"))}
        aria-label="Sign was incorrect"
        aria-pressed={vote === "down"}
        className={cn(
          "rounded-md p-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#111111]",
          vote === "down"
            ? "bg-red-500/20 text-red-400"
            : "text-[#888] hover:bg-[#1c1c1c] hover:text-white",
        )}
      >
        <ThumbsDown className="h-5 w-5" />
      </button>

      <button
        type="button"
        aria-label="Report wrong sign"
        className="flex items-center gap-1.5 rounded-md border border-[#2a2a2a] bg-[#1a1a1a] px-3 py-2 text-xs font-medium text-[#cccccc] transition-colors hover:border-amber-500/50 hover:text-amber-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:ring-offset-2 focus-visible:ring-offset-[#111111]"
      >
        <Flag className="h-4 w-4" />
        Wrong sign?
      </button>
    </div>
  )
}
