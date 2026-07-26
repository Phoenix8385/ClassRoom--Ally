"use client";

import { Mic, MicOff } from "lucide-react";

interface SetupModalProps {
  open: boolean;
  permissionDenied: boolean;
  requesting: boolean;
  onRequest: () => void;
}

/**
 * Blocking pre-session modal that asks the teacher to grant microphone access.
 * Shown until permission is granted; offers a retry path if it was denied.
 */
export default function SetupModal({
  open,
  permissionDenied,
  requesting,
  onRequest,
}: SetupModalProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-blue-500/15 text-blue-400">
          {permissionDenied ? <MicOff size={26} /> : <Mic size={26} />}
        </div>

        <h2 className="text-lg font-semibold text-slate-100">
          {permissionDenied ? "Microphone blocked" : "Microphone access"}
        </h2>
        <p className="mt-2 text-sm text-slate-400">
          {permissionDenied
            ? "Classroom Ally needs your microphone to translate speech into sign language. Enable it in your browser's site settings, then try again."
            : "Classroom Ally listens to the teacher's voice and translates it into sign language in real time. Grant microphone access to begin."}
        </p>

        <button
          type="button"
          onClick={onRequest}
          disabled={requesting}
          className="mt-5 w-full rounded-full bg-blue-500 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-600 disabled:opacity-60"
        >
          {requesting
            ? "Requesting…"
            : permissionDenied
              ? "Try again"
              : "Enable microphone"}
        </button>
      </div>
    </div>
  );
}
