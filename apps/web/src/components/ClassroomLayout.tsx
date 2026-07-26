"use client";

import type { ReactNode } from "react";

interface ClassroomLayoutProps {
  topBar: ReactNode;
  avatar: ReactNode;
  caption: ReactNode;
  controls: ReactNode;
  feedback: ReactNode;
}

/**
 * Page scaffold for the live classroom. Pure layout — every region is passed in
 * as a slot so the page owns data wiring and this component owns structure.
 */
export default function ClassroomLayout({
  topBar,
  avatar,
  caption,
  controls,
  feedback,
}: ClassroomLayoutProps) {
  return (
    <div className="flex h-full min-h-screen flex-col bg-slate-950 text-slate-100">
      {topBar}
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-4 px-4 py-4">
        <div className="flex-1">{avatar}</div>
        {caption}
        {feedback}
      </main>
      <footer className="border-t border-slate-800 bg-slate-900/60">
        <div className="mx-auto w-full max-w-5xl px-4 py-3">{controls}</div>
      </footer>
    </div>
  );
}
