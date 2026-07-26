"use client";

import * as THREE from "three";
import {
  Component,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";

import { useClassroomStore } from "@/store/classroom";
import type { SignAction } from "@/lib/ws-client";

// ─────────────────────────────────────────────────────────────────────────────
// Tunables
// ─────────────────────────────────────────────────────────────────────────────

const AVATAR_URL = "/avatars/signer.glb";

const SLERP_FACTOR = 0.3; // per-frame easing toward each bone's target rotation
const FINGERSPELL_INTERVAL_MS = 400; // one letter every 400ms
const TPOSE_GAP_MS = 100; // neutral pause inserted between consecutive signs
const IDLE_HZ = 0.4; // breathing frequency
const IDLE_SCALE_MIN = 1.0; // chest scale.y at trough
const IDLE_SCALE_MAX = 1.01; // chest scale.y at peak

// Model is normalized so its full height maps to this many world units. With the
// camera at (0, 1.4, 2.5)/fov 45 and the group dropped to y=-1, that frames the
// upper body to roughly 60% of canvas height.
const TARGET_FULL_HEIGHT = 2.6;

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

// ─────────────────────────────────────────────────────────────────────────────
// Skeleton mapping
//
// MediaPipe Hands emits 21 landmarks per hand. Each (parent → child) landmark
// segment drives one Mixamo finger bone: we align the bone's rest axis to the
// segment's world direction. The rest axis is a best-effort assumption for the
// signer.glb rig — recalibrate REST_AXIS if a different rig is swapped in.
// ─────────────────────────────────────────────────────────────────────────────

const REST_AXIS = new THREE.Vector3(0, 1, 0);

// [parentLandmark, childLandmark, mixamoBone]
const HAND_SEGMENTS: ReadonlyArray<readonly [number, number, string]> = [
  [0, 9, "mixamorigRightHand"], // wrist → middle-base ≈ palm orientation
  [1, 2, "mixamorigRightHandThumb1"],
  [2, 3, "mixamorigRightHandThumb2"],
  [3, 4, "mixamorigRightHandThumb3"],
  [5, 6, "mixamorigRightHandIndex1"],
  [6, 7, "mixamorigRightHandIndex2"],
  [7, 8, "mixamorigRightHandIndex3"],
  [9, 10, "mixamorigRightHandMiddle1"],
  [10, 11, "mixamorigRightHandMiddle2"],
  [11, 12, "mixamorigRightHandMiddle3"],
  [13, 14, "mixamorigRightHandRing1"],
  [14, 15, "mixamorigRightHandRing2"],
  [15, 16, "mixamorigRightHandRing3"],
  [17, 18, "mixamorigRightHandPinky1"],
  [18, 19, "mixamorigRightHandPinky2"],
  [19, 20, "mixamorigRightHandPinky3"],
];

// Arm bones the keypoint/fingerspell controllers may also touch.
const ARM_BONES = [
  "mixamorigRightArm",
  "mixamorigRightForeArm",
  "mixamorigLeftArm",
  "mixamorigLeftForeArm",
] as const;

// Every bone the controller is allowed to drive. Anything absent keeps its rest
// pose so the idle breathing (a scale on a separate group) stays undisturbed.
const DRIVEN_BONES: readonly string[] = [
  ...HAND_SEGMENTS.map((s) => s[2]),
  ...ARM_BONES,
];

// Pre-baked right-hand Euler poses (radians) for A–Z fingerspelling. Illustrative
// but distinct per letter, so the avatar reads as spelling rather than holding one
// pose. Index i corresponds to ALPHABET[i].
const FINGERSPELL_EULERS: ReadonlyArray<readonly [number, number, number]> = [
  [0.1, 0.0, -0.2], // A
  [-0.3, 0.1, 0.0], // B
  [0.2, -0.4, 0.1], // C
  [-0.4, 0.0, 0.3], // D
  [0.3, 0.2, -0.1], // E
  [-0.1, -0.3, 0.2], // F
  [0.0, 0.4, -0.3], // G
  [0.4, -0.1, 0.0], // H
  [-0.2, 0.3, 0.4], // I
  [0.1, -0.2, -0.4], // J
  [-0.3, 0.4, 0.1], // K
  [0.2, 0.0, 0.5], // L
  [-0.4, -0.2, -0.1], // M
  [0.3, 0.1, 0.2], // N
  [0.0, -0.4, 0.3], // O
  [-0.1, 0.2, -0.4], // P
  [0.4, 0.3, 0.0], // Q
  [-0.2, -0.1, 0.4], // R
  [0.1, 0.4, -0.2], // S
  [-0.3, 0.0, 0.3], // T
  [0.2, -0.3, -0.1], // U
  [-0.4, 0.1, 0.2], // V
  [0.3, 0.2, 0.4], // W
  [-0.1, -0.4, 0.0], // X
  [0.0, 0.3, -0.3], // Y
  [0.4, -0.2, 0.1], // Z
];

// SignAction as delivered may optionally carry a raw MediaPipe keypoint frame.
// The base type (ws-client) doesn't guarantee it, so we read it defensively.
type Keypoint = readonly [number, number, number];
interface KeypointCarrier {
  keypoints?: ReadonlyArray<Keypoint> | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Pose math helpers
// ─────────────────────────────────────────────────────────────────────────────

const _euler = new THREE.Euler();
const _dir = new THREE.Vector3();
const _pa = new THREE.Vector3();
const _pb = new THREE.Vector3();

function eulerToQuat(e: readonly [number, number, number]): THREE.Quaternion {
  return new THREE.Quaternion().setFromEuler(_euler.set(e[0], e[1], e[2], "XYZ"));
}

/** Deterministic 0..1 hash so a given token always yields the same synth pose. */
function hashToken(token: string): number {
  let h = 2166136261;
  for (let i = 0; i < token.length; i++) {
    h ^= token.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 0xffffffff;
}

/**
 * Map a MediaPipe hand-landmark frame to per-bone target quaternions by aligning
 * each bone's rest axis to its (parent → child) segment direction.
 */
function keypointsToBoneQuats(
  keypoints: ReadonlyArray<Keypoint>,
): Record<string, THREE.Quaternion> {
  const out: Record<string, THREE.Quaternion> = {};
  for (const [parent, child, bone] of HAND_SEGMENTS) {
    const a = keypoints[parent];
    const b = keypoints[child];
    if (!a || !b) continue;
    _pa.set(a[0], a[1], a[2]);
    _pb.set(b[0], b[1], b[2]);
    _dir.subVectors(_pb, _pa);
    if (_dir.lengthSq() < 1e-8) continue;
    _dir.normalize();
    out[bone] = new THREE.Quaternion().setFromUnitVectors(REST_AXIS, _dir);
  }
  return out;
}

/**
 * Fallback held-arm pose synthesized from a token when no raw keypoints are
 * attached. Deterministic, so repeated renders of the same sign are stable.
 */
function synthKeypointTargets(token: string): Record<string, THREE.Quaternion> {
  const seed = hashToken(token);
  const a = (seed - 0.5) * 1.2; // ±0.6 rad spread
  return {
    mixamorigRightArm: eulerToQuat([a, 0, -0.3 - a * 0.4]),
    mixamorigRightForeArm: eulerToQuat([0, 0, -0.6 + a * 0.5]),
    mixamorigLeftArm: eulerToQuat([-a, 0, 0.3 + a * 0.4]),
    mixamorigLeftForeArm: eulerToQuat([0, 0, 0.6 - a * 0.5]),
    mixamorigRightHand: eulerToQuat([a * 0.5, 0, 0]),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Bone controller
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Drives an avatar skeleton for a single SignAction:
 *  - "keypoints":   slerp driven bones toward keypoint-derived (or token-synth) targets
 *  - "fingerspell": cycle letter poses every 400ms, slerped in
 *  - "clip":        no-op (the video overlay handles the visual)
 * With `action === null` every driven bone eases back to its captured rest pose,
 * which is what produces the brief T-pose separation between signs.
 */
function useBoneController(
  model: THREE.Object3D | null,
  action: SignAction | null,
): React.RefObject<THREE.SkinnedMesh | null> {
  const skinnedRef = useRef<THREE.SkinnedMesh | null>(null);
  const bonesRef = useRef<Record<string, THREE.Bone>>({});
  const restRef = useRef<Record<string, THREE.Quaternion>>({});
  const targetsRef = useRef<Record<string, THREE.Quaternion>>({});

  // Resolve bones + the SkinnedMesh, and capture rest rotations, once the model
  // is available. Re-runs only when the model instance changes.
  useEffect(() => {
    if (!model) return;
    const bones: Record<string, THREE.Bone> = {};
    const rest: Record<string, THREE.Quaternion> = {};
    model.traverse((obj) => {
      if ((obj as THREE.SkinnedMesh).isSkinnedMesh && !skinnedRef.current) {
        skinnedRef.current = obj as THREE.SkinnedMesh;
      }
      if ((obj as THREE.Bone).isBone) {
        const bone = obj as THREE.Bone;
        bones[bone.name] = bone;
        rest[bone.name] = bone.quaternion.clone();
      }
    });
    bonesRef.current = bones;
    restRef.current = rest;
  }, [model]);

  // Compute (or begin animating) targets whenever the active action changes.
  useEffect(() => {
    targetsRef.current = {};
    if (!action || action.type === "clip") return;

    if (action.type === "keypoints") {
      const kp = (action as SignAction & KeypointCarrier).keypoints;
      targetsRef.current =
        kp && kp.length > 0
          ? keypointsToBoneQuats(kp)
          : synthKeypointTargets(action.token);
      return;
    }

    // fingerspell — step through letters on a fixed interval.
    const letters =
      action.letters && action.letters.length > 0
        ? action.letters
        : action.token.split("");
    let idx = 0;

    const applyLetter = (letter: string) => {
      const li = ALPHABET.indexOf(letter.toUpperCase());
      const euler = FINGERSPELL_EULERS[li >= 0 ? li : 0];
      targetsRef.current = {
        mixamorigRightHand: eulerToQuat(euler),
        mixamorigRightArm: eulerToQuat([euler[0] * 0.4, 0, -0.4]),
        mixamorigRightForeArm: eulerToQuat([0, 0, -0.8]),
      };
    };

    applyLetter(letters[0] ?? "A");
    const id = window.setInterval(() => {
      idx = (idx + 1) % letters.length;
      applyLetter(letters[idx]);
    }, FINGERSPELL_INTERVAL_MS);

    return () => window.clearInterval(id);
  }, [action]);

  // Per-frame slerp: driven bones with a target ease toward it; the rest ease
  // back to their captured rest rotation (the T-pose return).
  useFrame(() => {
    const bones = bonesRef.current;
    const targets = targetsRef.current;
    const rest = restRef.current;
    for (const name of DRIVEN_BONES) {
      const bone = bones[name];
      if (!bone) continue;
      const goal = targets[name] ?? rest[name];
      if (goal) bone.quaternion.slerp(goal, SLERP_FACTOR);
    }
  });

  return skinnedRef;
}

// ─────────────────────────────────────────────────────────────────────────────
// Avatar model
// ─────────────────────────────────────────────────────────────────────────────

interface AvatarModelProps {
  action: SignAction | null;
  onLoaded?: () => void;
}

function AvatarModel({ action, onLoaded }: AvatarModelProps) {
  const idleRef = useRef<THREE.Group>(null);
  const { scene } = useGLTF(AVATAR_URL);

  // Clone so repeated mounts / HMR don't mutate the shared drei cache.
  const model = useMemo(() => {
    const clone = scene.clone(true);
    clone.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.isMesh) {
        mesh.castShadow = true;
        mesh.receiveShadow = true;
      }
    });
    return clone;
  }, [scene]);

  // Normalize height so the upper body fills ~60% of the framed canvas.
  const normScale = useMemo(() => {
    const size = new THREE.Vector3();
    new THREE.Box3().setFromObject(model).getSize(size);
    return size.y > 0 ? TARGET_FULL_HEIGHT / size.y : 1;
  }, [model]);

  const skinnedRef = useBoneController(model, action);
  void skinnedRef; // exposed for future direct SkinnedMesh manipulation

  useEffect(() => {
    onLoaded?.();
  }, [onLoaded]);

  // Idle breathing: chest scale.y oscillates between 1.0 and 1.01 at 0.4Hz on a
  // dedicated inner group, so it composes with (and never fights) bone poses.
  useFrame(({ clock }) => {
    const g = idleRef.current;
    if (!g) return;
    const t = clock.elapsedTime * Math.PI * 2 * IDLE_HZ;
    const s = IDLE_SCALE_MIN + (IDLE_SCALE_MAX - IDLE_SCALE_MIN) * (0.5 + 0.5 * Math.sin(t));
    g.scale.y = s;
  });

  return (
    <group position={[0, -1, 0]} scale={normScale}>
      <group ref={idleRef}>
        <primitive object={model} />
      </group>
    </group>
  );
}

useGLTF.preload(AVATAR_URL);

// ─────────────────────────────────────────────────────────────────────────────
// Error boundary — falls back to gloss text if the GLB never loads
// ─────────────────────────────────────────────────────────────────────────────

interface GlbErrorBoundaryProps {
  gloss: string;
  children: ReactNode;
}

class GlbErrorBoundary extends Component<
  GlbErrorBoundaryProps,
  { hasError: boolean }
> {
  constructor(props: GlbErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    // eslint-disable-next-line no-console
    console.error("[SignAvatar] GLB failed to load:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-full w-full items-center justify-center rounded-xl bg-slate-900/80 p-6 text-center">
          <div>
            <p className="mb-1 text-xs uppercase tracking-wide text-slate-400">
              Avatar unavailable — showing gloss
            </p>
            <p className="text-2xl font-semibold text-white">
              {this.props.gloss || "…"}
            </p>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Loading skeleton (shown via Suspense while the GLB streams in)
// ─────────────────────────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="absolute inset-0 flex items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="h-24 w-24 animate-pulse rounded-full bg-slate-700/60" />
        <div className="h-32 w-20 animate-pulse rounded-2xl bg-slate-700/40" />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Clip overlay — HTML5 video positioned above the canvas
// ─────────────────────────────────────────────────────────────────────────────

interface ClipOverlayProps {
  action: SignAction;
  onEnded: () => void;
}

function ClipOverlay({ action, onEnded }: ClipOverlayProps) {
  const src = action.clip_path ?? `/signs/${action.token}.mp4`;
  return (
    <video
      // key forces a fresh element (and autoplay restart) per clip
      key={src}
      className="pointer-events-none absolute inset-0 z-10 h-full w-full rounded-xl object-contain"
      src={src}
      autoPlay
      muted
      playsInline
      onEnded={onEnded}
      onError={onEnded} // a missing clip shouldn't stall the queue
    />
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────

export default function SignAvatar() {
  const current = useClassroomStore((s) => s.signs.current);
  const queueLength = useClassroomStore((s) => s.signs.queue.length);
  const shiftSign = useClassroomStore((s) => s.shiftSign);
  const setCurrentSign = useClassroomStore((s) => s.setCurrentSign);
  const setIsPlaying = useClassroomStore((s) => s.setIsPlaying);

  const [loaded, setLoaded] = useState(false);

  const isSigning = current !== null;

  // Playback scheduler. Advances the queue and inserts the 100ms T-pose gap
  // between signs. Clip signs advance from the video's onEnded instead of a timer.
  useEffect(() => {
    setIsPlaying(isSigning);

    if (current === null) {
      // Idle: if more signs are queued, hold the T-pose gap, then advance.
      if (queueLength > 0) {
        const t = window.setTimeout(() => shiftSign(), TPOSE_GAP_MS);
        return () => window.clearTimeout(t);
      }
      return;
    }

    if (current.type === "clip") return; // ClipOverlay.onEnded drives advance

    // keypoints / fingerspell: hold for the action's duration, then clear so the
    // idle branch picks up the next sign after the gap.
    const dur = current.duration_ms > 0 ? current.duration_ms : 1500;
    const t = window.setTimeout(() => setCurrentSign(null), dur);
    return () => window.clearTimeout(t);
  }, [current, queueLength, isSigning, shiftSign, setCurrentSign, setIsPlaying]);

  const handleClipEnded = () => setCurrentSign(null);

  // Only the skeleton-driven actions reach the bone controller.
  const boneAction = current && current.type !== "clip" ? current : null;
  const gloss = current?.token ?? "";

  return (
    <div
      className="relative aspect-[3/4] w-full overflow-hidden rounded-xl bg-slate-950"
      style={{
        boxShadow: isSigning
          ? "0 0 0 2px rgba(59,130,246,0.7), 0 0 28px 6px rgba(59,130,246,0.55)"
          : "0 0 0 1px rgba(30,41,59,0.8)",
        transition: "box-shadow 200ms ease",
      }}
    >
      <GlbErrorBoundary gloss={gloss}>
        {!loaded && <LoadingSkeleton />}

        <Canvas
          shadows
          camera={{ position: [0, 1.4, 2.5], fov: 45 }}
          gl={{ alpha: true }}
          style={{ background: "transparent" }}
        >
          <ambientLight intensity={1.2} />
          <directionalLight position={[2, 4, 3]} intensity={1.5} castShadow />
          <Suspense fallback={null}>
            <AvatarModel action={boneAction} onLoaded={() => setLoaded(true)} />
          </Suspense>
        </Canvas>

        {current?.type === "clip" && (
          <ClipOverlay action={current} onEnded={handleClipEnded} />
        )}
      </GlbErrorBoundary>
    </div>
  );
}
