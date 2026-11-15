"""Versioned user settings. The 2D benchmark remains an immutable reference."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math

from contracts.protocol import ProtocolError

MAP_SIZES = (25, 35, 45, 55, 65, 75, 100, 125, 150)
PRESETS = ('open', 'urban', 'clusters', 'scarce', 'uncertain', 'dynamic')
EVENT_DEFAULTS = {
    'v052': {'collapse': 20, 'fire': 18, 'flood': 12, 'mud': 25,
             'road_damage': 23, 'smoke': 28, 'appearance': 30},
    'v3': {'collapse': 12, 'fire': 12, 'flood': 10, 'mud': 14,
           'road_damage': 14, 'smoke': 15, 'low_visibility': 12, 'new_target': 20},
}


@dataclass(frozen=True)
class Settings:
    map_size: int = 25
    seed: int = 2026
    preset: str = 'urban'
    scouts: int = 3
    rescuers: int = 4
    people: int = 16
    horizon: float = 480.0
    layout: str = 'generated_city'
    city_revision: str = '1.1'
    event_profile: str = 'v052'
    resource_profile: str = 'unlimited'
    ground_battery_wh: float = 220.0
    aerial_battery_wh: float = 120.0
    initial_battery_fraction: float = 1.0
    energy_reserve_fraction: float = .10
    probabilities: dict[str, float] = field(default_factory=lambda: dict(EVENT_DEFAULTS['v052']))
    sensor_reliability: float = 1.0
    communication_range_m: float = 180.0
    communication_latency_s: float = 0.2
    communication_loss: float = 0.0
    competition: bool = False

    @classmethod
    def parse(cls, value: dict | None = None) -> 'Settings':
        value = {} if value is None else value
        if not isinstance(value, dict):
            raise ProtocolError('INVALID_REQUEST', 'settings must be an object')
        unknown = set(value) - set(cls.__dataclass_fields__)
        if unknown:
            raise ProtocolError('INVALID_REQUEST', 'Unknown setting', {'fields': sorted(unknown)})
        data = asdict(cls())
        data.update(value)
        if type(data['competition']) is not bool:
            raise ProtocolError('INVALID_REQUEST', 'competition must be a boolean')
        for key, low, high in (('seed', 0, 999999999), ('scouts', 1, 48),
                               ('rescuers', 1, 40), ('people', 3, 600)):
            if type(data[key]) is not int or not low <= data[key] <= high:
                raise ProtocolError('INVALID_REQUEST', f'{key}: integer {low}..{high}')
        if type(data['map_size']) is not int or data['map_size'] not in MAP_SIZES:
            raise ProtocolError('INVALID_REQUEST', 'map_size is outside the v0.5.2 choices')
        for key, choices in (('preset', PRESETS), ('event_profile', tuple(EVENT_DEFAULTS)),
                             ('layout', ('generated_city', 'rescue_quarter')),
                             ('city_revision', ('1.1', '2.0', '2.1', '2.2')),
                             ('resource_profile', ('unlimited', 'contest'))):
            if data[key] not in choices:
                raise ProtocolError('INVALID_REQUEST', f'Unknown {key}')
        if 'horizon' not in value:
            data['horizon'] = 480.0 * data['map_size'] / 25
        if 'sensor_reliability' not in value and data['preset'] == 'uncertain':
            data['sensor_reliability'] = .83
        for key, low, high in (('horizon', 1, 86400), ('sensor_reliability', 0, 1),
                               ('ground_battery_wh', 1, 10000), ('aerial_battery_wh', 1, 10000),
                               ('initial_battery_fraction', 0, 1), ('energy_reserve_fraction', 0, .75),
                               ('communication_range_m', 5, 10000),
                               ('communication_latency_s', 0, 60), ('communication_loss', 0, 1)):
            number = data[key]
            if type(number) not in (int, float) or not low <= number <= high or not math.isfinite(number):
                raise ProtocolError('INVALID_REQUEST', f'{key}: finite number {low}..{high}')
        if 'probabilities' not in value:
            data['probabilities'] = dict(EVENT_DEFAULTS[data['event_profile']])
        probs = data['probabilities']
        if not isinstance(probs, dict) or set(probs) != set(EVENT_DEFAULTS[data['event_profile']]):
            raise ProtocolError('INVALID_REQUEST', 'Probabilities must match the selected event profile')
        if any(type(p) not in (int, float) or not 0 <= p <= 100 or not math.isfinite(p) for p in probs.values()):
            raise ProtocolError('INVALID_REQUEST', 'Probability: finite percent 0..100')
        data['probabilities'] = dict(probs)
        return cls(**data)

    @property
    def event_window_s(self):
        return 80.0 if self.event_profile == 'v052' else 30.0

    def json(self):
        return asdict(self)
