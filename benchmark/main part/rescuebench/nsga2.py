"""NSGA-II: nondominated sorting, crowding, tournament, OX and elitist survival.

All objectives are minimized. Permutations express task priorities, not coordinates.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import random
from typing import Callable


def dominates(a, b):
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))


def nondominated_fronts(values):
    dominated = [[] for _ in values]
    counts = [0] * len(values)
    first = []
    for i, a in enumerate(values):
        for j in range(i+1, len(values)):
            b = values[j]
            if dominates(a, b):
                dominated[i].append(j); counts[j] += 1
            elif dominates(b, a):
                dominated[j].append(i); counts[i] += 1
        if counts[i] == 0:
            first.append(i)
    fronts = []
    current = first
    while current:
        fronts.append(current)
        following = []
        for i in current:
            for j in dominated[i]:
                counts[j] -= 1
                if counts[j] == 0:
                    following.append(j)
        current = following
    return fronts


def crowding(front, values):
    distances = {i: 0.0 for i in front}
    if len(front) <= 2:
        return {i: math.inf for i in front}
    for objective in range(len(values[0])):
        ordered = sorted(front, key=lambda i: values[i][objective])
        low, high = values[ordered[0]][objective], values[ordered[-1]][objective]
        if high == low:
            continue
        distances[ordered[0]] = distances[ordered[-1]] = math.inf
        for j in range(1, len(ordered)-1):
            distances[ordered[j]] += (
                values[ordered[j+1]][objective] - values[ordered[j-1]][objective]) / (high-low)
    return distances


def order_crossover(a, b, rng):
    if len(a) < 2:
        return tuple(a)
    lo, hi = sorted(rng.sample(range(len(a)+1), 2))
    child = [None] * len(a)
    child[lo:hi] = a[lo:hi]
    positions = list(range(hi, len(a))) + list(range(lo))
    # OX scans the other parent from the end of the copied interval.
    rotated = b[hi:] + b[:hi]
    remaining = [gene for gene in rotated if gene not in set(a[lo:hi])]
    for index, gene in zip(positions, remaining):
        child[index] = gene
    return tuple(child)


def mutate(genes, rng):
    genes = list(genes)
    if len(genes) >= 2:
        a, b = sorted(rng.sample(range(len(genes)), 2))
        if rng.random() < .5:
            genes[a], genes[b] = genes[b], genes[a]
        else:
            genes[a:b+1] = reversed(genes[a:b+1])
    return tuple(genes)


@dataclass
class SearchResult:
    genes: tuple
    objectives: tuple
    trace: list
    evaluations: int


def optimize(n: int, evaluate: Callable, preference: Callable, *, seed=0,
             population=24, generations=8, seeds=()):
    rng = random.Random(seed)
    base = tuple(range(n))
    if n < 2:
        values = tuple(evaluate(base))
        return SearchResult(base, values,
                            [{"generation": 0, "evaluations": 1, "best": values,
                              "front": [values]}], 1)
    cache = {}
    def fitness(genes):
        if genes not in cache:
            value = tuple(evaluate(genes))
            if not all(math.isfinite(x) for x in value):
                raise ValueError("Objective function returned a non-finite value")
            cache[genes] = value
        return cache[genes]
    individuals = []
    for genes in seeds:
        genes = tuple(genes)
        if len(genes) == n and set(genes) == set(base) and genes not in individuals:
            individuals.append(genes)
    individuals = individuals[:population]
    while len(individuals) < population:
        individuals.append(tuple(rng.sample(base, n)))
    history = []
    for generation in range(generations+1):
        values = [fitness(x) for x in individuals]
        fronts = nondominated_fronts(values)
        ranks, distances = {}, {}
        for rank, front in enumerate(fronts):
            ranks.update({i: rank for i in front})
            distances.update(crowding(front, values))
        best = min(fronts[0], key=lambda i: (preference(values[i]), individuals[i]))
        history.append({"generation": generation, "evaluations": len(cache),
                        "best": values[best],
                        "front": list(dict.fromkeys(values[i] for i in fronts[0]))})
        if generation == generations:
            return SearchResult(individuals[best], values[best], history, len(cache))
        def tournament():
            a, b = rng.sample(range(len(individuals)), 2)
            ka, kb = (ranks[a], -distances[a]), (ranks[b], -distances[b])
            return individuals[a if ka < kb or (ka == kb and rng.random() < .5) else b]
        children = []
        while len(children) < population:
            child = order_crossover(tournament(), tournament(), rng)
            if rng.random() < .8:
                child = mutate(child, rng)
            children.append(child)
        combined = individuals + children
        combined_values = [fitness(x) for x in combined]
        survivors = []
        for front in nondominated_fronts(combined_values):
            if len(survivors) + len(front) <= population:
                survivors.extend(front)
            else:
                cd = crowding(front, combined_values)
                # Randomize genuine ties reproducibly instead of favoring one parent.
                rng.shuffle(front)
                front.sort(key=lambda i: -cd[i])
                survivors.extend(front[:population-len(survivors)])
                break
        individuals = [combined[i] for i in survivors]
    raise AssertionError("Unreachable")

