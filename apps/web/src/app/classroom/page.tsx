"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import AvatarPanel from "@/components/AvatarPanel";
import CaptionBar from "@/components/CaptionBar";
import ClassroomLayout from "@/components/ClassroomLayout";
import ControlsPanel from "@/components/ControlsPanel";
import FeedbackRow from "@/components/FeedbackRow";
import SetupModal from "@/components/SetupModal";
import TopBar from "@/components/TopBar";
import { startCapture, stopCapture } from "@/lib/audio-capture";
import { useClassroomWS } from "@/lib/ws-client";
import { useClassroomStore } from "@/store/classroom";

function ClassroomSession() {
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("session") ?? "";

  const { connect, disconnect, status, getClient } = useClassroomWS(sessionId);

  // ── Store reads (passed down as props) ──────────────────────────────────────
  const connection = useClassroomStore((s) => s.connection);
  const transcript = useClassroomStore((s) => s.transcript);
  const gloss = useClassroomStore((s) => s.gloss);
  const signs = useClassroomStore((s) => s.signs);
  const settings = useClassroomStore((s) => s.settings);
  const mic = useClassroomStore((s) => s.mic);
  const feedback = useClassroomStore((s) => s.feedback);

  // ── Store actions ───────────────────────────────────────────────────────────
  const setLanguage = useClassroomStore((s) => s.setLanguage);
  const setSpeed = useClassroomStore((s) => s.setSpeed);
  const setCaptionsEnabled = useClassroomStore((s) => s.setCaptionsEnabled);
  const setAvatarMode = useClassroomStore((s) => s.setAvatarMode);
  const clearFeedback = useClassroomStore((s) => s.clearFeedback);

  const [requesting, setRequesting] = useState(false);
  const startingRef = useRef(false);

  // Connect the socket + open the mic pipeline. Safe to call repeatedly (the
  // SetupModal retry button reuses it); guarded against overlapping starts.
  const startSession = useCallback(async () => {
    if (startingRef.current || mic.isActive) return;
    const client = getClient();
    if (!client) return;

    startingRef.current = true;
    setRequesting(true);
    try {
      connect();
      await startCapture(client); // prompts for mic; flags denial in the store
    } catch {
      // Permission denial is reflected via store.mic.permissionDenied; the
      // SetupModal stays open so the teacher can retry.
    } finally {
      setRequesting(false);
      startingRef.current = false;
    }
  }, [connect, getClient, mic.isActive]);

  // On mount: request mic + connect + start audio. On unmount: tear everything
  // down. The WS client itself is also disconnected by useClassroomWS cleanup.
  useEffect(() => {
    if (!sessionId) return;
    void startSession();
    return () => {
      void stopCapture();
      disconnect();
    };
    // startSession is stable enough for mount; sessionId drives re-runs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const handleToggleCapture = useCallback(() => {
    if (mic.isActive) {
      void stopCapture();
    } else {
      void startSession();
    }
  }, [mic.isActive, startSession]);

  const handleRate = useCallback(
    (segmentId: string, rating: "up" | "down") => {
      // TODO: POST to the feedback API once the endpoint lands.
      console.info("[feedback]", segmentId, rating);
      clearFeedback();
    },
    [clearFeedback],
  );

  if (!sessionId) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-300">
        <p className="text-sm">
          Missing session. Open a classroom from the home page.
        </p>
      </div>
    );
  }

  // The socket gave up: either the server refused this session id outright
  // (close 4004) or the backoff schedule ran out. Both leave the page unusable,
  // so say so rather than sitting on a spinner that will never resolve.
  if (status === "error") {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 bg-slate-950 px-6 text-center text-slate-300">
        <p className="text-sm">
          This session is not available. The link may be stale, or the server may
          be unreachable.
        </p>
        <Link
          href="/"
          className="text-sm font-medium text-blue-400 transition-colors hover:text-blue-300"
        >
          Start a new session
        </Link>
      </div>
    );
  }

  const micGranted = mic.isActive;

  return (
    <>
      <SetupModal
        open={!micGranted}
        permissionDenied={mic.permissionDenied}
        requesting={requesting}
        onRequest={() => void startSession()}
      />

      <ClassroomLayout
        topBar={
          <TopBar
            status={status}
            sessionId={connection.sessionId ?? sessionId}
            latencyMs={connection.latencyMs}
            language={settings.language}
          />
        }
        avatar={<AvatarPanel signs={signs} avatarMode={settings.avatarMode} />}
        caption={
          <CaptionBar
            transcript={transcript}
            gloss={gloss}
            captionsEnabled={settings.captionsEnabled}
          />
        }
        feedback={
          <FeedbackRow
            feedback={feedback}
            currentSegmentId={transcript.currentSegmentId}
            onRate={handleRate}
            onDismiss={clearFeedback}
          />
        }
        controls={
          <ControlsPanel
            mic={mic}
            settings={settings}
            onToggleCapture={handleToggleCapture}
            onLanguageChange={setLanguage}
            onSpeedChange={setSpeed}
            onToggleCaptions={setCaptionsEnabled}
            onAvatarModeChange={setAvatarMode}
          />
        }
      />
    </>
  );
}

export default function ClassroomPage() {
  // useSearchParams must sit under a Suspense boundary (Next App Router).
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-400">
          Loading classroom…
        </div>
      }
    >
      <ClassroomSession />
    </Suspense>
  );
}
