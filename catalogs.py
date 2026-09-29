"""Small local label catalogue; center points are annotations, not footprints."""
import json, math
from pathlib import Path
import numpy as np

FILE=Path(__file__).resolve().parent/'data'/'catalogs.json'
CATEGORIES=('Messier','NGC','Abell','LBN','LDN')
CAPS={'Messier':25,'NGC':90,'Abell':40,'LBN':45,'LDN':45}
_cache={}
def load():
    stamp=(FILE.stat().st_mtime_ns,FILE.stat().st_size) if FILE.exists() else None
    if _cache.get('stamp')!=stamp:
        rows=json.loads(FILE.read_text(encoding='utf8')) if stamp else []
        _cache.update(stamp=stamp,rows=rows,ra=np.radians([r['ra'] for r in rows]),dec=np.radians([r['dec'] for r in rows]))
    return _cache
def find_name(name):
    """Resolve an exact numbered catalogue designation without an online request."""
    import re
    match=re.fullmatch(r'(?i)\s*(M|Messier|NGC|Abell|A|LBN|LDN)\s*[- ]?\s*(\d+)\s*',name)
    if not match:return None
    prefix,number=match.groups()
    category={'M':'Messier','MESSIER':'Messier','NGC':'NGC','ABELL':'Abell','A':'Abell','LBN':'LBN','LDN':'LDN'}[prefix.upper()]
    target=f'{"M" if category=="Messier" else category} {int(number)}'
    return next((r for r in load()['rows'] if r['category']==category and r['name'].casefold()==target.casefold()),None)
def enabled(mode,fov):
    if mode=='off':return ()
    if mode=='overview':return ('Messier',) if fov<=90 else ()
    if mode=='standard':return ('Messier','NGC','Abell') if fov<=30 else ('Messier',) if fov<=90 else ()
    if mode=='detailed':return CATEGORIES if fov<=15 else ('Messier','NGC','Abell') if fov<=30 else ('Messier',) if fov<=90 else ()
    if mode!='auto':raise ValueError('未知标注等级')
    return CATEGORIES if fov<=8 else ('Messier','NGC','Abell') if fov<=20 else ('Messier',) if fov<=90 else ()
def nearby(ra,dec,fov,mode='auto',selected=CATEGORIES):
    if not all(math.isfinite(x) for x in (ra,dec,fov)) or not 0<=ra<360 or not -90<=dec<=90 or not 0<fov<=360:raise ValueError('无效视图坐标或视场')
    permitted=set(enabled(mode,fov)) & set(selected)
    data=load(); rows=data['rows']
    if not permitted or not rows:return []
    cra,cdec=math.radians(ra),math.radians(dec)
    sep=2*np.arcsin(np.sqrt(np.clip(np.sin((data['dec']-cdec)/2)**2+np.cos(data['dec'])*math.cos(cdec)*np.sin((data['ra']-cra)/2)**2,0,1)))
    radius=math.radians(min(180,max(1.5,fov*.75)))
    result=[]
    for category in CATEGORIES:
        if category not in permitted:continue
        found=[i for i,r in enumerate(rows) if r['category']==category and sep[i]<=radius]
        found.sort(key=lambda i:sep[i])
        result.extend(rows[i] for i in found[:CAPS[category]])
    return result[:200]
