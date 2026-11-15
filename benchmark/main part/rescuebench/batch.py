"""Reproducible paired seeds, descriptive statistics, and bootstrap intervals."""
from __future__ import annotations

from dataclasses import replace
import math
import platform
import random
import statistics
import time

from . import __version__
from .simulation import Comparison


def provenance():
    return {"version": __version__, "python": platform.python_version(),
            "platform": platform.platform(), "processor": platform.processor(),
            "clock": "perf_counter", "units": "model seconds / abstract energy",
            "score": "100*(count + 0.49*mean(1-completion/H) + "
                     "0.24*max(0,1-energy/(3*fleet_capacity)))/(people+0.73); zero if count=0"}


def aggregate(rows, mode):
    field = "found" if mode == "scout" else "rescued"
    algorithms = list(dict.fromkeys(r["algorithm"] for r in rows))
    seeds = sorted({r["seed"] for r in rows})
    wins = {key: 0.0 for key in algorithms}
    for seed in seeds:
        sample = [r for r in rows if r["seed"] == seed]
        best = max(r["score"] for r in sample)
        tied = [r for r in sample if abs(r["score"]-best) < 1e-9]
        for row in tied:
            wins[row["algorithm"]] += 1/len(tied)
    result = []
    for key in algorithms:
        sample = [r for r in rows if r["algorithm"] == key]
        item = {"algorithm": key, "label": sample[0]["label"], "n": len(sample),
                "wins": wins[key], "win_rate": wins[key]/max(1,len(seeds))}
        for metric in [field, "score", "energy", "finished_at", "seconds_per_person", "mean_response"]:
            values = [r[metric] for r in sample if r[metric] is not None]
            item[metric] = {"mean": statistics.mean(values) if values else None,
                            "sd": statistics.stdev(values) if len(values)>1 else 0.0,
                            "n": len(values)}
        values = [r["planning"]["mean_ms"] for r in sample]
        item["planning_ms"] = {"mean": statistics.mean(values),
                               "sd": statistics.stdev(values) if len(values)>1 else 0.0}
        result.append(item)
    paired = []
    target = {r["seed"]: r for r in rows if r["algorithm"] == "nsga2"}
    for key in algorithms:
        if key == "nsga2":
            continue
        other = {r["seed"]: r for r in rows if r["algorithm"] == key}
        diffs = [target[s]["score"]-other[s]["score"] for s in seeds if s in target and s in other]
        interval = None
        if len(diffs) >= 3:
            rng = random.Random(20261109)
            samples = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(2000))
            interval = [samples[49], samples[1949]]
        paired.append({"against": key, "mean_score_difference": statistics.mean(diffs),
                       "bootstrap_95": interval, "n": len(diffs)})
    return {"summary": sorted(result, key=lambda r: -r["score"]["mean"]),
            "paired_nsga2": paired}


def run_series(config, mode, count=5, cancel=None, progress=None):
    if type(count) is not int or not 1 <= count <= 20:
        raise ValueError("Число карт: целое от 1 до 20.")
    if config.seed+count-1 > 2147483647:
        raise ValueError("Слишком большой начальный seed для этой серии.")
    started = time.perf_counter()
    rows = []
    completed = 0
    for index in range(count):
        if cancel is not None and cancel.is_set():
            break
        current = replace(config, seed=config.seed+index)
        comparison = Comparison(current, mode)
        if not comparison.finish(cancel):
            break
        rows.extend({"seed": current.seed, **row} for row in comparison.results())
        completed += 1
        if progress:
            progress(completed, count)
    return {"mode": mode, "config": config.json(), "requested": count, "completed": completed,
            "cancelled": completed < count, "elapsed_seconds": time.perf_counter()-started,
            "metadata": provenance(), "rows": rows,
            **(aggregate(rows,mode) if rows else {"summary": [], "paired_nsga2": []})}
