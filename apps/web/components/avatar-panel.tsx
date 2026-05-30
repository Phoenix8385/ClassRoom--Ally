"use client"

import { useEffect, useRef } from "react"
import { Hand } from "lucide-react"
import type { SignLanguage } from "@/hooks/use-signing-session"

interface AvatarPanelProps {
  currentWord: string
  language: SignLanguage
  connected: boolean
}

/**
 * Placeholder for a Three.js sign-avatar canvas. A lightweight 2D canvas
 * animation stands in for the 3D avatar so the layout reads as "live".
 */
export function AvatarPanel({ currentWord, language, connected }: AvatarPanelProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    let raf = 0
    const dpr = window.devicePixelRatio || 1

    const resize = () => {
      const { width, height } = canvas.getBoundingClientRect()
      canvas.width = width * dpr
      canvas.height = height * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    window.addEventListener("resize", resize)

    let t = 0
    const draw = () => {
      const { width, height } = canvas.getBoundingClientRect()
      ctx.clearRect(0, 0, width, height)
      const cx = width / 2
      const cy = height / 2
      t += connected ? 0.04 : 0.008

      // Glow halo
      const pulse = 60 + Math.sin(t) * 10
      const grad = ctx.createRadialGradient(cx, cy, 10, cx, cy, 180 + pulse)
      grad.addColorStop(0, "rgba(16, 185, 129, 0.18)")
      grad.addColorStop(1, "rgba(16, 185, 129, 0)")
      ctx.fillStyle = grad
      ctx.fillRect(0, 0, width, height)

      // Simple articulated "avatar": head + two waving hands
      ctx.strokeStyle = "rgba(120, 240, 200, 0.9)"
      ctx.lineWidth = 6
      ctx.lineCap = "round"

      // head
      ctx.beginPath()
      ctx.arc(cx, cy - 90, 34, 0, Math.PI * 2)
      ctx.stroke()

      // torso
      ctx.beginPath()
      ctx.moveTo(cx, cy - 56)
      ctx.lineTo(cx, cy + 40)
      ctx.stroke()

      // arms with motion
      const swing = Math.sin(t * 1.5) * 0.5
      const swing2 = Math.cos(t * 1.5) * 0.5
      // left arm
      ctx.beginPath()
      ctx.moveTo(cx, cy - 30)
      const lex = cx - 70
      const ley = cy - 30 + Math.sin(t) * 40
      ctx.lineTo(cx - 40, cy - 10 + swing * 30)
      ctx.lineTo(lex, ley)
      ctx.stroke()
      // right arm
      ctx.beginPath()
      ctx.moveTo(cx, cy - 30)
      const rex = cx + 70
      const rey = cy - 30 + Math.cos(t) * 40
      ctx.lineTo(cx + 40, cy - 10 + swing2 * 30)
      ctx.lineTo(rex, rey)
      ctx.stroke()

      // hands
      ctx.fillStyle = "rgba(160, 255, 220, 0.95)"
      ctx.beginPath()
      ctx.arc(lex, ley, 10, 0, Math.PI * 2)
      ctx.arc(rex, rey, 10, 0, Math.PI * 2)
      ctx.fill()

      raf = window.requestAnimationFrame(draw)
    }
    draw()

    return () => {
      window.cancelAnimationFrame(raf)
      window.removeEventListener("resize", resize)
    }
  }, [connected])

  return (
    <section
      aria-label="Sign avatar"
      className="relative flex h-full min-w-0 flex-col overflow-hidden rounded-2xl border border-[#1f1f1f] bg-[#0d0d0d]"
    >
      {/* Label */}
      <div className="absolute left-4 top-4 z-10 flex items-center gap-2 rounded-full border border-[#222] bg-black/50 px-3 py-1.5 backdrop-blur-sm">
        <Hand className="h-4 w-4 text-emerald-400" aria-hidden="true" />
        <span className="text-xs font-medium text-[#cccccc]">Sign Avatar</span>
        <span className="text-[10px] font-semibold text-[#666]">· {language}</span>
      </div>

      <canvas
        ref={canvasRef}
        className="h-full w-full"
        role="img"
        aria-label={`Animated sign avatar currently signing the word ${currentWord}`}
      />

      {/* Current word overlay */}
      <div className="pointer-events-none absolute bottom-4 left-1/2 -translate-x-1/2 rounded-lg border border-[#222] bg-black/60 px-4 py-2 backdrop-blur-sm">
        <span className="text-sm text-[#888]">Signing: </span>
        <span className="text-sm font-semibold text-[#FFD700]">{currentWord}</span>
      </div>
    </section>
  )
}
