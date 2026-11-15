"""Prepare a validated private layout for an in-process Unreal Core reset."""
from __future__ import annotations

import argparse
from dataclasses import fields
import hashlib
from pathlib import Path

from contracts.protocol import ProtocolError, encode, strict_json
from environment.config import Settings
from environment.layout import generate


def prepare(request):
    settings_keys = {field.name for field in fields(Settings)} - {'seed'}
    base, parameters = request['base'], request['parameters']
    unknown = parameters.keys() - settings_keys
    if unknown:
        raise ProtocolError('INVALID_REQUEST', 'Unknown mission parameters', {'fields': sorted(unknown)})
    settings = {'city_revision': '2.2', **{key: value for key, value in base.items() if key in settings_keys},
                **parameters, 'seed': request['seed']}
    for override, default in (('event_profile', 'probabilities'), ('map_size', 'horizon'),
                              ('preset', 'sensor_reliability')):
        if override in parameters and settings[override] != base.get(override) and default not in parameters:
            settings.pop(default, None)
    include_events = request['generate_events'] or bool(parameters.keys() & {'event_profile', 'probabilities'})
    return generate(Settings.parse(settings), include_events=include_events)


def atomic_write(directory, name, contents):
    path = directory/name
    temporary = path.with_suffix('.part')
    temporary.write_bytes(encode(contents))
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    directory = parser.parse_args().directory
    try:
        request = strict_json((directory/'request.json').read_bytes())
        layout = prepare(request)
        atomic_write(directory, 'layout.json', layout)
        result = {'state': 'prepared', 'seed': layout['settings']['seed'],
                  'sha256': hashlib.sha256((directory/'layout.json').read_bytes()).hexdigest()}
    except ProtocolError as error:
        result = {'state': 'failed', 'code': error.code, 'message': error.message, 'details': error.details or {}}
    except ValueError as error:
        result = {'state': 'failed', 'code': 'CONSTRAINT_VIOLATION', 'message': str(error)}
    atomic_write(directory, 'result.json', result)
    return 0 if result['state'] == 'prepared' else 1


if __name__ == '__main__':
    raise SystemExit(main())
