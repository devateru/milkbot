"""Align a standalone maimai chart capture using the eight outside lanes."""

from bisect import bisect_left
from math import ceil
from statistics import median


CAPTURE_FPS = 30
MATCH_WINDOW = 0.055
PREFIX_SECONDS = 8


class CaptureAlignment:
    def __init__(self, width, height, chart, timestamps):
        import cv2
        import numpy as np

        self.cv2, self.np = cv2, np
        self.width, self.height = width, height
        first_note = chart.notes[0].time
        self.earliest = max(-first_note, max(timestamps) - chart.end - 0.2)
        self.latest = min(timestamps) - first_note + 1
        self.events = [[] for _ in range(8)]
        self.anchors = []
        for lane in range(1, 9):
            times = sorted({note.time for note in chart.notes if note.lane == lane and
                            note.time <= first_note + PREFIX_SECONDS and note.earliest == note.latest})
            for previous, current, following in zip([-float('inf'), *times], times, [*times[1:], float('inf')]):
                if min(current - previous, following - current) > 2 * MATCH_WINDOW:
                    self.anchors.append((current, lane - 1))
        self.anchors.sort()
        self.checked = float('-inf')
        self.map = None
        self.previous = None

    def ring(self, image):
        np, cv2 = self.np, self.cv2
        scale = self.height / 180
        small = cv2.resize(image, (round(self.width / scale), 180), interpolation=cv2.INTER_AREA)
        circles = cv2.HoughCircles(small, cv2.HOUGH_GRADIENT, 1, 75, param1=85, param2=26,
                                   minRadius=54, maxRadius=89)
        if circles is None:
            return None
        angles = np.deg2rad(np.arange(0, 360, 3))[:, None]
        distances = np.array([-.11, -.065, -.025, -.012, 0, .012, .025, .065, .11])
        matches = []
        for x, y, radius in circles[0]:
            if min(x, small.shape[1] - x, y, 180 - y) < radius:
                continue
            point_x = (x + radius * np.cos(angles) * (1 + distances)).astype(np.float32)
            point_y = (y + radius * np.sin(angles) * (1 + distances)).astype(np.float32)
            strips = cv2.remap(small, point_x, point_y, cv2.INTER_LINEAR)
            rim = strips[:, 2:7].max(axis=1).astype(float)
            sides = np.maximum(strips[:, :2].mean(axis=1), strips[:, 7:].mean(axis=1))
            if np.mean((rim > 70) & (rim - sides > 27)) >= .72:
                matches.append((x * scale, y * scale, radius * scale))
        return matches[0] if len(matches) == 1 else None

    def feed(self, frame):
        if len(self.anchors) < 6 or frame.time > self.latest + self.anchors[-1][0] + MATCH_WINDOW:
            return
        np, cv2 = self.np, self.cv2
        image = np.frombuffer(frame.pixels, np.uint8).reshape(self.height, self.width)
        if self.map is None:
            if frame.time - self.checked < .22:
                return
            self.checked = frame.time
            circle = self.ring(image)
            if circle is None:
                return
            x, y, radius = circle
            lanes = np.arange(8) * 45 - 67.5
            angles = np.deg2rad(lanes[:, None] + np.arange(-9, 10, 2)).reshape(-1, 1)
            distances = radius * np.linspace(.97, 1.085, 13)
            self.map = ((x + np.cos(angles) * distances).astype(np.float32),
                        (y + np.sin(angles) * distances).astype(np.float32))
        strips = cv2.remap(image, *self.map, cv2.INTER_LINEAR).reshape(8, -1)
        values = strips.mean(axis=1)
        if self.previous is not None:
            previous_time, previous = self.previous
            drops = previous - values
            falling = np.flatnonzero(drops >= 15)
            # A scene change can darken the whole ring at once.
            if frame.time - previous_time <= .075 and len(falling) <= 4:
                for lane in falling:
                    self.events[lane].append((frame.time + previous_time) / 2)
        self.previous = frame.time, values

    def origin(self):
        required = max(6, ceil(.72 * len(self.anchors)))
        if len(self.anchors) < required:
            return None

        def match(offset):
            offsets = []
            for time, lane in self.anchors:
                events = self.events[lane]
                expected = time + offset
                at = bisect_left(events, expected)
                nearby = events[max(0, at - 1):at + 1]
                if nearby:
                    closest = min(nearby, key=lambda hit: abs(hit - expected))
                    if abs(closest - expected) <= MATCH_WINDOW:
                        offsets.append(closest - time)
            return offsets

        # Try the first few visible notes so a hidden/missed first tap alone cannot set the clock.
        candidates = []
        for time, lane in self.anchors[:5]:
            for hit in self.events[lane]:
                offset = hit - time
                if not self.earliest <= offset <= self.latest:
                    continue
                offsets = match(offset)
                if len(offsets) >= required:
                    offset = median(offsets)
                    offsets = match(offset)
                    if len(offsets) >= required:
                        candidates.append((len(offsets), sum(abs(value - offset) for value in offsets), offset))
        if not candidates:
            return None
        candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
        score, _, origin = candidates[0]
        if any(count >= score - 1 and abs(offset - origin) > .085 for count, _, offset in candidates[1:]):
            return None
        return origin
