"""
Humanizer — replaces raw mouse_move events with smooth cubic-bezier paths
between click/scroll checkpoint anchors.

How it works
------------
1.  Anchor extraction  — find (t, x, y) for: recording start, every
    mouse_click / mouse_scroll position, recording end.
2.  Segment generation — for each pair of consecutive anchors, generate
    N evenly-timed mouse_move events that follow a cubic bezier curve.
    * Two independent control points offset perpendicular to the direct
      line create a natural arc (curve_strength controls magnitude).
    * Positions use smoothstep ease-in-out: the cursor starts slow,
      accelerates through the arc, and decelerates at the target.
    * The segment duration is lightly jittered so timing is not perfect.
3.  Non-move events    — clicks, scrolls, key events are kept with
    per-gap timing jitter applied.
4.  Merge + sort       — generated moves and jittered non-moves are
    merged back into a single timestamp-ordered list.
"""
from __future__ import annotations
import math
import random
import dataclasses
from typing import List, Tuple

from src.models.macro import MacroEvent


_ANCHOR_TYPES      = frozenset({"mouse_click", "mouse_scroll"})
_TARGET_STEP_S     = 0.016    # aim for ~60 fps step density
_STEPS_PER_PX      = 0.15     # also scale by distance: ~1 step per 6–7 px
_MIN_STEPS         = 3
_MAX_STEPS         = 120
_DEFAULT_SPEED_PXS = 500.0    # fallback when recording has no move data
_MIN_SPEED_PXS     = 80.0     # floor — always move at least this fast
_MAX_SPEED_PXS     = 2500.0   # ceiling — prevent absurdly fast movement


class Humanizer:
    """Replaces recorded mouse moves with smooth bezier paths and jittered timing."""

    def __init__(self) -> None:
        self.timing_jitter:  float = 0.05   # ±fraction of each inter-event gap
        self.mouse_noise:    float = 1.5    # Gaussian px noise per generated point
        self.curve_strength: float = 0.25   # max perp. offset as fraction of segment dist
        self.add_curves:     bool  = True   # False → timing jitter only
        self.typing_variation: float = 0.15  # spread of key hold / gap times

    # ------------------------------------------------------------------

    def apply(self, events: List[MacroEvent]) -> List[MacroEvent]:
        if not events:
            return events
        events = vary_typing(events, self.typing_variation)
        if not self.add_curves:
            return _jitter_timeline(events, self.timing_jitter)
        return self._smooth_humanize(events)

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    def _smooth_humanize(self, events: List[MacroEvent]) -> List[MacroEvent]:
        anchors = _build_anchors(events)
        if len(anchors) < 2:
            return _jitter_timeline(events, self.timing_jitter)

        # Derive a natural movement speed from the recording itself.
        # Using the full recorded path distance / full path time means the
        # generated paths feel as fast (or slow) as the original user — but
        # dwell time (pausing before a click) is stripped out of movement.
        avg_speed = _compute_avg_speed(events)

        # Build smooth paths between every consecutive pair of checkpoints
        generated: List[MacroEvent] = []
        for i in range(len(anchors) - 1):
            t0, x0, y0 = anchors[i]
            t1, x1, y1 = anchors[i + 1]
            generated.extend(self._bezier_segment(x0, y0, x1, y1, t0, t1, avg_speed))

        # Keep all non-move events with per-gap timing jitter
        non_moves = [e for e in events if e.type != "mouse_move"]
        jittered  = _jitter_timeline(non_moves, self.timing_jitter)

        return sorted(generated + jittered, key=lambda e: e.timestamp)

    def _bezier_segment(
        self,
        x0: float, y0: float,
        x1: float, y1: float,
        t_start: float, t_end: float,
        avg_speed: float,
    ) -> List[MacroEvent]:
        dist = math.hypot(x1 - x0, y1 - y0)
        if dist < 2.0:
            return []

        # How long this segment *should* take at the recording's natural speed.
        # A small Gaussian offset gives each movement a slightly different pace.
        base_dur = dist / avg_speed
        jf  = 1.0 + random.gauss(0, self.timing_jitter)
        dur = max(_TARGET_STEP_S * 2, base_dur * max(0.3, jf))

        # Hard cap: never let generated moves run past the anchor's original
        # timestamp.  The mouse arrives early and idles; the click fires at
        # its recorded time.  This prevents moves from stomping over clicks
        # when the recording had a fast drag.
        original_gap = t_end - t_start
        if original_gap > _TARGET_STEP_S * 2:
            dur = min(dur, original_gap * 0.92)

        # Step count: pick the larger of distance-based and time-based targets,
        # then clamp so we neither under-sample short paths nor flood long ones.
        n = max(
            _MIN_STEPS,
            min(_MAX_STEPS, max(int(dist * _STEPS_PER_PX),
                                int(dur  / _TARGET_STEP_S))),
        )

        # Perpendicular unit vector
        dx, dy = x1 - x0, y1 - y0
        px, py = -dy / dist, dx / dist

        # Two independent control points for a cubic bezier.
        # Each is placed at 1/3 and 2/3 along the direct line, then shifted
        # perpendicularly by a Gaussian-random amount.
        max_off = dist * self.curve_strength
        c1x = x0 + dx / 3.0 + px * random.gauss(0, max_off * 0.4)
        c1y = y0 + dy / 3.0 + py * random.gauss(0, max_off * 0.4)
        c2x = x0 + 2.0 * dx / 3.0 + px * random.gauss(0, max_off * 0.4)
        c2y = y0 + 2.0 * dy / 3.0 + py * random.gauss(0, max_off * 0.4)

        moves: List[MacroEvent] = []
        for step in range(1, n + 1):
            t_norm = step / n

            # Smoothstep maps linear time → eased position progress.
            # The cursor starts slow, arcs fast through the middle,
            # and decelerates as it approaches the target.
            u = _smoothstep(t_norm)
            s = 1.0 - u

            bx = s**3 * x0 + 3*s**2*u * c1x + 3*s*u**2 * c2x + u**3 * x1
            by = s**3 * y0 + 3*s**2*u * c1y + 3*s*u**2 * c2y + u**3 * y1

            if self.mouse_noise > 0:
                bx += random.gauss(0, self.mouse_noise)
                by += random.gauss(0, self.mouse_noise)

            moves.append(MacroEvent(
                type      = "mouse_move",
                timestamp = t_start + t_norm * dur,
                x         = int(round(bx)),
                y         = int(round(by)),
            ))

        return moves


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _compute_avg_speed(events: List[MacroEvent]) -> float:
    """
    Compute average cursor speed (px/s) from the recorded mouse_move events.

    Uses the full recorded path distance divided by the total move-event
    time span.  This captures "how fast this user actually moves their
    mouse" — slow deliberate users produce slow paths, fast users produce
    fast ones — while completely ignoring dwell time (pauses before clicks).
    """
    moves = [e for e in events
             if e.type == "mouse_move" and e.x is not None and e.y is not None]
    if len(moves) < 2:
        return _DEFAULT_SPEED_PXS

    total_dist = sum(
        math.hypot(moves[i].x - moves[i - 1].x, moves[i].y - moves[i - 1].y)
        for i in range(1, len(moves))
    )
    total_time = moves[-1].timestamp - moves[0].timestamp

    if total_time < 0.001 or total_dist < 1.0:
        return _DEFAULT_SPEED_PXS

    return max(_MIN_SPEED_PXS, min(_MAX_SPEED_PXS, total_dist / total_time))


def _build_anchors(events: List[MacroEvent]) -> List[Tuple[float, float, float]]:
    """
    Return a list of (timestamp, x, y) checkpoints:
      - the first event that carries a screen position
      - every mouse_click and mouse_scroll event
      - the last event that carries a screen position
    """
    anchors: List[Tuple[float, float, float]] = []
    seen: set = set()

    def _push(ts: float, x: float, y: float) -> None:
        key = round(ts, 6)
        if key not in seen:
            anchors.append((ts, x, y))
            seen.add(key)

    for ev in events:
        if ev.x is not None and ev.y is not None:
            _push(ev.timestamp, float(ev.x), float(ev.y))
            break

    for ev in events:
        if ev.type in _ANCHOR_TYPES and ev.x is not None and ev.y is not None:
            _push(ev.timestamp, float(ev.x), float(ev.y))

    for ev in reversed(events):
        if ev.x is not None and ev.y is not None:
            _push(ev.timestamp, float(ev.x), float(ev.y))
            break

    return anchors


def _smoothstep(t: float) -> float:
    """Hermite ease-in-out: velocity is zero at t=0 and t=1."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


_KEY_TYPES = ("key_press", "key_release")
# Each key gap is scaled by a factor drawn around 1 and kept in this range,
# so a gap never vanishes or balloons.
_TYPING_FACTOR_MIN, _TYPING_FACTOR_MAX = 0.4, 1.8


def vary_typing(events: List[MacroEvent], amount: float) -> List[MacroEvent]:
    """Give typing a natural, never-identical rhythm.

    Real typing varies in two independent ways: how long each key is held
    (press to release) and the pauses between keys.  Here every gap between
    consecutive key events is scaled by its own random factor (Gaussian
    around 1, spread ``amount``), which varies both at once.

    Guarantees:
    * the **order** of key events never changes, so a shortcut stays a
      shortcut (Ctrl is still down when C goes down);
    * typing stays inside its **burst**: a run of key events between two
      clicks or scrolls is squeezed back if it would run past the next one;
    * mouse events are left exactly where they were.
    """
    if amount <= 0 or not events:
        return list(events)
    out = list(events)
    # Indices of key events, split into bursts at clicks and scrolls.
    bursts: List[List[int]] = [[]]
    for i, e in enumerate(out):
        if e.type in _KEY_TYPES:
            bursts[-1].append(i)
        elif e.type in ("mouse_click", "mouse_scroll") and bursts[-1]:
            bursts.append([])

    for burst in bursts:
        if len(burst) < 2:
            continue
        t0 = out[burst[0]].timestamp
        # The burst must end before the next click/scroll after it.
        limit = next((e.timestamp for e in out[burst[-1] + 1:]
                      if e.type in ("mouse_click", "mouse_scroll")), None)
        gaps = []
        for a, b in zip(burst, burst[1:], strict=False):   # neighbours
            gap = out[b].timestamp - out[a].timestamp
            factor = min(_TYPING_FACTOR_MAX,
                         max(_TYPING_FACTOR_MIN, random.gauss(1.0, amount)))
            gaps.append(gap * factor)
        total = sum(gaps)
        if limit is not None and total > 0:
            room = max(0.0, limit - t0) * 0.98
            if total > room:
                gaps = [g * room / total for g in gaps]
        t = t0
        for idx, gap in zip(burst[1:], gaps, strict=True):
            t += gap
            out[idx] = dataclasses.replace(out[idx], timestamp=t)
    # Mouse moves between keys keep their times; re-sort the whole list.
    return sorted(out, key=lambda e: e.timestamp)


def _jitter_timeline(events: List[MacroEvent], jitter: float) -> List[MacroEvent]:
    """Return a copy with slightly randomised inter-event gaps."""
    if not events or jitter <= 0.0:
        return list(events)

    out: List[MacroEvent] = [events[0]]
    prev_orig = events[0].timestamp
    prev_new  = events[0].timestamp

    for ev in events[1:]:
        gap     = ev.timestamp - prev_orig
        new_gap = max(0.0, gap * (1.0 + random.uniform(-jitter, jitter)))
        new_t   = prev_new + new_gap
        out.append(dataclasses.replace(ev, timestamp=new_t))
        prev_orig = ev.timestamp
        prev_new  = new_t

    return out
