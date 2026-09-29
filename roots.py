"""Per-installation, read-only FITS source directories.

The list lives in data/roots.json so public source never contains local paths.
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONFIG = BASE / 'data' / 'roots.json'


def get_roots():
    if not CONFIG.exists():
        return []
    value = json.loads(CONFIG.read_text(encoding='utf-8'))
    if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
        raise ValueError('data/roots.json 必须是路径字符串数组')
    return value


def add_root(path):
    if not isinstance(path, str) or not path.strip():
        raise ValueError('请输入目录路径')
    folder = Path(path.strip().strip('"')).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f'目录不可访问：{folder}')
    if folder == BASE or BASE in folder.parents or folder in BASE.parents:
        raise ValueError('源目录不能是项目目录或其上级目录')
    roots = get_roots()
    if str(folder).casefold() not in {p.casefold() for p in roots}:
        roots.append(str(folder))
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        temporary = CONFIG.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(roots, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(CONFIG)
    return roots


def remove_root(path):
    roots = [p for p in get_roots() if p.casefold() != str(path).casefold()]
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(roots, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(CONFIG)
    return roots
