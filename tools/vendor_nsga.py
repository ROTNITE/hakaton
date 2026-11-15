"""Copy the user-supplied pure optimizer with a verifiable origin record."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'benchmarks/MetaRescue_Benchmark_v0_5_2/main part/nsga2.py'
destination=ROOT/'controller/vendor/nsga2_v052.py'
digest=hashlib.sha256(source.read_bytes()).hexdigest()
destination.parent.mkdir(parents=True,exist_ok=True)
if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest()!=digest:
    raise RuntimeError('Existing optimizer differs; preserve and review it before vendoring')
if not destination.exists():shutil.copy2(source,destination)
manifest={'format':'metarescue.algorithm-origin.v1','source':source.relative_to(ROOT).as_posix(),
          'destination':destination.relative_to(ROOT).as_posix(),'sha256':digest,'modified':False,
          'imported_at':datetime.now(timezone.utc).isoformat(),
          'scope':'pure NSGA-II only; no World, sensors, event tape or private target data'}
target=destination.parent/'nsga2-origin.json'
if not target.exists():target.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps({'destination':str(destination),'sha256':digest,'modified':False}))
