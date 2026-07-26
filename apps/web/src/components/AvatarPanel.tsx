"use client";

import SignAvatar from "@/components/SignAvatar";
import type { AvatarMode, SignsState } from "@/store/classroom";

interface AvatarPanelProps {
  signs: SignsState;
  avatarMode: AvatarMode;
}

/**
 * Hosts the signing avatar. SignAvatar reads the live sign queue from the store
 * directly; `signs`/`avatarMode` are passed for the panel's own status chrome.
 */
export default function AvatarPanel({ signs, avatarMode }: AvatarPanelProps) {
  return (
    <section className="relative flex h-full flex-col items-center justify-center rounded-2xl bg-slate-900/40 p-4">
      <div className="absolute left-4 top-4 z-10 flex items-center gap-2 text-xs text-slate-400">
        <span className="rounded bg-slate-800 px-2 py-1 capitalize">
          {avatarMode}
        </span>
        {signs.isPlaying && signs.current && (
          <span className="rounded bg-blue-500/20 px-2 py-1 font-medium text-blue-300">
            {signs.current.token}
          </span>
        )}
      </div>

      <div className="mx-auto w-full max-w-sm">
        <SignAvatar />
      </div>

      {signs.queue.length > 0 && (
        <p className="absolute bottom-4 right-4 text-xs text-slate-500">
          {signs.queue.length} queued
        </p>
      )}
    </section>
  );
}
