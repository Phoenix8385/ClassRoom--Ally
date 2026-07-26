#!/usr/bin/env python3
"""Extract MediaPipe Holistic keypoints from ISL sign clips.

Runs MediaPipe Holistic over every frame of each MP4 in an input directory and
writes one JSON file per word containing pose (33), left/right hand (21 each) and
face (468) landmark tracks — 543 landmarks per frame. Pose coordinates are
hip-centered and divided by shoulder width, making the tracks invariant to the
signer's position and apparent size. Frames where neither hand is detected are
dropped. Absent streams are written as null.

Usage:
    python extract_keypoints.py
    python extract_keypoints.py --word hello --word thank --visualize
    python extract_keypoints.py --input data/isl_clips --output data/keypoints
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import mediapipe as mp
from tqdm import tqdm

mp_holistic = mp.solutions.holistic
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles

# Pose landmark indices (MediaPipe Pose topology).
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_HIP = 23
RIGHT_HIP = 24

# Landmark counts per stream (used only for output documentation / sanity).
POSE_N = 33
HAND_N = 21
FACE_N = 468  # holistic default (refine_face_landmarks=False)

DEFAULT_INPUT = Path("data/isl_clips")
DEFAULT_OUTPUT = Path("data/keypoints")


# ── Stats accumulator ─────────────────────────────────────────────────────────


@dataclass
class RunStats:
    words: list[str] = field(default_factory=list)
    kept_frames_per_word: dict[str, int] = field(default_factory=dict)
    processed_frames_total: int = 0
    kept_frames_total: int = 0

    def add_word(self, word: str, processed: int, kept: int) -> None:
        self.words.append(word)
        self.kept_frames_per_word[word] = kept
        self.processed_frames_total += processed
        self.kept_frames_total += kept

    def report(self) -> str:
        n = len(self.words)
        avg = (self.kept_frames_total / n) if n else 0.0
        rate = (
            self.kept_frames_total / self.processed_frames_total
            if self.processed_frames_total
            else 0.0
        )
        lines = [
            "",
            "=" * 48,
            f"  Words processed:   {n}",
            f"  Avg frames/sign:   {avg:.1f}",
            f"  Detection rate:    {rate:.1%} "
            f"({self.kept_frames_total}/{self.processed_frames_total} frames)",
            "=" * 48,
        ]
        return "\n".join(lines)


# ── Landmark extraction ───────────────────────────────────────────────────────


def _hip_midpoint(pose) -> tuple[float, float, float]:
    """Average of the left/right hip landmarks, used as the pose origin."""
    lh, rh = pose[LEFT_HIP], pose[RIGHT_HIP]
    return ((lh.x + rh.x) / 2.0, (lh.y + rh.y) / 2.0, (lh.z + rh.z) / 2.0)


def _shoulder_width(pose) -> float:
    """3-D distance between the shoulders — the pose's scale reference."""
    ls, rs = pose[LEFT_SHOULDER], pose[RIGHT_SHOULDER]
    return math.dist((ls.x, ls.y, ls.z), (rs.x, rs.y, rs.z))


def extract_pose(pose_landmarks) -> Optional[list[list[float]]]:
    """33 pose landmarks as [x, y, z, visibility], hip-centered and scaled.

    Coordinates are translated so the hip midpoint sits at the origin, then
    divided by the shoulder width so they are expressed in shoulder-width units
    (~[-1, 1] for the torso) — making the track invariant to both the signer's
    position in frame and their apparent size. Visibility is passed through.

    Returns None when no pose was detected.
    """
    if pose_landmarks is None:
        return None
    pose = pose_landmarks.landmark
    cx, cy, cz = _hip_midpoint(pose)
    sw = _shoulder_width(pose)
    scale = sw if sw > 1e-6 else 1.0
    return [
        [(lm.x - cx) / scale, (lm.y - cy) / scale, (lm.z - cz) / scale, lm.visibility]
        for lm in pose
    ]


def extract_hand(hand_landmarks) -> Optional[list[list[float]]]:
    """21 hand landmarks as raw [x, y, z]. None when the hand is absent.

    Hands are left in MediaPipe's own normalized image space (not hip/shoulder
    normalized) so keypoints_to_bones.py can rebuild its own hand frame.
    """
    if hand_landmarks is None:
        return None
    return [[lm.x, lm.y, lm.z] for lm in hand_landmarks.landmark]


def extract_face(face_landmarks) -> Optional[list[list[float]]]:
    """468 face landmarks as raw [x, y, z]. None when the face is absent."""
    if face_landmarks is None:
        return None
    return [[lm.x, lm.y, lm.z] for lm in face_landmarks.landmark]


# ── Visualization ─────────────────────────────────────────────────────────────


def draw_overlay(frame_bgr, results) -> None:
    """Draw pose + both hand skeletons onto a BGR frame in place."""
    mp_drawing.draw_landmarks(
        frame_bgr,
        results.pose_landmarks,
        mp_holistic.POSE_CONNECTIONS,
        landmark_drawing_spec=mp_drawing_styles.get_default_pose_landmarks_style(),
    )
    for hand in (results.left_hand_landmarks, results.right_hand_landmarks):
        mp_drawing.draw_landmarks(
            frame_bgr,
            hand,
            mp_holistic.HAND_CONNECTIONS,
            landmark_drawing_spec=mp_drawing_styles.get_default_hand_landmarks_style(),
            connection_drawing_spec=mp_drawing_styles.get_default_hand_connections_style(),
        )


# ── Per-clip processing ───────────────────────────────────────────────────────


def process_clip(
    mp4_path: Path,
    output_dir: Path,
    min_detection_confidence: float,
    visualize: bool,
) -> Optional[tuple[int, int]]:
    """Process one MP4. Returns (processed_frames, kept_frames) or None on error."""
    word = mp4_path.stem.lower()
    cap = cv2.VideoCapture(str(mp4_path))
    if not cap.isOpened():
        tqdm.write(f"  ! could not open {mp4_path.name}, skipping")
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    src_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    writer = None
    if visualize:
        preview_dir = output_dir / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(
            str(preview_dir / f"{word}.mp4"),
            fourcc,
            fps if fps > 0 else 25.0,
            (width, height),
        )

    frames: list[dict] = []
    processed = 0

    with mp_holistic.Holistic(
        min_detection_confidence=min_detection_confidence,
        min_tracking_confidence=0.5,
    ) as holistic:
        bar = tqdm(
            total=src_frames or None,
            desc=f"  {word}",
            leave=False,
            unit="f",
        )
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break
            processed += 1

            # MediaPipe expects RGB.
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = holistic.process(rgb)

            left = extract_hand(results.left_hand_landmarks)
            right = extract_hand(results.right_hand_landmarks)

            # Skip frames where neither hand was detected (likely non-signing).
            if left is not None or right is not None:
                frames.append(
                    {
                        "pose": extract_pose(results.pose_landmarks),
                        "left_hand": left,
                        "right_hand": right,
                        "face": extract_face(results.face_landmarks),
                    }
                )

            if writer is not None:
                draw_overlay(frame_bgr, results)
                writer.write(frame_bgr)

            bar.update(1)
        bar.close()

    cap.release()
    if writer is not None:
        writer.release()

    payload = {
        "word": word,
        "fps": round(fps, 3),
        "total_frames": len(frames),
        "frames": frames,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{word}.json"
    out_path.write_text(json.dumps(payload), encoding="utf-8")
    tqdm.write(f"  ✓ {word}: {len(frames)}/{processed} frames -> {out_path}")

    return processed, len(frames)


# ── CLI ───────────────────────────────────────────────────────────────────────


def parse_words(values: Optional[list[str]]) -> Optional[set[str]]:
    """Flatten repeated/comma-separated --word values into a lowercase set."""
    if not values:
        return None
    out: set[str] = set()
    for v in values:
        out.update(w.strip().lower() for w in v.split(",") if w.strip())
    return out or None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT, help="Directory of MP4 clips"
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="Keypoint JSON output dir"
    )
    parser.add_argument(
        "--word",
        action="append",
        help="Only process these words (repeatable or comma-separated)",
    )
    parser.add_argument(
        "--min-detection-confidence",
        type=float,
        default=0.5,
        help="MediaPipe min_detection_confidence (default 0.5)",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Render a skeleton-overlay preview MP4 per word",
    )
    args = parser.parse_args()

    if not args.input.is_dir():
        print(f"error: input directory not found: {args.input}", file=sys.stderr)
        return 1

    word_filter = parse_words(args.word)
    clips = sorted(args.input.glob("*.mp4"))
    if word_filter is not None:
        clips = [c for c in clips if c.stem.lower() in word_filter]

    if not clips:
        print(f"error: no matching MP4 files in {args.input}", file=sys.stderr)
        return 1

    stats = RunStats()
    for clip in tqdm(clips, desc="clips", unit="clip"):
        result = process_clip(
            clip,
            args.output,
            args.min_detection_confidence,
            args.visualize,
        )
        if result is not None:
            processed, kept = result
            stats.add_word(clip.stem.lower(), processed, kept)

    print(stats.report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
