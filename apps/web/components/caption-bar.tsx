"use client"

import { Fragment } from "react"
import { cn } from "@/lib/utils"
import { FeedbackRow } from "@/components/feedback-row"

interface CaptionBarProps {
  transcript: string[]
  activeIndex: number
  currentGloss: string[]
  captionsOn: boolean
}

export function CaptionBar({ transcript, activeIndex, currentGloss, captionsOn }: CaptionBarProps) {
  return (
    <footer
      className="flex h-[140px] shrink-0 items-center justify-between gap-6 border-t border-[#1f1f1f] bg-[#111111] px-6"
      aria-label="Live captions"
    >
      <div className="min-w-0 flex-1">
        {captionsOn ? (
          <>
            {/* Main caption: 28px white, current word highlighted yellow */}
            <p
              className="line-clamp-2 text-[28px] font-medium leading-snug text-white"
              aria-live="polite"
              aria-atomic="true"
            >
              {transcript.map((word, i) => (
                <Fragment key={`${word}-${i}`}>
                  <span
                    className={cn(
                      i === activeIndex && "rounded bg-[#FFD700]/10 px-1 font-semibold text-[#FFD700]",
                    )}
                  >
                    {word}
                  </span>{" "}
                </Fragment>
              ))}
            </p>

            {/* Gloss tokens: #888888 18px, bullet-separated */}
            <p className="mt-2 flex flex-wrap items-center text-[18px] text-[#888888]">
              <span className="sr-only">Gloss tokens: </span>
              {currentGloss.map((token, i) => (
                <Fragment key={`${token}-${i}`}>
                  {i > 0 && <span className="px-2 text-[#555]" aria-hidden="true">•</span>}
                  <span className="font-mono uppercase tracking-wide">{token}</span>
                </Fragment>
              ))}
            </p>
          </>
        ) : (
          <p className="text-[18px] italic text-[#666]">Captions hidden</p>
        )}
      </div>

      {/* Feedback controls */}
      <div className="shrink-0">
        <FeedbackRow />
      </div>
    </footer>
  )
}
