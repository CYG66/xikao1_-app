from __future__ import annotations

from collections import deque


class HeadingOscillationDetector:
    def __init__(self, window_seconds: float = 4.0, deadband: float = 0.12,
                 reversal_limit: int = 4, progress_limit_m: float = 0.12) -> None:
        self.window_seconds = window_seconds
        self.deadband = deadband
        self.reversal_limit = reversal_limit
        self.progress_limit_m = progress_limit_m
        self.samples: deque[tuple[float, float, float, float]] = deque()

    def reset(self) -> None:
        self.samples.clear()

    def add(self, timestamp: float, angular_velocity: float, x: float, y: float) -> dict | None:
        self.samples.append((timestamp, angular_velocity, x, y))
        while self.samples and timestamp - self.samples[0][0] > self.window_seconds:
            self.samples.popleft()
        significant = [sample for sample in self.samples if abs(sample[1]) >= self.deadband]
        reversals = sum(1 for a, b in zip(significant, significant[1:]) if a[1] * b[1] < 0)
        if len(significant) < 5 or reversals < self.reversal_limit:
            return None
        first, last = self.samples[0], self.samples[-1]
        progress = ((last[2] - first[2]) ** 2 + (last[3] - first[3]) ** 2) ** 0.5
        if progress > self.progress_limit_m:
            return None
        event = {"reversals": reversals, "window_seconds": round(last[0] - first[0], 3),
                 "progress_m": round(progress, 4), "peak_angular_velocity": round(max(abs(s[1]) for s in significant), 4)}
        self.reset()
        return event
