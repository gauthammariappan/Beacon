# Finds beeps in the stream of mic frames. The same detector runs while recording,
# while training (on the saved recordings) and live, so all three see beeps the same way.
import numpy as np


class BeepDetector:
    def __init__(self, start=5.0, end=2.0, end_frames=2, purity_min=3.0, require_purity=True,
                 min_frames=3, max_frames=120, warmup_frames=40):
        self.start = start                # a beep starts above 5x the noise floor ...
        self.end = end                    # ... and ends once every mic is under 2x
        self.end_frames = end_frames      # ... for 2 frames in a row (32 ms)
        self.purity_min = purity_min      # 2500 Hz vs its neighbours; claps and talking are near 1
        self.require_purity = require_purity
        self.min_frames = min_frames
        self.max_frames = max_frames
        self.warmup_frames = warmup_frames
        self.warm = []
        self.floor = None
        self.active = False
        self.quiet = 0
        self.frames = []
        self.floor_at_start = None
        self.blank_until_ms = -1          # set this after a laser move so the servo isn't heard

    @staticmethod
    def purity(v):
        e = np.asarray(v[0:3], dtype=float)
        side = (np.asarray(v[3:6], dtype=float) + np.asarray(v[6:9], dtype=float)) / 2
        return e / np.maximum(side, 1e-6)

    def push(self, ms, v):
        """Feed one frame (pico_ms, 9 values). Returns a finished beep as a dict, or None."""
        e = np.asarray(v[0:3], dtype=float)
        if self.floor is None:
            # learn the room's background first; the 20th percentile ignores the odd early beep
            self.warm.append(e)
            if len(self.warm) >= self.warmup_frames:
                self.floor = np.maximum(np.percentile(np.array(self.warm), 20, axis=0), 1e-3)
            return None
        if ms < self.blank_until_ms:
            return None

        ratio = e / self.floor
        if not self.active:
            if ratio.max() < self.end:    # only learn while it's really quiet, so a long tone can't hide itself
                self.floor = np.maximum(0.99 * self.floor + 0.01 * e, 1e-3)
            loud = ratio.max() > self.start
            pure = self.purity(v).max() > self.purity_min
            if loud and (pure or not self.require_purity):
                self.active = True
                self.quiet = 0
                self.frames = [(ms, list(v))]
                self.floor_at_start = self.floor.copy()
            return None

        self.frames.append((ms, list(v)))
        self.quiet = self.quiet + 1 if ratio.max() < self.end else 0
        if self.quiet >= self.end_frames or len(self.frames) >= self.max_frames:
            body = self.frames[:-self.quiet] if self.quiet else self.frames
            self.active = False
            self.quiet = 0
            self.frames = []
            if len(body) < self.min_frames:
                return None
            return {"t_start_ms": body[0][0], "t_end_ms": body[-1][0],
                    "frames": body, "floor": self.floor_at_start.copy()}
        return None
