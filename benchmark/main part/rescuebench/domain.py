from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import heapq
import math
import random


@dataclass(frozen=True)
class Config:
    width: int = 48
    height: int = 40
    people: int = 24
    drones: int = 3
    robots: int = 4
    seed: int = 42
    horizon: int = 360
    density: float = 0.12
    radius: int = 5
    robot_energy: float = 300.0
    drone_energy: float = 180.0
    population: int = 24
    generations: int = 8
    scout_policy: str = "coverage"

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict):
            raise ValueError("Настройки должны быть JSON-объектом.")
        names = {f.name for f in fields(cls)}
        unknown = set(data) - names
        if unknown:
            raise ValueError("Неизвестные настройки: " + ", ".join(sorted(unknown)))
        config = cls(**data)
        bounds = {
            "width": (20, 120), "height": (20, 120), "people": (1, 120),
            "drones": (1, 12), "robots": (1, 16), "seed": (0, 2147483647),
            "horizon": (60, 1800), "radius": (2, 10),
            "population": (12, 64), "generations": (2, 24),
        }
        for name, (lo, hi) in bounds.items():
            value = getattr(config, name)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"{name}: требуется целое число от {lo} до {hi}.")
        for name, lo, hi in [
            ("density", 0, 0.28), ("robot_energy", 40, 2000), ("drone_energy", 40, 2000),
        ]:
            value = getattr(config, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"{name}: требуется конечное число от {lo} до {hi}.")
        if config.scout_policy not in {"sweep", "nearest", "coverage", "nsga2"}:
            raise ValueError("Неизвестный метод общей разведки.")
        return config

    def json(self):
        return asdict(self)


@dataclass(frozen=True)
class Person:
    id: int
    x: int
    y: int
    deadline: float
    extraction: float
    urgency: str

    def json(self):
        return asdict(self)


class Terrain:
    """Known satellite terrain; robots use weighted ground paths, drones fly above it."""

    def __init__(self, config):
        self.config = config
        self.width, self.height = config.width, config.height
        self.base = (1, 1)
        rng = random.Random(config.seed)
        self.cells = [[1.0 for _ in range(self.width)] for _ in range(self.height)]
        # Rectangular damaged buildings, with open passages around the checkpoint.
        target = int(self.width * self.height * config.density)
        blocked = 0
        for _ in range(max(1, target * 4)):
            if blocked >= target:
                break
            x, y = rng.randrange(3, self.width), rng.randrange(3, self.height)
            rw, rh = rng.randint(1, 4), rng.randint(1, 4)
            for yy in range(y, min(y + rh, self.height)):
                for xx in range(x, min(x + rw, self.width)):
                    if self.cells[yy][xx] != 0 and blocked < target:
                        self.cells[yy][xx] = 0
                        blocked += 1
        for y in range(self.height):
            for x in range(self.width):
                if self.cells[y][x] and rng.random() < 0.17:
                    self.cells[y][x] = 2.2  # traversable rubble
        self.cells[1][1] = 1.0
        self.distances, self.parents = self._dijkstra(self.base)
        self.eligible = sorted(self.distances)
        if len(self.eligible) < config.people + 1:
            raise ValueError("Недостаточно доступных клеток для заданного числа людей.")
        self.eligible_set = set(self.eligible)
        self.eligible_mask = sum(1 << (y * self.width + x) for x, y in self.eligible)
        self.path_cache = {}
        self.mask_cache = {}
        candidates = [p for p in self.eligible if math.dist(p, self.base) > 3]
        if len(candidates) < config.people:
            candidates = [p for p in self.eligible if p != self.base]
        rng.shuffle(candidates)
        self.people = []
        for i, (x, y) in enumerate(candidates[:config.people]):
            direct = self.distances[(x, y)]
            minimum_trip = direct / 1.25 + direct / 1.05 + 4
            deadline = min(config.horizon * 0.96,
                           max(25, minimum_trip * rng.uniform(1.3, 2.6)
                               + config.horizon * rng.uniform(0.08, 0.36)))
            urgency = "critical" if deadline < config.horizon * .45 else (
                "serious" if deadline < config.horizon * .7 else "stable")
            self.people.append(Person(i, x, y, round(deadline, 2),
                                      rng.uniform(2, 6), urgency))
        spacing = max(2, int(config.radius * 1.4))
        self.survey_points = [(x, y)
            for row, y in enumerate(range(1, self.height, spacing))
            for x in (range(1, self.width, spacing) if row % 2 == 0
                      else reversed(list(range(1, self.width, spacing))))]
        # Include corners to cover map edges. No hidden victim coordinates are used.
        self.survey_points += [(1, 1), (self.width-1, 1),
                               (self.width-1, self.height-1), (1, self.height-1)]

    def _dijkstra(self, start):
        distances, parents = {start: 0.0}, {}
        heap = [(0.0, start)]
        while heap:
            distance, pos = heapq.heappop(heap)
            if distance != distances[pos]:
                continue
            x, y = pos
            for nx, ny in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
                if not (0 <= nx < self.width and 0 <= ny < self.height):
                    continue
                if not self.cells[ny][nx]:
                    continue
                cost = (self.cells[y][x] + self.cells[ny][nx]) / 2
                new = distance + cost
                if new < distances.get((nx, ny), math.inf):
                    distances[(nx, ny)] = new
                    parents[(nx, ny)] = pos
                    heapq.heappush(heap, (new, (nx, ny)))
        return distances, parents

    def base_path(self, target):
        target = tuple(target)
        if target not in self.path_cache:
            if target not in self.distances:
                return []
            path, pos = [target], target
            while pos != self.base:
                pos = self.parents[pos]
                path.append(pos)
            self.path_cache[target] = list(reversed(path))
        return self.path_cache[target]

    def edge_cost(self, a, b):
        return (self.cells[a[1]][a[0]] + self.cells[b[1]][b[0]]) / 2

    def footprint(self, point):
        cx, cy = int(round(point[0])), int(round(point[1]))
        key = (cx, cy)
        if key not in self.mask_cache:
            r, mask = self.config.radius, 0
            for y in range(max(0, cy-r), min(self.height, cy+r+1)):
                for x in range(max(0, cx-r), min(self.width, cx+r+1)):
                    if (x-cx)**2 + (y-cy)**2 <= r*r and (x, y) in self.eligible_set:
                        mask |= 1 << (y * self.width + x)
            self.mask_cache[key] = mask
        return self.mask_cache[key]

    def json(self):
        return {"width": self.width, "height": self.height,
                "base": list(self.base), "terrain": self.cells,
                "people": [p.json() for p in self.people],
                "eligible_cells": len(self.eligible)}

