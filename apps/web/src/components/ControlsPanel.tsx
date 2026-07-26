"use client";

import { Mic, MicOff } from "lucide-react";

import type {
  AvatarMode,
  Language,
  MicState,
  SettingsState,
} from "@/store/classroom";

interface ControlsPanelProps {
  mic: MicState;
  settings: SettingsState;
  onToggleCapture: () => void;
  onLanguageChange: (language: Language) => void;
  onSpeedChange: (speed: number) => void;
  onToggleCaptions: (enabled: boolean) => void;
  onAvatarModeChange: (mode: AvatarMode) => void;
}

export default function ControlsPanel({
  mic,
  settings,
  onToggleCapture,
  onLanguageChange,
  onSpeedChange,
  onToggleCaptions,
  onAvatarModeChange,
}: ControlsPanelProps) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <button
        type="button"
        onClick={onToggleCapture}
        className={`flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors ${
          mic.isActive
            ? "bg-red-500 text-white hover:bg-red-600"
            : "bg-emerald-500 text-white hover:bg-emerald-600"
        }`}
      >
        {mic.isActive ? <MicOff size={16} /> : <Mic size={16} />}
        {mic.isActive ? "Stop" : "Start"}
      </button>

      {/* Mic level meter */}
      <div
        className="h-2 w-24 overflow-hidden rounded-full bg-slate-800"
        title="Microphone level"
      >
        <div
          className="h-full bg-emerald-400 transition-[width] duration-75"
          style={{ width: `${Math.min(100, Math.round(mic.level * 100))}%` }}
        />
      </div>

      <div className="ml-auto flex flex-wrap items-center gap-4 text-xs">
        {/* Language */}
        <div className="flex overflow-hidden rounded-full border border-slate-700">
          {(["ISL", "ASL"] as const).map((lang) => (
            <button
              key={lang}
              type="button"
              onClick={() => onLanguageChange(lang)}
              className={`px-3 py-1.5 ${
                settings.language === lang
                  ? "bg-blue-500 text-white"
                  : "text-slate-300 hover:bg-slate-800"
              }`}
            >
              {lang}
            </button>
          ))}
        </div>

        {/* Avatar mode */}
        <div className="flex overflow-hidden rounded-full border border-slate-700">
          {(["clips", "avatar"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => onAvatarModeChange(mode)}
              className={`px-3 py-1.5 capitalize ${
                settings.avatarMode === mode
                  ? "bg-blue-500 text-white"
                  : "text-slate-300 hover:bg-slate-800"
              }`}
            >
              {mode}
            </button>
          ))}
        </div>

        {/* Speed */}
        <label className="flex items-center gap-2 text-slate-400">
          Speed
          <input
            type="range"
            min={0.5}
            max={1.5}
            step={0.1}
            value={settings.speed}
            onChange={(e) => onSpeedChange(Number(e.target.value))}
            className="w-20 accent-blue-500"
          />
          <span className="w-8 tabular-nums text-slate-300">
            {settings.speed.toFixed(1)}x
          </span>
        </label>

        {/* Captions */}
        <label className="flex items-center gap-2 text-slate-400">
          <input
            type="checkbox"
            checked={settings.captionsEnabled}
            onChange={(e) => onToggleCaptions(e.target.checked)}
            className="accent-blue-500"
          />
          Captions
        </label>
      </div>
    </div>
  );
}
