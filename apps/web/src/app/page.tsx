"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Github, Play } from "lucide-react";

const GITHUB_URL = "https://github.com/Phoenix8385/ClassRoom--Ally";

const TEAM = [
  "Aanya Sharma",
  "Rohan Verma",
  "Priya Nair",
  "Arjun Mehta",
  "Sneha Kulkarni",
];

export default function Home() {
  const router = useRouter();

  const startSession = useCallback(() => {
    const sessionId = crypto.randomUUID();
    router.push(`/classroom?session=${sessionId}`);
  }, [router]);

  return (
    <div className="flex min-h-screen flex-col bg-slate-950 text-slate-100">
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-8 px-6 py-20 text-center">
        <span className="rounded-full border border-slate-800 bg-slate-900/60 px-3 py-1 text-xs font-medium tracking-wide text-blue-300">
          Classroom Ally · ISL in real time
        </span>

        <h1 className="text-4xl font-bold leading-tight tracking-tight sm:text-6xl">
          Break the sound barrier.
          <br />
          <span className="text-blue-400">In real time.</span>
        </h1>

        <p className="max-w-xl text-lg leading-relaxed text-slate-400">
          Classroom Ally listens to the teacher&apos;s voice and instantly
          translates it into Indian Sign Language — captions and a signing avatar,
          live on screen — so deaf and hard-of-hearing students never miss a word.
        </p>

        <button
          type="button"
          onClick={startSession}
          className="group flex items-center gap-2 rounded-full bg-blue-500 px-6 py-3 text-base font-semibold text-white transition-colors hover:bg-blue-600"
        >
          Start Classroom Session
          <ArrowRight
            size={18}
            className="transition-transform group-hover:translate-x-0.5"
          />
        </button>

        <a
          href={GITHUB_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 text-sm text-slate-400 transition-colors hover:text-slate-200"
        >
          <Github size={16} />
          View on GitHub
        </a>

        {/* Demo video embed placeholder — swap the inner div for an <iframe>
            (YouTube/Vimeo) or <video> once the demo reel is recorded. */}
        <div className="w-full max-w-2xl">
          <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-slate-700 bg-slate-900/40">
            <span className="flex h-14 w-14 items-center justify-center rounded-full bg-blue-500/15 text-blue-300">
              <Play size={24} className="translate-x-0.5" />
            </span>
            <p className="text-sm font-medium text-slate-300">Demo video</p>
            <p className="text-xs text-slate-500">Coming soon</p>
          </div>
        </div>
      </main>

      <footer className="border-t border-slate-800 bg-slate-900/40">
        <div className="mx-auto w-full max-w-3xl px-6 py-6 text-center text-xs text-slate-500">
          <p className="text-slate-400">{TEAM.join(" · ")}</p>
          <p className="mt-1">
            Dayananda Sagar Academy of Technology and Management (DSATM)
          </p>
        </div>
      </footer>
    </div>
  );
}
