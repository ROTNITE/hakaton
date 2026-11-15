from __future__ import annotations

from dataclasses import dataclass
import math
import random
import time

from .nsga2 import optimize


SCOUT_METHODS = [
    ("sweep", "Полосовой обход"),
    ("nearest", "Ближний сектор"),
    ("coverage", "Прирост покрытия"),
    ("nsga2", "NSGA-II"),
]
RESCUE_METHODS = [
    ("nearest", "Ближайший человек"),
    ("deadline", "Сначала срочные"),
    ("local", "Локальный поиск"),
    ("nsga2", "NSGA-II"),
]


@dataclass(frozen=True)
class Job:
    id: int
    distance: float
    deadline: float
    extraction: float


def schedule(order, jobs, availability, now, horizon, capacity):
    """Decode priorities into capacity-one pickup -> checkpoint missions.

    availability: (time_until_free, energy_on_return) for each public robot.
    Only already discovered jobs enter this function.
    """
    ready = [now + item[0] for item in availability]
    energy = [max(0, item[1]) for item in availability]
    queues = [[] for _ in availability]
    served, completion, spent = 0, 0.0, 0.0
    for index in order:
        job = jobs[index]
        cost = 2.35 * job.distance + .08 * (job.extraction + 2)
        duration = job.distance / 1.25 + job.distance / 1.05 + job.extraction + 2
        if cost > capacity:
            completion += horizon
            continue
        options = []
        for r in range(len(ready)):
            recharge = max(0, cost - energy[r]) / 10
            finish = ready[r] + recharge + duration
            options.append((finish, r, recharge))
        finish, r, recharge = min(options)
        if finish <= min(job.deadline, horizon):
            ready[r] = finish
            energy[r] = min(capacity, energy[r] + recharge * 10) - cost
            queues[r].append(job.id)
            served += 1
            completion += finish - now
            spent += cost
        else:
            completion += horizon
    objectives = (-served, completion / max(1, len(jobs)), spent)
    return objectives, queues


def rescue_preference(value, count, horizon, energy_bound):
    saved, mean_time, energy = -value[0], value[1], value[2]
    timing = max(0, 1 - mean_time / horizon) if saved else 0
    efficiency = max(0, 1 - energy / max(1, energy_bound)) if saved else 0
    return -(saved + .49 * timing + .24 * efficiency)


class RescuePlanner:
    def __init__(self, method, config):
        self.method, self.config = method, config
        self.calls = self.evaluations = 0
        self.total_ms = self.max_ms = 0.0
        self.trace = []
        self.trace_time = None
        self.warm = []

    def plan(self, jobs, availability, now):
        if not jobs:
            return [[] for _ in availability]
        started = time.perf_counter()
        # Shared candidate bound prevents unbounded online combinatorics.
        jobs = sorted(jobs, key=lambda j: (j.deadline, j.id))[:60]
        c = self.config
        evaluate = lambda order: schedule(order, jobs, availability, now, c.horizon, c.robot_energy)[0]
        preference = lambda value: rescue_preference(
            value, len(jobs), c.horizon, c.robot_energy * max(1, len(availability)) * 2)
        near = tuple(sorted(range(len(jobs)), key=lambda i: (jobs[i].distance, jobs[i].id)))
        urgent = tuple(sorted(range(len(jobs)), key=lambda i: (jobs[i].deadline, jobs[i].distance)))
        slack = tuple(sorted(range(len(jobs)), key=lambda i: (
            jobs[i].deadline-now-2*jobs[i].distance-jobs[i].extraction, jobs[i].id)))
        index = {j.id: i for i, j in enumerate(jobs)}
        warm = tuple([index[x] for x in self.warm if x in index]
                     + [i for i in range(len(jobs)) if jobs[i].id not in self.warm])
        count = 1
        if self.method == "nearest":
            order = near
        elif self.method == "deadline":
            order = urgent
        elif self.method == "local":
            rng = random.Random(f"{c.seed}:rescue-local:{now}")
            seeds = list(dict.fromkeys([near, urgent, slack, warm]))
            cache = {s: evaluate(s) for s in seeds}
            order = min(seeds, key=lambda s: preference(cache[s]))
            for _ in range(c.population * (c.generations + 1) - len(seeds)):
                child = list(order)
                if len(child) >= 2:
                    a, b = sorted(rng.sample(range(len(child)), 2))
                    if rng.random() < .5:
                        child[a], child[b] = child[b], child[a]
                    else:
                        gene = child.pop(b); child.insert(a, gene)
                child = tuple(child)
                if child not in cache:
                    cache[child] = evaluate(child)
                if preference(cache[child]) < preference(cache[order]):
                    order = child
            count = len(cache)
        else:
            result = optimize(len(jobs), evaluate, preference,
                              seed=f"{c.seed}:rescue-nsga:{now}",
                              population=c.population, generations=c.generations,
                              seeds=[near, urgent, slack, warm])
            order, count = result.genes, result.evaluations
            # Keep a useful, genuine evolutionary round after late infeasible calls.
            if (len(result.trace) > 1 and result.objectives[0] < 0) or not self.trace:
                self.trace, self.trace_time = result.trace, now
        self.warm = [jobs[i].id for i in order]
        queues = schedule(order, jobs, availability, now, c.horizon, c.robot_energy)[1]
        self.calls += 1; self.evaluations += count
        elapsed = (time.perf_counter()-started)*1000
        self.total_ms += elapsed; self.max_ms = max(self.max_ms, elapsed)
        return queues

    def stats(self):
        return {"calls": self.calls, "evaluations": self.evaluations,
                "mean_ms": self.total_ms / max(1, self.calls),
                "max_ms": self.max_ms, "total_ms": self.total_ms}


class ScoutPlanner:
    def __init__(self, method, terrain):
        self.method, self.terrain = method, terrain
        self.calls = self.evaluations = 0
        self.total_ms = self.max_ms = 0.0
        self.trace = []
        self.trace_time = None

    def plan(self, idle, coverage, active_goals, now):
        t, c = self.terrain, self.terrain.config
        started = time.perf_counter()
        reserved = coverage
        for point in active_goals:
            reserved |= t.footprint(point)
        candidates = [p for p in t.survey_points if (t.footprint(p) & ~reserved).bit_count() > 0]
        # Add coarse frontiers if the survey grid left small uncovered strips.
        if not candidates:
            uncovered = t.eligible_mask & ~reserved
            while uncovered and len(candidates) < 32:
                bit = (uncovered & -uncovered).bit_length()-1
                p = (bit % t.width, bit // t.width)
                candidates.append(p)
                uncovered &= ~t.footprint(p)
        candidates = [p for p in candidates if any(
            math.dist((d.x, d.y), p) + math.dist(p, t.base) + 3 <= d.energy + 1e-9
            for d in idle)]
        if not candidates or not idle:
            return {}
        # Preserve broad spatial variety. Candidate selection never sees people.
        if self.method == "nsga2" and len(candidates) > 32:
            chosen = sorted(candidates, key=lambda p: (
                -(t.footprint(p) & ~reserved).bit_count(), p))[:16]
            step = max(1, len(candidates)//16)
            chosen += candidates[::step][:16]
            candidates = list(dict.fromkeys(chosen))
        masks = [t.footprint(p) for p in candidates]
        result = {}
        evaluations = 1
        if self.method == "nsga2":
            depth = min(len(candidates), len(idle)*2)
            def decode(order):
                positions = [(d.x, d.y) for d in idle]
                arrivals = [0.0] * len(idle)
                consumed = [0.0] * len(idle)
                plans = {d.id: [] for d in idle}
                mask, energy = reserved, 0.0
                for i in order[:depth]:
                    point = candidates[i]
                    options = [(arrivals[r]+math.dist(positions[r], point)/3.0, r)
                               for r in range(len(idle))
                               if consumed[r] + math.dist(positions[r], point)
                               + math.dist(point, t.base) + 3 <= idle[r].energy + 1e-9]
                    if not options:
                        continue
                    arrival, r = min(options)
                    distance = math.dist(positions[r], point)
                    arrivals[r] = arrival
                    positions[r] = point
                    consumed[r] += distance
                    plans[idle[r].id].append(point)
                    energy += distance
                    mask |= masks[i]
                gain = (mask & ~reserved).bit_count()
                return (-gain, max(arrivals), energy), plans
            near = tuple(sorted(range(len(candidates)), key=lambda i:
                min(math.dist((d.x,d.y), candidates[i]) for d in idle)))
            gain = tuple(sorted(range(len(candidates)), key=lambda i: -(masks[i] & ~reserved).bit_count()))
            max_gain = max(1, len(idle)*2*math.pi*c.radius*c.radius)
            max_time = max(1, math.hypot(t.width,t.height)*2/3)
            def preference(v):
                return .7*v[0]/max_gain + .2*v[1]/max_time + .1*v[2]/max(1,max_time*3)
            search = optimize(len(candidates), lambda order: decode(order)[0], preference,
                seed=f"{c.seed}:scout-nsga:{now}", population=c.population,
                generations=c.generations, seeds=[near, gain])
            result = decode(search.genes)[1]
            evaluations = search.evaluations
            if len(search.trace) > 1 or not self.trace:
                self.trace, self.trace_time = search.trace, now
        else:
            available = list(range(len(candidates)))
            for d in idle:
                feasible = [i for i in available if math.dist((d.x, d.y), candidates[i])
                            + math.dist(candidates[i], t.base) + 3 <= d.energy + 1e-9]
                if not feasible:
                    continue
                if self.method == "sweep":
                    # Boustrophedon order is inherited from the public survey grid.
                    index = feasible[0]
                elif self.method == "nearest":
                    index = min(feasible, key=lambda i: math.dist((d.x,d.y), candidates[i]))
                else:
                    index = max(feasible, key=lambda i:
                        (masks[i] & ~reserved).bit_count() /
                        (1+math.dist((d.x,d.y), candidates[i])))
                result[d.id] = [candidates[index]]
                reserved |= masks[index]
                available.remove(index)
        self.calls += 1; self.evaluations += evaluations
        elapsed = (time.perf_counter()-started)*1000
        self.total_ms += elapsed; self.max_ms = max(self.max_ms, elapsed)
        return result

    def stats(self):
        return {"calls": self.calls, "evaluations": self.evaluations,
                "mean_ms": self.total_ms/max(1,self.calls),
                "max_ms": self.max_ms, "total_ms": self.total_ms}

