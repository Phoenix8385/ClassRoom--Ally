"use client";

import type { GlossState, TranscriptState } from "@/store/classroom";

interface CaptionBarProps {
  transcript: TranscriptState;
  gloss: GlossState;
  captionsEnabled: boolean;
}

/**
 * Live captions: finalized transcript with the in-flight partial appended, plus
 * the gloss-token strip with the active token highlighted.
 */
export default function CaptionBar({
  transcript,
  gloss,
  captionsEnabled,
}: CaptionBarProps) {
  if (!captionsEnabled) return null;

  const hasText = transcript.current || transcript.partial;

  return (
    <section className="rounded-2xl bg-slate-900/60 p-4">
      <p className="min-h-[2rem] text-lg leading-relaxed">
        {hasText ? (
          <>
            <span className="text-slate-100">{transcript.current}</span>{" "}
            <span className="text-slate-400 italic">{transcript.partial}</span>
          </>
        ) : (
          <span className="text-slate-600">Listening…</span>
        )}
      </p>

      {gloss.tokens.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {gloss.tokens.map((token, i) => (
            <span
              key={`${token}-${i}`}
              className={
                i === gloss.currentIndex
                  ? "rounded bg-blue-500 px-2 py-0.5 text-xs font-semibold text-white"
                  : "rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-300"
              }
            >
              {token}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
