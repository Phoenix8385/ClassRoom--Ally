"use client"

import { useState } from "react"
import { useSigningSession } from "@/hooks/use-signing-session"
import { TopBar } from "@/components/top-bar"
import { AvatarPanel } from "@/components/avatar-panel"
import { ControlsPanel } from "@/components/controls-panel"
import { CaptionBar } from "@/components/caption-bar"

export function ClassroomLayout() {
  const session = useSigningSession()
  const [panelCollapsed, setPanelCollapsed] = useState(false)

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-[#0a0a0a] text-white">
      <a
        href="#avatar-region"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-emerald-500 focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:text-[#0a0a0a]"
      >
        Skip to sign avatar
      </a>

      <TopBar
        connected={session.connected}
        language={session.language}
        onLanguageChange={session.setLanguage}
        latencyMs={session.latencyMs}
        onOpenSettings={() => setPanelCollapsed((c) => !c)}
      />

      {/* Center region */}
      <main id="avatar-region" className="flex min-h-0 flex-1 gap-3 p-3">
        <div className="min-w-0 flex-[7]">
          <AvatarPanel
            currentWord={session.currentWord}
            language={session.language}
            connected={session.connected}
          />
        </div>
        <ControlsPanel
          micLevels={session.micLevels}
          connected={session.connected}
          onToggleConnection={session.toggleConnection}
          speed={session.speed}
          onSpeedChange={session.setSpeed}
          captionsOn={session.captionsOn}
          onCaptionsChange={session.setCaptionsOn}
          language={session.language}
          onLanguageChange={session.setLanguage}
          collapsed={panelCollapsed}
          onCollapse={() => setPanelCollapsed((c) => !c)}
        />
      </main>

      <CaptionBar
        transcript={session.transcript}
        activeIndex={session.activeIndex}
        currentGloss={session.currentGloss}
        captionsOn={session.captionsOn}
      />
    </div>
  )
}
