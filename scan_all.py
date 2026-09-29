"""Incremental scan of every configured source; only reads source FITS files."""
import json, traceback
from pathlib import Path
from roots import get_roots
import archive
out=[]
for root in get_roots():
    try:
        stats=archive.scan(root)
        out.append(dict(root=root,ok=True,stats=stats))
    except Exception as exc:
        out.append(dict(root=root,ok=False,error=str(exc),traceback=traceback.format_exc()))
    (archive.DATA/'all-roots-scan.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(out[-1],ensure_ascii=False),flush=True)
