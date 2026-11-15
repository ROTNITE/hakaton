"""Write a versioned 3D demonstration scenario, separate from the imported 2D snapshot."""
from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'unreal/MetaRescue/Content/Scenario/quarter.json'
base = [-.7, 1.0]
targets = [(5.5, 2.3), (1.0, 7.1), (7.1, 5.5), (10.0, 7.2),
           (12.4, 10.0), (5.5, 12.2), (14.5, 14.1), (10.0, 3.4)]
people = []
for index, (x, y) in enumerate(targets):
    if x in [1.0, 5.5, 10.0, 14.5]:
        path = [base, [1.0, 1.0], [x, 1.0], [x, y]]
    else:
        path = [base, [1.0, 1.0], [1.0, y], [x, y]]
    people.append({'id': index + 1, 'x': x, 'y': y, 'path': path})
data = {
    'kind': 'rescue_quarter_environment_demo_v3', 'source': 'authored_3d_environment_not_benchmark_comparison',
    'width': 25, 'seed': 20261109, 'grid': [[0] * 25 for _ in range(25)], 'base': base,
    'scouts': 3, 'rescuers': 4, 'ground_battery_Wh': 240, 'people': people,
    'scout_waypoints': [
        [[1, 1], [1, 14.5], [5.5, 14.5], [5.5, 1], [1, 1]],
        [[1.2, 1.2], [10, 1], [10, 14.5], [14.5, 14.5], [14.5, 1], [1.2, 1.2]],
        [[1.2, 1.2], [14.5, 5.5], [1, 5.5], [1, 10], [14.5, 10], [1.2, 1.2]],
    ],
    'units': {'scenario_xy': '10 meters', 'unreal': 'centimeters'},
    'environment_stage': 'physical scene and local demonstration policy; external controller is pending',
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(data, indent=2), encoding='utf-8')
print(OUT)
