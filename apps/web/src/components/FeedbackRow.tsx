"use client";

import { ThumbsDown, ThumbsUp, X } from "lucide-react";

import type { FeedbackState } from "@/store/classroom";

interface FeedbackRowProps {
  feedback: FeedbackState;
  currentSegmentId: string | null;
  onRate: (segmentId: string, rating: "up" | "down") => void;
  onDismiss: () => void;
}

/**
 * Lightweight per-segment quality prompt: "Was this translation correct?".
 * Only renders when the store flags a segment as awaiting feedback.
 */
export default function FeedbackRow({
  feedback,
  currentSegmentId,
  onRate,
  onDismiss,
}: FeedbackRowProps) {
  const segmentId = feedback.pendingSegmentId ?? currentSegmentId;
  if (!feedback.showFeedbackUI || !segmentId) return null;

  return (
    <section className="flex items-center justify-between gap-4 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-2 text-sm">
      <span className="text-slate-300">Was this translation correct?</span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onRate(segmentId, "up")}
          className="rounded-full p-2 text-slate-300 hover:bg-emerald-500/20 hover:text-emerald-400"
          aria-label="Correct"
        >
          <ThumbsUp size={16} />
        </button>
        <button
          type="button"
          onClick={() => onRate(segmentId, "down")}
          className="rounded-full p-2 text-slate-300 hover:bg-red-500/20 hover:text-red-400"
          aria-label="Incorrect"
        >
          <ThumbsDown size={16} />
        </button>
        <button
          type="button"
          onClick={onDismiss}
          className="rounded-full p-2 text-slate-500 hover:bg-slate-800 hover:text-slate-300"
          aria-label="Dismiss"
        >
          <X size={16} />
        </button>
      </div>
    </section>
  );
}
