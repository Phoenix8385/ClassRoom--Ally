#!/usr/bin/env python3
"""Convert MediaPipe hand landmarks into Mixamo finger-bone Euler rotations.

MediaPipe Hands gives 21 landmark *positions* per hand; a Mixamo-rigged avatar
is driven by *rotations* on named finger bones. This module bridges the two: it
builds an orientation-invariant hand frame from the wrist + knuckles, measures
each phalanx's direction in that frame, and converts the rotation from the
bone's rest direction into local XYZ Euler angles (radians).

As a library:
    from keypoints_to_bones import hand_to_bones
    bones = hand_to_bones(landmarks, side="right")  # {"mixamorigRightHandIndex1": [x,y,z], ...}

As a CLI it walks a directory of keypoint JSONs (the output of
extract_keypoints.py) and writes a lookup table JSON keyed by word:
    python keypoints_to_bones.py --input data/keypoints --output packages/glossary/bone_lookup.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

# ── MediaPipe Hands topology ──────────────────────────────────────────────────
# 21 landmarks: wrist=0, then 4 joints per finger (thumb..pinky).
WRIST = 0
INDEX_MCP = 5
PINKY_MCP = 17

# Mixamo bone -> (start_landmark, end_landmark). Each phalanx bone points from a
# joint to the next one out toward the fingertip.
FINGER_CHAINS: dict[str, list[tuple[str, int, int]]] = {
    "Thumb": [("Thumb1", 1, 2), ("Thumb2", 2, 3), ("Thumb3", 3, 4)],
    "Index": [("Index1", 5, 6), ("Index2", 6, 7), ("Index3", 7, 8)],
    "Middle": [("Middle1", 9, 10), ("Middle2", 10, 11), ("Middle3", 11, 12)],
    "Ring": [("Ring1", 13, 14), ("Ring2", 14, 15), ("Ring3", 15, 16)],
    "Pinky": [("Pinky1", 17, 18), ("Pinky2", 18, 19), ("Pinky3", 19, 20)],
}


def _bone_name(side: str, suffix: str) -> str:
    hand = "Right" if side.lower().startswith("r") else "Left"
    return f"mixamorig{hand}Hand{suffix}"


# ── Geometry helpers (numpy only, no scipy) ───────────────────────────────────


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-8 else v


def _hand_basis(pts: np.ndarray) -> np.ndarray:
    """Build an orthonormal hand frame from wrist + index/pinky knuckles.

    Columns are [x_axis, y_axis, z_axis]:
      y = wrist -> midpoint of the knuckles (the "up the hand" direction)
      x = across the palm (index knuckle -> pinky knuckle, orthogonalized)
      z = palm normal (x cross y)
    Expressing each phalanx direction in this frame makes the result invariant
    to where the hand sits in the image and how it is globally rotated.
    """
    wrist = pts[WRIST]
    knuckle_mid = (pts[INDEX_MCP] + pts[PINKY_MCP]) / 2.0
    y_axis = _normalize(knuckle_mid - wrist)

    across = pts[PINKY_MCP] - pts[INDEX_MCP]
    # Remove the y-component so x is orthogonal to y.
    x_axis = _normalize(across - np.dot(across, y_axis) * y_axis)
    z_axis = _normalize(np.cross(x_axis, y_axis))
    return np.column_stack([x_axis, y_axis, z_axis])


def _quat_from_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Shortest-arc quaternion [x, y, z, w] rotating unit vector a onto b."""
    a, b = _normalize(a), _normalize(b)
    d = float(np.dot(a, b))
    if d >= 1.0 - 1e-8:
        return np.array([0.0, 0.0, 0.0, 1.0])
    if d <= -1.0 + 1e-8:
        # Opposite vectors: rotate 180° about any orthogonal axis.
        axis = np.cross(a, np.array([1.0, 0.0, 0.0]))
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, np.array([0.0, 1.0, 0.0]))
        axis = _normalize(axis)
        return np.array([axis[0], axis[1], axis[2], 0.0])
    axis = np.cross(a, b)
    w = 1.0 + d
    q = np.array([axis[0], axis[1], axis[2], w])
    return q / np.linalg.norm(q)


def _quat_to_euler_xyz(q: np.ndarray) -> list[float]:
    """Quaternion [x, y, z, w] -> intrinsic XYZ Euler angles (radians)."""
    x, y, z, w = q
    # Roll (X)
    sinr = 2.0 * (w * x + y * z)
    cosr = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr, cosr)
    # Pitch (Y), clamped to avoid NaN at the gimbal pole.
    sinp = 2.0 * (w * y - z * x)
    sinp = max(-1.0, min(1.0, sinp))
    pitch = math.asin(sinp)
    # Yaw (Z)
    siny = 2.0 * (w * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny, cosy)
    return [roll, pitch, yaw]


# The rest pose: a Mixamo finger points "up the hand", i.e. along +Y of our
# hand frame. Each bone's rotation is measured relative to this direction.
_REST_DIR = np.array([0.0, 1.0, 0.0])


def hand_to_bones(landmarks: list[list[float]], side: str) -> dict[str, list[float]]:
    """Map 21 MediaPipe hand landmarks to Mixamo finger-bone Euler rotations.

    Args:
        landmarks: 21 [x, y, z] points from MediaPipe Hands.
        side: "left" or "right" (selects Mixamo bone prefix).

    Returns:
        {mixamo_bone_name: [euler_x, euler_y, euler_z]} in radians. Empty dict
        if the hand is missing or malformed.
    """
    if not landmarks or len(landmarks) < 21:
        return {}

    pts = np.asarray(landmarks, dtype=np.float64)[:, :3]
    basis = _hand_basis(pts)
    basis_t = basis.T  # world -> hand-frame

    bones: dict[str, list[float]] = {}
    for chain in FINGER_CHAINS.values():
        for suffix, start, end in chain:
            seg = pts[end] - pts[start]
            if np.linalg.norm(seg) < 1e-7:
                bones[_bone_name(side, suffix)] = [0.0, 0.0, 0.0]
                continue
            # Direction expressed in the hand frame, then rotation from rest.
            local_dir = _normalize(basis_t @ seg)
            quat = _quat_from_to(_REST_DIR, local_dir)
            bones[_bone_name(side, suffix)] = _quat_to_euler_xyz(quat)
    return bones


# ── CLI: build a per-word bone lookup table ───────────────────────────────────


def build_lookup(keypoints_dir: Path) -> dict:
    """Convert every keypoint JSON in a directory into a bone-rotation track."""
    table: dict[str, dict] = {}
    files = sorted(keypoints_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no keypoint JSONs in {keypoints_dir}")

    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        word = data.get("word", path.stem)
        frames_out = []
        for frame in data.get("frames", []):
            frames_out.append(
                {
                    "left_hand": hand_to_bones(frame.get("left_hand", []), "left"),
                    "right_hand": hand_to_bones(frame.get("right_hand", []), "right"),
                }
            )
        table[word] = {
            "fps": data.get("fps", 0.0),
            "total_frames": len(frames_out),
            "frames": frames_out,
        }
        print(f"  ✓ {word}: {len(frames_out)} frames")
    return table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/keypoints"),
        help="Directory of keypoint JSONs (from extract_keypoints.py)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("packages/glossary/bone_lookup.json"),
        help="Path to write the bone lookup table JSON",
    )
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"error: input directory not found: {args.input}", file=sys.stderr)
        return 1

    table = build_lookup(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(table), encoding="utf-8")
    print(f"\nWrote {len(table)} words -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
