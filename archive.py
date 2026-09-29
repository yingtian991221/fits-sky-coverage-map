"""Local, read-only FITS archive. All writable state lives beside this module."""
import argparse, collections, hashlib, json, math, os, re, shutil, sqlite3, subprocess, time, warnings, sys
from datetime import datetime, timedelta
if hasattr(sys.stdout,'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
BASE = Path(__file__).resolve().parent
DATA = BASE / 'data'
TMP = BASE / 'tmp'
for p in (DATA, TMP, DATA/'solutions', DATA/'previews'): p.mkdir(parents=True, exist_ok=True)
os.environ['TEMP'] = os.environ['TMP'] = str(TMP)
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.coordinates import SkyCoord
import astropy.units as u
from scipy.ndimage import maximum_filter
from PIL import Image
warnings.filterwarnings('ignore', category=Warning, module='astropy')
DB = DATA / 'archive.sqlite'
import settings

def ident(s): return hashlib.sha256(str(s).encode('utf8')).hexdigest()[:20]
def target_key(s): return re.sub(r'[\s_\-]+','',str(s or '')).casefold()
def dumps(o): return json.dumps(o, ensure_ascii=False, allow_nan=False)
def connect():
    c=sqlite3.connect(DB, timeout=30)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY,path TEXT UNIQUE,root TEXT,size INTEGER,mtime INTEGER,active INTEGER,meta TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS solutions (id TEXT PRIMARY KEY,status TEXT,payload TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS runs (time TEXT,kind TEXT,payload TEXT)')
    c.commit()
    return c
def num(v):
    try:
        f=float(v)
        return f if math.isfinite(f) else None
    except (ValueError,TypeError): return None
def local_time_from_header(meta):
    """Recover DATE-LOC from the saved FITS header, without rereading source FITS."""
    raw=meta.get('date_local')
    if raw is None:
        match=re.search(r"(?m)^DATE-LOC\s*=\s*'([^']+)'",meta.get('header',''))
        raw=match.group(1) if match else None
    if raw:
        try:
            local=datetime.fromisoformat(str(raw))
            utc=datetime.fromisoformat(str(meta['date'])) if meta.get('date') else None
            offset=(local-utc).total_seconds()/3600 if utc else None
            if offset is None or -12<=offset<=14:
                meta['date_local']=str(raw)
                meta['time_basis']='FITS DATE-LOC'
                meta['local_offset_hours']=round(offset,4) if offset is not None else None
                return meta
        except (TypeError,ValueError): pass
    meta['date_local']=None
    meta['time_basis']='FITS DATE-OBS (UTC)' if meta.get('date') else '未知'
    meta['local_offset_hours']=None
    return meta
def capture_version_from_saved_header(meta):
    """Recognize ASIAIR acquisition FITS in an existing index without source reads."""
    if meta.get('version')!='unknown': return meta
    header=meta.get('header') or ''
    if (re.search(r"(?mi)^CREATOR\s*=\s*'ZWO ASIAIR(?: Plus)?'",header)
            and not re.search(r'(?m)^(HISTORY|CALSTAT|NCOMBINE)\b',header)):
        meta['version']='raw'
        meta['version_evidence']='FITS CREATOR=ZWO ASIAIR Plus; no HISTORY/CALSTAT/NCOMBINE'
    return meta
def observing_night(record):
    """Noon-to-noon grouping in the header's local clock; UTC fallback is explicit."""
    if record.get('date_local'):
        try:return (datetime.fromisoformat(record['date_local'])-timedelta(hours=12)).date().isoformat()
        except ValueError:pass
    return (record.get('date') or '未知')[:10]
def focal_band(focal, bins):
    if focal is None: return 'FITS 焦距未知'
    for i, upper in enumerate(bins):
        if focal < upper:
            return f'FITS 焦距 <{upper} mm' if i == 0 else f'FITS 焦距 {bins[i-1]}–{upper-1} mm'
    return f'FITS 焦距 ≥{bins[-1]} mm'

def identify_device(meta, path, rules=None):
    """Use FITS metadata unless this installation explicitly overrides the directory."""
    rule=settings.device_rule(path,rules)
    meta['telescope_display']=rule['telescope'] if rule else meta.get('telescope')
    meta['telescope_source']='directory_override' if rule else 'FITS TELESCOP'
    focal=focal_band(meta.get('focal'),rule['focal_bins']) if rule and rule.get('focal_bins') else meta.get('focal')
    meta['device']=' | '.join(str(v if v is not None else '未知') for v in (meta.get('camera'),meta['telescope_display'],focal))
    date=meta.get('date')
    if date:
        meta['acquisition']=ident([meta['device'],date,meta.get('filter'),meta.get('exposure'),meta.get('width'),meta.get('height'),meta.get('binning')])
    else: meta['acquisition']=ident(path)
    return meta
def coord(ra,dec):
    a,b=num(ra),num(dec)
    if a is not None and b is not None and 0<=a<360 and -90<=b<=90: return [a,b]
    return None
def distance(a,b):
    a,b=np.radians(a),np.radians(b)
    v=np.sin((a[1]-b[1])/2)**2+np.cos(a[1])*np.cos(b[1])*np.sin((a[0]-b[0])/2)**2
    return float(np.degrees(2*np.arcsin(np.sqrt(np.clip(v,0,1)))))
def geometry(header,width,height):
    if not width or not height: raise ValueError('缺少图像尺寸')
    if not str(header.get('CTYPE1','')).startswith('RA') or not str(header.get('CTYPE2','')).startswith('DEC'): raise ValueError('没有 RA/DEC 天球 WCS')
    if not all(k in header for k in ['CRVAL1','CRVAL2','CRPIX1','CRPIX2']): raise ValueError('不完整 WCS')
    if not (all(k in header for k in ['CD1_1','CD1_2','CD2_1','CD2_2']) or ('CDELT1' in header and 'CDELT2' in header)): raise ValueError('缺少 WCS 尺度矩阵')
    w=WCS(header).celestial
    # Pixel edges, not pixel centres. Sample all four edges for distorted WCS.
    corners=np.array([[-.5,-.5],[width-.5,-.5],[width-.5,height-.5],[-.5,height-.5]])
    edge=np.concatenate([np.linspace(corners[i],corners[(i+1)%4],17,endpoint=False) for i in range(4)])
    world=w.all_pix2world(edge,0)
    rt=w.all_world2pix(world,0)
    if not np.isfinite(world).all() or np.max(np.abs(rt-edge))>.1: raise ValueError('WCS 往返误差/数值异常')
    cc=np.array([(width-1)/2,(height-1)/2])
    center=w.all_pix2world([cc],0)[0]
    scale=[distance(center,w.all_pix2world([cc+d],0)[0])*3600 for d in ([1,0],[0,1])]
    if not all(.02<s<120 for s in scale): raise ValueError('不合理像素尺度')
    if max(distance(center,p) for p in world)>20: raise ValueError('第一版暂不接受半径超过20度的视场')
    y=w.all_pix2world([cc+[0,100]],0)[0]
    pa=float(SkyCoord(*center,unit='deg').position_angle(SkyCoord(*y,unit='deg')).degree)
    return dict(center=center.tolist(),polygon=world.tolist(),corners=w.all_pix2world(corners,0).tolist(),scale=scale,rotation=pa,
                width_deg=distance(world[0],world[17]),height_deg=distance(world[17],world[34]),roundtrip_px=float(np.max(np.abs(rt-edge))))

def metadata(p):
    with fits.open(p,mode='readonly',memmap=True,lazy_load_hdus=True) as hdus:
        hdu=next((x for x in hdus if int(x.header.get('NAXIS',0))==2 and x.header.get('NAXIS1',0)>0),None)
        if hdu is None: raise ValueError('没有二维图像 HDU')
        h=hdu.header.copy(); hduno=hdus.index_of(hdu)
        if hdu.fileinfo()['datLoc']+hdu.size>p.stat().st_size: raise ValueError('文件截断：像素数据长度不足')
    rawtype=str(h.get('IMAGETYP',h.get('FRAME','未知')))
    t=rawtype.lower()
    typ=next((v for k,v in [('dark','Dark'),('flat','Flat'),('bias','Bias'),('light','Light'),('science','Light'),('object','Light')] if k in t),'未知')
    hist=str(h.get('HISTORY','')); proc=(hist+' '+str(h.get('SWCREATE',''))).lower()
    evidence='FITS HISTORY/SWCREATE/CALSTAT/NCOMBINE'
    if any(k in proc for k in ['integration','stacked','imageintegration']): version='stacked'
    elif any(k in proc for k in ['calibrat','debayer','registration','registered']): version='calibrated'
    elif 'n.i.n.a' in proc and not hist and not any(k in h for k in ['CALSTAT','NCOMBINE']): version='raw'
    elif str(h.get('CREATOR','')).lower().startswith('zwo asiair') and not hist and not any(k in h for k in ['CALSTAT','NCOMBINE']):
        version='raw';evidence='FITS CREATOR=ZWO ASIAIR Plus; no HISTORY/CALSTAT/NCOMBINE'
    else: version='unknown'
    pointing=coord(h.get('RA'),h.get('DEC'))
    date=h.get('DATE-OBS')
    meta=dict(type=typ,type_raw=rawtype,date=date,date_local=h.get('DATE-LOC'),target=h.get('OBJECT'),camera=h.get('INSTRUME'),telescope=h.get('TELESCOP'),focal=num(h.get('FOCALLEN')),
              filter=h.get('FILTER'),exposure=num(h.get('EXPTIME',h.get('EXPOSURE'))),width=h['NAXIS1'],height=h['NAXIS2'],
              binning=[h.get('XBINNING'),h.get('YBINNING')],pointing=pointing,planned_rotation=num(h.get('OBJCTROT')),pier=h.get('PIERSIDE'),
              version=version,version_evidence=evidence,hdu=hduno,header=h.tostring(sep='\n',endcard=True,padding=False),parent=str(p.parent))
    local_time_from_header(meta)
    identify_device(meta,p)
    try: meta['existing_wcs']=geometry(h,meta['width'],meta['height'])
    except Exception as e: meta['wcs_note']=str(e)
    return meta

def scan(root):
    root=Path(root).resolve()
    if not root.is_dir(): raise ValueError(f'路径不可访问: {root}')
    c=connect(); stats=collections.Counter(); seen=[]
    for p in root.rglob('*'):
        if p.suffix.lower() not in ('.fits','.fit','.fts') or not p.is_file(): continue
        p=p.resolve(); key=ident(str(p).lower()); s=p.stat(); seen.append(key)
        old=c.execute('SELECT size,mtime FROM files WHERE id=?',(key,)).fetchone()
        if old==(s.st_size,s.st_mtime_ns):
            c.execute('UPDATE files SET active=1,root=? WHERE id=?',(str(root),key)); stats['unchanged']+=1; continue
        try: m=metadata(p); stats['read']+=1
        except Exception as e: m={'error':str(e),'type':'未知','version':'unknown'}; stats['error']+=1
        c.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)',(key,str(p),str(root),s.st_size,s.st_mtime_ns,1,dumps(m)))
        c.execute('DELETE FROM solutions WHERE id=?',(key,))
        if m.get('type')=='Light' and m.get('existing_wcs') and 'bad' not in [x.casefold() for x in p.parts]:
            try:
                quality=quality_preview(p,dict(m,id=key))
                if quality['suspicious']: raise ValueError(quality['reason'])
                payload=dict(m['existing_wcs'],source='validated_header_wcs',quality=quality,wcs_header=m['header'])
                c.execute('INSERT OR REPLACE INTO solutions VALUES (?,?,?)',(key,'solved',dumps(payload)))
                stats['header_wcs']+=1
            except Exception as exc:
                c.execute('INSERT OR REPLACE INTO solutions VALUES (?,?,?)',(key,'failed',dumps({'error':str(exc)})))
                stats['wcs_review']+=1
        if (stats['read']+stats['error'])%25==0: c.commit()
        if (stats['read']+stats['error'])%100==0: print(dumps(dict(stats)),flush=True)
    # Only mark deletions after a completed walk. Interrupted scans retain progress.
    oldids=c.execute('SELECT id FROM files WHERE root=?',(str(root),)).fetchall()
    seen=set(seen)
    for (key,) in oldids:
        if key not in seen: c.execute('UPDATE files SET active=0 WHERE id=?',(key,))
    stats['total']=len(seen)
    c.execute('INSERT INTO runs VALUES (?,?,?)',(time.strftime('%Y-%m-%dT%H:%M:%S'),'scan',dumps(dict(stats))))
    c.commit(); c.close(); print(dumps(dict(stats)),flush=True); return dict(stats)

def records():
    c=connect()
    rows=[]
    rules=settings.load()['device_overrides']
    for key,path,root,meta,status,payload in c.execute('SELECT f.id,f.path,f.root,f.meta,s.status,s.payload FROM files f LEFT JOIN solutions s ON f.id=s.id WHERE active=1'):
        m=json.loads(meta)
        if not m.get('error'):
            local_time_from_header(m)
            capture_version_from_saved_header(m)
            identify_device(m,path,rules)
        m.update(id=key,path=path,root=root,status=status or 'pending',solution=json.loads(payload) if payload else None); rows.append(m)
        if any(x.lower()=='bad' for x in Path(path).parts): m['review_reason']='原目录 bad 子目录；需人工复核，未推断具体质量原因'
    c.close()
    acquisitions={}
    for r in sorted(rows,key=lambda r:r['path'].lower()):
        if r.get('version')=='raw':
            k=r['acquisition']
            if k in acquisitions: r['duplicate_of']=acquisitions[k]
            else: acquisitions[k]=r['id']
    return rows

def batches(rows):
    buckets=collections.defaultdict(list)
    for r in rows:
        if r.get('type')!='Light' or r.get('error'): continue
        key=(r['device'],observing_night(r),r.get('target'),r.get('parent'),tuple(r['binning']),r['width'],r['height'],r['version'],r.get('pier'),r.get('planned_rotation'))
        buckets[key].append(r)
    result=[]
    for key,rr in sorted(buckets.items(),key=lambda x:str(x[0])):
        rr.sort(key=lambda r:(r.get('date') or '',r['path']))
        part=[]
        for r in rr:
            split=False
            if part:
                a,b=part[0].get('pointing'),r.get('pointing')
                split=bool(a and b and distance(a,b)>.08)
                try:
                    split |= (datetime.fromisoformat(r['date'])-datetime.fromisoformat(part[-1]['date'])).total_seconds()>7200
                except (TypeError,ValueError): pass
            if split: result.append(part); part=[]
            part.append(r)
        if part: result.append(part)
    return result

def quality_preview(p,r):
    # Read sparse pixels to keep memory bounded; quality is a screening flag, not a diagnosis.
    with fits.open(p,mode='readonly',memmap=True,do_not_scale_image_data=True) as hdus:
        hdu=hdus[r.get('hdu',0)]
        step=max(1,max(r['width'],r['height'])//1400)
        a=np.array(hdu.data[::step,::step],dtype=float)*float(hdu.header.get('BSCALE',1))+float(hdu.header.get('BZERO',0))
    good=np.isfinite(a); frac=float(good.mean())
    if frac<.99: raise ValueError('疑似损坏：有效像素不足99%')
    med=float(np.nanmedian(a)); mad=float(np.nanmedian(np.abs(a-med)))*1.4826
    low,high=np.nanpercentile(a,[1,99.8])
    if high<=low or mad==0: raise ValueError('待复核：图像近乎常量/无有效动态范围')
    peaks=(a==maximum_filter(a,size=5)) & (a>med+8*mad)
    count=int(peaks[3:-3,3:-3].sum())
    im=np.arcsinh(np.clip((a-low)/(high-low),0,1)*12)/np.arcsinh(12)
    Image.fromarray((np.nan_to_num(im)*255).astype('uint8')).save(DATA/'previews'/f"{r['id']}.jpg")
    return dict(valid_fraction=frac,median=med,robust_sigma=mad,bright_peaks=count,suspicious=count<8,reason='稀疏亮点不足；不诊断未开顶/云/失焦' if count<8 else None)

def solve(r,timeout=90,retry=False):
    if r['status']!='pending' and not retry: return r
    dest=DATA/'solutions'/r['id']; dest.mkdir(exist_ok=True)
    local=dest/'input.fits'; payload={}; status='failed'; begin=time.monotonic()
    try:
        if any(x.lower()=='bad' for x in Path(r['path']).parts): raise ValueError('位于原目录 bad 子目录，保留为人工待复核，不据此判断具体原因')
        # ASTAP never receives a source path; side effects stay in this project.
        shutil.copyfile(r['path'],local)
        payload['quality']=quality_preview(local,r)
        if payload['quality']['suspicious']: raise ValueError('待复核：亮点筛查未通过')
        h=fits.Header.fromstring(r['header'],sep='\n')
        if r.get('existing_wcs'):
            geom=r['existing_wcs']; payload['source']='validated_header_wcs'
            h.tofile(dest/'header-wcs.fits',overwrite=True)
        else:
            cmd=settings.solver_command(local,dest/'solution',r.get('pointing'))
            if r.get('pointing'): cmd += ['-ra',str(r['pointing'][0]/15),'-spd',str(r['pointing'][1]+90)]
            pix=num(h.get('YPIXSZ')); focal=r.get('focal'); biny=num(h.get('YBINNING'))
            if pix and focal and biny: cmd += ['-fov',str(math.degrees(2*math.atan(r['height']*pix*biny/1000/(2*focal))))]
            else: cmd += ['-fov','0']
            payload['command']=cmd
            for suffix in ('ini','wcs'):
                previous=dest/f'solution.{suffix}'
                if previous.exists(): previous.unlink()
            result=subprocess.run(cmd,cwd=dest,capture_output=True,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            log=result.stdout.decode('utf8',errors='replace')+result.stderr.decode('utf8',errors='replace')
            (dest/'run.log').write_text(log,encoding='utf8'); payload['returncode']=result.returncode
            ini=dest/'solution.ini'; wcs=dest/'solution.wcs'
            if result.returncode or not ini.exists() or 'PLTSOLVD=T' not in ini.read_text(errors='replace') or not wcs.exists(): raise ValueError('ASTAP 未获得解；参见本地 run.log，不推断天气或开顶状态')
            h=fits.getheader(wcs); geom=geometry(h,r['width'],r['height']); payload['source']='ASTAP'
        payload.update(geom); payload['wcs_header']=h.tostring(sep='\n',padding=False); status='solved'
    except subprocess.TimeoutExpired: status='timeout'; payload['error']=f'解析超时（{timeout}秒），可重试'
    except Exception as e: payload['error']=str(e)
    finally:
        if local.exists(): local.unlink() # Only our copy under data/solutions.
    payload['elapsed_seconds']=round(time.monotonic()-begin,3)
    c=connect(); c.execute('INSERT OR REPLACE INTO solutions VALUES (?,?,?)',(r['id'],status,dumps(payload))); c.commit(); c.close()
    r.update(status=status,solution=payload)
    print(dumps(dict(id=r['id'],target=r.get('target'),date=r.get('date'),status=status,seconds=payload['elapsed_seconds'],error=payload.get('error'))),flush=True)
    return r

def same(a,b):
    if a['status']!='solved' or b['status']!='solved': return False
    x,y=a['solution'],b['solution']
    return distance(x['center'],y['center'])<.025 and abs((x['rotation']-y['rotation']+180)%360-180)<1 and max(abs(np.array(x['scale'])/np.array(y['scale'])-1))<.015

def partition(rr,do_solve=False,timeout=90):
    indexes=sorted(set([0,len(rr)//2,len(rr)-1]))
    if do_solve:
        for i in indexes: solve(rr[i],timeout)
    samples=[rr[i] for i in indexes]
    if all(x['status']=='solved' for x in samples) and all(same(samples[0],x) for x in samples):
        # All available solutions must also agree, including a resumed finer scan.
        if all(same(samples[0],x) for x in rr if x['status']=='solved'): return [(rr,True)]
    if len(rr)>3 and sum(x['status']=='solved' for x in samples)>=2 and any(not same(a,b) for a in samples for b in samples if a['status']==b['status']=='solved'):
        mid=len(rr)//2
        return partition(rr[:mid],do_solve,timeout)+partition(rr[mid:],do_solve,timeout)
    # Failed samples never establish coverage for untested neighbours.
    solved=[r for r in rr if r['status']=='solved']; rest=[r for r in rr if r['status']!='solved']
    groups=[]
    for r in solved:
        for g,_ in groups:
            if same(g[0],r): g.append(r); break
        else: groups.append(([r],False))
    if rest: groups.append((rest,False))
    return groups

def sample(limit=8,timeout=90):
    bs=[b for b in batches(records()) if not any(x.lower()=='bad' for x in Path(b[0]['path']).parts)]; chosen=[]; seen=set()
    # Choose distinct object / commanded rotation / device before filling repeats.
    for rr in sorted(bs,key=lambda g:(-len(g),g[0]['id'])):
        signature=(rr[0]['device'],rr[0].get('target'),rr[0].get('planned_rotation'))
        if signature not in seen: chosen.append(rr); seen.add(signature)
    chosen += [g for g in bs if g not in chosen]
    for rr in chosen[:limit]: partition(rr,True,timeout)
    print(dumps({'selected_batches':min(limit,len(bs)),'available_batches':len(bs)}))

def sample_roots(per_root=0,timeout=90,roots=None,progress=None):
    from roots import get_roots
    all_batches=batches(records())
    results=[]
    for root in (get_roots() if roots is None else roots):
        choices=[b for b in all_batches if b[0]['root'].lower()==root.lower() and b[0]['version'] in ('raw','unknown') and not any(x.lower()=='bad' for x in Path(b[0]['path']).parts)]
        choices.sort(key=lambda b:(-len(b),b[0]['id']))
        # 0 explicitly means all batches, including repeated sessions of one target.
        picked=choices if per_root == 0 else choices[:per_root]
        for i,b in enumerate(picked,1):
            if progress: progress(root,i-1,len(picked))
            partition(b,True,timeout)
            if progress: progress(root,i,len(picked))
        results.append(dict(root=root,chosen=[dict(device=b[0]['device'],target=b[0]['target'],count=len(b)) for b in picked],available=len(choices)))
        print(dumps(results[-1]),flush=True)
    (DATA/'sample-roots.json').write_text(dumps(results),encoding='utf8')

def sample_target(name,timeout=90,progress=None):
    key=target_key(name)
    if not key: raise ValueError('目标名不能为空')
    bs=[b for b in batches(records()) if target_key(b[0].get('target'))==key and b[0]['version'] in ('raw','unknown') and not any(x.casefold()=='bad' for x in Path(b[0]['path']).parts)]
    print(dumps({'target':name,'batches':len(bs),'files':sum(len(b) for b in bs)}),flush=True)
    for i,b in enumerate(bs,1):
        partition(b,True,timeout)
        if progress: progress(i,len(bs))
    return len(bs)

def sample_missing_targets(limit=5,timeout=60):
    """First-pass one representative Light batch per as-yet-unmapped FITS target."""
    rows=records(); listed=target_summaries(rows,groups(rows))
    by_key=collections.defaultdict(list)
    for batch in batches(rows):
        indexes={0,len(batch)//2,len(batch)-1}
        if (batch[0]['version'] in ('raw','unknown') and not any(x.casefold()=='bad' for x in Path(batch[0]['path']).parts)
                and any(batch[i]['status']=='pending' for i in indexes)):
            by_key[target_key(batch[0].get('target'))].append(batch)
    selected=[t for t in listed if not t['mapped_groups'] and by_key.get(t['key'])][:max(0,limit)]
    result=[]
    for i,t in enumerate(selected,1):
        choice=max(by_key[t['key']],key=lambda b:(len(b),sum(x['status']=='pending' for x in b)))
        partition(choice,True,timeout)
        entry=dict(index=i,total=len(selected),target=t['target'],batch_frames=len(choice),
                   solved=sum(r['status']=='solved' for r in choice),failed=sum(r['status'] in ('failed','timeout') for r in choice))
        result.append(entry)
        (DATA/'sample-missing-targets.json').write_text(dumps(result),encoding='utf8')
        print(dumps(entry),flush=True)
    return result

def tangent(points,center):
    p=np.radians(np.array(points)); ra,dec=np.radians(center)
    d=p[:,0]-ra; den=np.sin(dec)*np.sin(p[:,1])+np.cos(dec)*np.cos(p[:,1])*np.cos(d)
    if np.any(den<=0): return None
    return np.column_stack((np.cos(p[:,1])*np.sin(d)/den,(np.cos(dec)*np.sin(p[:,1])-np.sin(dec)*np.cos(p[:,1])*np.cos(d))/den))
def inside2(p,poly):
    x,y=p; inside=False
    for a,b in zip(poly,np.roll(poly,-1,axis=0)):
        cross=(b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0])
        if abs(cross)<1e-12 and min(a[0],b[0])-1e-12<=x<=max(a[0],b[0])+1e-12 and min(a[1],b[1])-1e-12<=y<=max(a[1],b[1])+1e-12: return True
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]: inside=not inside
    return inside
def contains(geom,point):
    # Exact inverse WCS test, including SIP, avoids RA wrap and rectangle approximations.
    try:
        w=WCS(fits.Header.fromstring(geom['wcs_header'],sep='\n')).celestial
        x,y=w.all_world2pix([point],0)[0]
        return bool(-.5<=x<=geom['pixel_width']-.5 and -.5<=y<=geom['pixel_height']-.5)
    except Exception: return False
def intersects(a,b):
    if distance(a['center'],b['center'])>max(distance(a['center'],p) for p in a['corners'])+max(distance(b['center'],p) for p in b['corners']): return False
    p,q=tangent(a['polygon'],a['center']),tangent(b['polygon'],a['center'])
    if p is None or q is None: return False
    if inside2(p[0],q) or inside2(q[0],p): return True
    def cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    for x,y in zip(p,np.roll(p,-1,axis=0)):
        for z,t in zip(q,np.roll(q,-1,axis=0)):
            if max(x[0],y[0])<min(z[0],t[0]) or max(z[0],t[0])<min(x[0],y[0]) or max(x[1],y[1])<min(z[1],t[1]) or max(z[1],t[1])<min(x[1],y[1]): continue
            if cross(x,y,z)*cross(x,y,t)<=0 and cross(z,t,x)*cross(z,t,y)<=0: return True
    return False

def groups(rows=None):
    rows=records() if rows is None else rows
    gs=[]
    for batch in batches(rows):
        for rr,stable in partition(batch):
            solved=[r for r in rr if r['status']=='solved']; rep=solved[len(solved)//2] if solved else rr[0]
            local_dates=sorted(r['date_local'] for r in rr if r.get('date_local'))
            utc_dates=sorted(r['date'] for r in rr if r.get('date'))
            g=dict(id=ident([r['id'] for r in rr]),device=rep['device'],target=rep.get('target') or '未知',date=rep.get('date'),date_local=rep.get('date_local'),
                   local_start=local_dates[0] if local_dates else None,local_end=local_dates[-1] if local_dates else None,
                   utc_start=utc_dates[0] if utc_dates else None,utc_end=utc_dates[-1] if utc_dates else None,
                   observing_night=observing_night(rep),time_basis=rep.get('time_basis'),version=rep['version'],pointing=rep.get('pointing'),planned_rotation=rep.get('planned_rotation'),
                   telescope_header=rep.get('telescope'),telescope_display=rep.get('telescope_display'),telescope_source=rep.get('telescope_source'),
                   count=len(rr),confirmed=len(solved),estimated=sum(r['status']=='pending' for r in rr) if stable else 0,
                   pending=sum(r['status']!='solved' for r in rr) if not stable else sum(r['status'] not in ('pending','solved') for r in rr),
                   evidence='抽样估算' if stable and any(r['status']=='pending' for r in rr) else ('已解析代表帧' if solved else '待确认'),
                   sample_ids=[r['id'] for r in solved],representative=rep['id'],files=[],exposures={},geometry=None)
            if solved: g['geometry']={**rep['solution'],'pixel_width':rep['width'],'pixel_height':rep['height']}
            seen=set()
            for r in rr:
                duplicate=bool(r.get('duplicate_of')) or r['acquisition'] in seen; seen.add(r['acquisition'])
                ev='已解析代表帧' if r['status']=='solved' else ('抽样估算' if stable and r['status']=='pending' else '待确认')
                g['files'].append({k:r.get(k) for k in ['id','path','date','date_local','time_basis','filter','exposure','status','version','width','height','binning','pointing']} | dict(evidence=ev,possible_duplicate=duplicate,error=(r.get('solution') or {}).get('error')))
                f=r.get('filter') or '未知'; e=g['exposures'].setdefault(f,dict(recorded=0,confirmed=0,estimated=0,unknown_exposure=0,excluded_versions=0,possible_duplicates=0))
                if duplicate: e['possible_duplicates']+=1; continue
                if r['version']!='raw': e['excluded_versions']+=1; continue
                exp=r.get('exposure')
                if exp is None: e['unknown_exposure']+=1; continue
                e['recorded']+=exp
                if ev=='已解析代表帧': e['confirmed']+=exp
                elif ev=='抽样估算': e['estimated']+=exp
            gs.append(g)
    return gs

def target_summaries(rows=None,group_rows=None):
    """All Light targets, including unparsed ones; exposure is unique raw acquisition time."""
    rows=records() if rows is None else rows
    group_rows=groups(rows) if group_rows is None else group_rows
    by_target={}
    def system_label(r):return r.get('device') or Path(r.get('root') or '').name
    for r in rows:
        if r.get('type')!='Light': continue
        key=target_key(r.get('target'))
        if not key: key='未知'
        t=by_target.setdefault(key,dict(key=key,names=collections.Counter(),files=0,raw_files=0,raw_seconds=0,
                                        excluded_version_files=0,duplicate_files=0,missing_exposure_files=0,
                                        groups=0,mapped_groups=0,confirmed_frames=0,estimated_frames=0,pending_frames=0,systems={}))
        t['names'][r.get('target') or '未知']+=1; t['files']+=1
        if r.get('duplicate_of'):
            t['duplicate_files']+=1; continue
        if r.get('version')!='raw':
            t['excluded_version_files']+=1; continue
        t['raw_files']+=1
        exp=r.get('exposure')
        if exp is None:
            t['missing_exposure_files']+=1; continue
        t['raw_seconds']+=exp
        label=system_label(r)
        s=t['systems'].setdefault(label,dict(device=label,raw_seconds=0,raw_files=0,filters={}))
        s['raw_seconds']+=exp; s['raw_files']+=1
        f=r.get('filter') or '未知'; fe=s['filters'].setdefault(f,dict(seconds=0,files=0))
        fe['seconds']+=exp;fe['files']+=1
    for g in group_rows:
        key=target_key(g['target']) or '未知'
        if key not in by_target:continue
        t=by_target[key];t['groups']+=1;t['mapped_groups']+=bool(g.get('geometry'))
        t['confirmed_frames']+=g['confirmed'];t['estimated_frames']+=g['estimated'];t['pending_frames']+=g['pending']
    output=[]
    for t in by_target.values():
        t['target']=t.pop('names').most_common(1)[0][0]
        t['systems']=sorted(t['systems'].values(),key=lambda s:-s['raw_seconds'])
        output.append(t)
    return sorted(output,key=lambda t:(-t['raw_seconds'],t['target'].casefold()))

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('scan'); s.add_argument('root')
    s=sub.add_parser('sample'); s.add_argument('--groups',type=int,default=8); s.add_argument('--timeout',type=int,default=90)
    s=sub.add_parser('sample-roots'); s.add_argument('--per-root',type=int,default=0); s.add_argument('--timeout',type=int,default=90)
    s=sub.add_parser('sample-missing-targets'); s.add_argument('--limit',type=int,default=5); s.add_argument('--timeout',type=int,default=60)
    s=sub.add_parser('sample-target'); s.add_argument('name'); s.add_argument('--timeout',type=int,default=90)
    s=sub.add_parser('solve'); s.add_argument('id'); s.add_argument('--retry',action='store_true'); s.add_argument('--timeout',type=int,default=90)
    sub.add_parser('report')
    a=p.parse_args()
    if a.action=='scan': scan(a.root)
    elif a.action=='sample': sample(a.groups,a.timeout)
    elif a.action=='sample-roots': sample_roots(a.per_root,a.timeout)
    elif a.action=='sample-missing-targets': sample_missing_targets(a.limit,a.timeout)
    elif a.action=='sample-target': sample_target(a.name,a.timeout)
    elif a.action=='solve': solve(next(r for r in records() if r['id']==a.id),a.timeout,a.retry)
    else:
        rr=records(); gs=groups(rr)
        report=dict(files=len(rr),status=dict(collections.Counter(r['status'] for r in rr)),types=dict(collections.Counter(r.get('type') for r in rr)),versions=dict(collections.Counter(r.get('version') for r in rr)),batches=len(batches(rr)),groups=len(gs),evidence=dict(collections.Counter(g['evidence'] for g in gs)),estimated_frames=sum(g['estimated'] for g in gs),confirmed_frames=sum(g['confirmed'] for g in gs),pending_frames=sum(g['pending'] for g in gs))
        (DATA/'report.json').write_text(dumps(report),encoding='utf8'); print(dumps(report))
if __name__=='__main__': main()
