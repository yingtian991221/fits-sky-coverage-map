"""Installation-specific settings. Never commit data/settings.json."""
import copy
import json
import os
import re
import shutil
import threading
from pathlib import Path

BASE = Path(__file__).resolve().parent
FILE = BASE / 'data' / 'settings.json'
DEFAULTS = {'solver': {'executable': '', 'catalog_dir': '', 'database': '', 'timeout': 90},
            'device_overrides': []}
_lock = threading.RLock()
_cache = {}


def load():
    with _lock:
        stamp = (str(FILE), FILE.stat().st_mtime_ns) if FILE.exists() else (str(FILE), None)
        if _cache.get('stamp') != stamp:
            value = json.loads(FILE.read_text(encoding='utf-8-sig')) if FILE.exists() else {}
            merged = copy.deepcopy(DEFAULTS)
            merged['solver'].update(value.get('solver', {}))
            merged['device_overrides'] = value.get('device_overrides', [])
            _cache.update(stamp=stamp, value=merged)
        return copy.deepcopy(_cache['value'])


def save(value):
    if not isinstance(value, dict): raise ValueError('Settings must be a JSON object / 设置必须是对象')
    solver = value.get('solver', {})
    if not isinstance(solver, dict): raise ValueError('Invalid solver settings')
    clean = copy.deepcopy(DEFAULTS)
    for key in ('executable', 'catalog_dir', 'database'):
        item = solver.get(key, '')
        if not isinstance(item, str) or len(item) > 2048: raise ValueError('Invalid '+key)
        clean['solver'][key] = item.strip().strip('"')
    if clean['solver']['database'] and not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', clean['solver']['database']):
        raise ValueError('Database must be an ASTAP abbreviation, e.g. d50')
    timeout = solver.get('timeout', 90)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 10 <= timeout <= 1800:
        raise ValueError('Timeout must be 10–1800 seconds')
    clean['solver']['timeout'] = timeout
    rules = value.get('device_overrides', [])
    if not isinstance(rules, list) or len(rules) > 200: raise ValueError('Invalid device overrides')
    for rule in rules:
        if not isinstance(rule, dict) or not all(isinstance(rule.get(k), str) and rule[k].strip() for k in ('path', 'telescope')):
            raise ValueError('Each device override needs path and telescope')
        path = Path(rule['path']).expanduser()
        if not path.is_absolute(): raise ValueError('Override paths must be absolute')
        bins = rule.get('focal_bins', [])
        if not isinstance(bins, list) or any(isinstance(b, bool) or not isinstance(b, int) or b <= 0 for b in bins) or bins != sorted(set(bins)):
            raise ValueError('focal_bins must be increasing positive integers')
        clean['device_overrides'].append(dict(path=str(path.resolve()), telescope=rule['telescope'].strip(), focal_bins=bins))
    with _lock:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = FILE.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(FILE)
        _cache.clear()
    return clean


def solver_info():
    config = load()['solver']
    executable = config['executable'] or os.environ.get('ASTAP_PATH') or shutil.which('astap_cli') or shutil.which('astap')
    if not executable and os.name == 'nt':
        candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'astap' / 'astap_cli.exe'
        if candidate.is_file(): executable = str(candidate)
    found = Path(executable).is_file() if executable else False
    catalog = config['catalog_dir']
    return dict(**config, resolved_executable=executable or '', executable_found=found,
                catalog_accessible=not catalog or Path(catalog).is_dir(),
                note='Executable detection is not a plate-solve test. Star catalogue compatibility must be verified with your frames.')


def solver_command(source, output, pointing):
    info = solver_info()
    if not info['executable_found']: raise RuntimeError('Configure ASTAP in Settings / 请在设置中指定 ASTAP')
    if not info['catalog_accessible']: raise RuntimeError('ASTAP catalogue directory is unavailable / 星表目录不可访问')
    cmd = [info['resolved_executable'], '-f', str(source), '-o', str(output),
           '-r', '10' if pointing else '180', '-wcs', '-log']
    if info['catalog_dir']: cmd += ['-d', info['catalog_dir']]
    if info['database']: cmd += ['-D', info['database']]
    return cmd


def device_rule(path, rules=None):
    # Lexical absolute paths avoid reopening tens of thousands of source files.
    location = Path(os.path.abspath(path))
    candidates = []
    for rule in (load()['device_overrides'] if rules is None else rules):
        parent = Path(os.path.abspath(rule['path']))
        if location == parent or parent in location.parents: candidates.append(rule)
    return max(candidates, key=lambda r: len(Path(r['path']).parts)) if candidates else None
