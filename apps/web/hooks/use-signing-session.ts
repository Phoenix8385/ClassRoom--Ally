"use client"

import { useCallback, useEffect, useRef, useState } from "react"

export type SignLanguage = "ISL" | "ASL"
export type SignSpeed = "Slow" | "Normal" | "Fast"

/** A short sample sentence broken into words + their gloss tokens. */
const SAMPLE_STREAM: { word: string; gloss: string[] }[] = [
  { word: "Good", gloss: ["GOOD"] },
  { word: "morning", gloss: ["MORNING"] },
  { word: "class", gloss: ["CLASS", "ALL"] },
  { word: "today", gloss: ["NOW", "DAY"] },
  { word: "we", gloss: ["WE"] },
  { word: "will", gloss: ["FUTURE"] },
  { word: "learn", gloss: ["LEARN"] },
  { word: "about", gloss: ["ABOUT"] },
  { word: "photosynthesis", gloss: ["PLANT", "MAKE", "FOOD", "SUN"] },
  { word: "in", gloss: ["IN"] },
  { word: "plants", gloss: ["PLANT", "MANY"] },
]

const SPEED_MS: Record<SignSpeed, number> = {
  Slow: 1600,
  Normal: 1000,
  Fast: 600,
}

export function useSigningSession() {
  const [connected, setConnected] = useState(true)
  const [speed, setSpeed] = useState<SignSpeed>("Normal")
  const [language, setLanguage] = useState<SignLanguage>("ISL")
  const [captionsOn, setCaptionsOn] = useState(true)
  const [latencyMs, setLatencyMs] = useState(120)
  const [activeIndex, setActiveIndex] = useState(0)
  const [micLevels, setMicLevels] = useState<number[]>([0.2, 0.4, 0.7, 0.3, 0.5])

  const indexRef = useRef(0)

  // Advance the "currently signing" word.
  useEffect(() => {
    if (!connected) return
    const id = window.setInterval(() => {
      indexRef.current = (indexRef.current + 1) % SAMPLE_STREAM.length
      setActiveIndex(indexRef.current)
    }, SPEED_MS[speed])
    return () => window.clearInterval(id)
  }, [connected, speed])

  // Animate mic level bars + jitter latency.
  useEffect(() => {
    if (!connected) {
      setMicLevels([0, 0, 0, 0, 0])
      return
    }
    const id = window.setInterval(() => {
      setMicLevels(Array.from({ length: 5 }, () => 0.15 + Math.random() * 0.85))
      setLatencyMs(90 + Math.round(Math.random() * 90))
    }, 200)
    return () => window.clearInterval(id)
  }, [connected])

  const toggleConnection = useCallback(() => setConnected((c) => !c), [])

  const current = SAMPLE_STREAM[activeIndex]
  const transcript = SAMPLE_STREAM.map((s) => s.word)

  return {
    connected,
    toggleConnection,
    speed,
    setSpeed,
    language,
    setLanguage,
    captionsOn,
    setCaptionsOn,
    latencyMs,
    micLevels,
    activeIndex,
    transcript,
    currentWord: current.word,
    currentGloss: current.gloss,
  }
}

export type SigningSession = ReturnType<typeof useSigningSession>
