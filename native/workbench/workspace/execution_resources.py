"""Explicit CPU admission reservations; unknown requirements remain exclusive.

Reservations describe the user's allocation, not measured utilisation or an OS
CPU limit. No resource cost is inferred from a parameter name or file size.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil


def normalize(policy=None, nodes=None, check_environment=True):
    if policy is None:
        policy = {}
    if not isinstance(policy, dict) or set(policy) - {'cpuBudget', 'maxParallel', 'stepCpus', 'temporaryFolder'}:
        raise ValueError('Invalid execution resource policy.')
    maximum_cpus = min(1024, max(1, os.cpu_count() or 1))
    result = {'cpuBudget': policy.get('cpuBudget', maximum_cpus),
              'maxParallel': policy.get('maxParallel', 1),
              'stepCpus': policy.get('stepCpus', {}), 'temporaryFolder': policy.get('temporaryFolder', '')}
    for name, maximum in (('cpuBudget', maximum_cpus if check_environment else 1024), ('maxParallel', 32)):
        if type(result[name]) is not int or not 1 <= result[name] <= maximum:
            raise ValueError(name + ' must be an integer between 1 and ' + str(maximum) + '.')
    declarations = result['stepCpus']
    if not isinstance(declarations, dict) or len(declarations) > 512:
        raise ValueError('CPU reservations must be a bounded object keyed by step ID.')
    identities = None if nodes is None else {node['id'] for node in nodes}
    for identity, count in declarations.items():
        if (not isinstance(identity, str) or not re.fullmatch(r'step-[1-9][0-9]{0,8}', identity)
                or identities is not None and identity not in identities):
            raise ValueError('CPU reservation names an unavailable workflow step.')
        if type(count) is not int or not 1 <= count <= result['cpuBudget']:
            raise ValueError('Each CPU reservation must fit within the total CPU budget.')
    result['stepCpus'] = dict(declarations)
    path = result['temporaryFolder']
    if not isinstance(path, str) or len(path) > 32768 or any(ord(c) < 32 for c in path):
        raise ValueError('Invalid temporary-storage folder.')
    if path:
        if not Path(path).is_absolute():
            raise ValueError('Temporary storage requires an absolute folder path.')
        if not check_environment:
            return result
        # Reuse the engine's extended-path and reparse-point policies lazily.
        try:
            from .engine import _io_path, _resolved_path
        except ImportError:
            from engine import _io_path, _resolved_path
        folder = Path(path).absolute()
        if not _io_path(folder).is_dir():
            raise ValueError('Select an existing temporary-storage folder.')
        for parent in [folder, *folder.parents]:
            physical = _io_path(parent)
            if physical.is_symlink() or (hasattr(physical, 'is_junction') and physical.is_junction()):
                raise ValueError('Temporary storage must not use symbolic links or junctions.')
        result['temporaryFolder'] = str(_resolved_path(folder))
    return result


def reservation(policy, identity):
    count = policy['stepCpus'].get(identity)
    return {'cpus': count if count is not None else policy['cpuBudget'],
            'source': 'user-declared' if count is not None else 'unknown-exclusive',
            'memoryBytes': None, 'temporaryBytes': None}


def storage(folder):
    try:
        from .engine import _io_path
    except ImportError:
        from engine import _io_path
    usage = shutil.disk_usage(_io_path(folder))
    if usage.free <= 0:
        raise ValueError('No free space is available in the selected execution folder.')
    return {'availableBytes': usage.free, 'requiredBytes': None,
            'scope': 'Free-space snapshot; tool expansion and peak memory are unknown.'}
