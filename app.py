import collections, json, math, re, threading, urllib.parse, urllib.request, uuid, xml.etree.ElementTree as ET
from flask import Flask, jsonify, request, send_from_directory
from astropy.coordinates import SkyCoord
import astropy.units as u
import archive as ar
import catalogs
import settings
import roots as source_roots
app=Flask(__name__,static_folder=str(ar.BASE/'static'))
app.json.ensure_ascii=False
cache={}; lock=threading.Lock()
jobs={}; job_lock=threading.Lock()
scan_job=None
def snapshot():
    stamp=tuple((p.stat().st_mtime_ns,p.stat().st_size) if p.exists() else None for p in [ar.DB,ar.Path(str(ar.DB)+'-wal'),settings.FILE])
    with lock:
        if cache.get('stamp')!=stamp:
            rows=ar.records(); gg=ar.groups(rows); cache.update(stamp=stamp,rows=rows,groups=gg,targets=ar.target_summaries(rows,gg))
        return cache['rows'],cache['groups']
def filtered():
    rows,gg=snapshot(); result=[]
    for g in gg:
        if request.args.get('device') and g['device']!=request.args['device']: continue
        if request.args.get('filter') and request.args['filter'] not in g['exposures']: continue
        first=(g.get('local_start') or g.get('utc_start') or '')[:10]
        last=(g.get('local_end') or g.get('utc_end') or '')[:10]
        if request.args.get('from') and (not last or last<request.args['from']): continue
        if request.args.get('to') and (not first or first>request.args['to']): continue
        if request.args.get('evidence') and g['evidence']!=request.args['evidence']: continue
        result.append(g)
    return result
def brief(g):
    d={k:v for k,v in g.items() if k not in ('files','geometry')}
    d['geometry']={k:v for k,v in g['geometry'].items() if k not in ('wcs_header','command','quality')} if g['geometry'] else None
    return d
@app.get('/')
def index(): return send_from_directory(app.static_folder,'index.html')
@app.get('/api/health')
def health(): return jsonify(ready=True)
@app.get('/api/settings')
def get_settings():
    return jsonify(settings=settings.load(),solver=settings.solver_info(),catalog_cached=catalogs.FILE.exists())

@app.post('/api/settings')
def update_settings():
    if request.mimetype!='application/json': return jsonify(error='需要 JSON 请求'),415
    with job_lock:
        if (scan_job and scan_job['state']=='running') or any(j['state']=='running' for j in jobs.values()):
            return jsonify(error='请等待扫描/解析完成后修改设置'),409
        try: settings.save(request.get_json(silent=True))
        except (ValueError,OSError,TypeError) as exc: return jsonify(error=str(exc)),400
    return get_settings()

@app.get('/api/roots')
def list_roots():
    return jsonify(roots=[dict(path=p,available=ar.Path(p).is_dir()) for p in source_roots.get_roots()])

@app.post('/api/roots')
def add_root():
    if request.mimetype!='application/json': return jsonify(error='需要 JSON 请求'),415
    try:
        path=(request.get_json(silent=True) or {}).get('path')
        source_roots.add_root(path)
    except (ValueError,OSError) as e: return jsonify(error=str(e)),400
    return list_roots()

@app.delete('/api/roots')
def remove_root():
    if request.mimetype!='application/json': return jsonify(error='需要 JSON 请求'),415
    path=(request.get_json(silent=True) or {}).get('path')
    with job_lock:
        if scan_job and scan_job['state']=='running': return jsonify(error='扫描运行中，请完成后再移除目录'),409
    source_roots.remove_root(path)
    return list_roots()

@app.get('/api/scan')
def scan_status():
    with job_lock: current=dict(scan_job) if scan_job else None
    return jsonify(job=current)

@app.post('/api/scan')
def start_scan():
    global scan_job
    if request.mimetype!='application/json': return jsonify(error='需要 JSON 请求'),415
    body=request.get_json(silent=True) or {}
    configured=source_roots.get_roots()
    selected=body.get('roots',configured)
    if not isinstance(selected,list) or not selected or any(not isinstance(p,str) or p not in configured for p in selected):
        return jsonify(error='请先添加要扫描的目录'),400
    selected=list(dict.fromkeys(selected))
    per_root=body.get('per_root',0)
    if isinstance(per_root,bool) or not isinstance(per_root,int) or not 0<=per_root<=10000: return jsonify(error='批次数上限必须为 0–10000'),400
    sample=body.get('sample',True)
    if not isinstance(sample,bool): return jsonify(error='sample 必须为布尔值'),400
    with job_lock:
        if scan_job and scan_job['state']=='running': return jsonify(error='扫描已在运行'),409
        if any(j['state']=='running' for j in jobs.values()): return jsonify(error='代表帧解析运行中，请稍后扫描'),409
        scan_job=dict(id=uuid.uuid4().hex[:12],state='running',phase='扫描 FITS 头',current='',done=0,total=len(selected),results=[],error=None)
        current=scan_job
    def work():
        for i,root in enumerate(selected,1):
            with job_lock: current.update(current=root,phase='扫描 FITS 头')
            try: result=dict(root=root,ok=True,stats=ar.scan(root))
            except Exception as e: result=dict(root=root,ok=False,error=str(e))
            with job_lock: current['results'].append(result);current['done']=i
        if sample and settings.solver_info()['executable_found']:
            with job_lock: current.update(phase='解析每目录的代表批次',current='ASTAP')
            try:
                def progress(root,done,total):
                    with job_lock: current.update(current=root,phase=f'代表批次 {done}/{total}')
                ar.sample_roots(per_root=per_root,timeout=settings.load()['solver']['timeout'],roots=[r['root'] for r in current['results'] if r['ok']],progress=progress)
            except Exception as e:
                with job_lock: current['error']='代表帧解析失败：'+str(e)
        elif sample:
            with job_lock: current['error']='没有找到 ASTAP；头信息已整理，实际边界仍待解析。'
        with job_lock: current.update(state='complete',phase='完成',current='')
    threading.Thread(target=work,daemon=True,name='scan-'+current['id']).start()
    return jsonify(job=dict(current)),202
@app.get('/api/summary')
def summary():
    rr,gg=snapshot()
    return jsonify(files=len(rr),devices=sorted({r['device'] for r in rr if 'device' in r}),filters=sorted({r.get('filter') or '未知' for r in rr}),
                   states=dict(collections.Counter(r['status'] for r in rr)),types=dict(collections.Counter(r.get('type') for r in rr)),
                   confirmed=sum(g['confirmed'] for g in gg),estimated=sum(g['estimated'] for g in gg),pending=sum(g['pending'] for g in gg),groups=len(gg),
                   targets=len(cache['targets']),mapped_targets=sum(t['mapped_groups']>0 for t in cache['targets']))
@app.get('/api/groups')
def group_list(): return jsonify([brief(g) for g in filtered()])
@app.get('/api/targets')
def target_list():
    snapshot()
    q=request.args.get('q','').strip().casefold()
    result=[t for t in cache['targets'] if not q or q in t['target'].casefold() or q in t['key']]
    return jsonify(result)
@app.get('/api/catalog')
def catalog_labels():
    try:
        ra=float(request.args.get('ra','nan'));dec=float(request.args.get('dec','nan'));fov=float(request.args.get('fov','nan'))
        selected=tuple(x for x in request.args.get('types',','.join(catalogs.CATEGORIES)).split(',') if x in catalogs.CATEGORIES)
        rows=catalogs.nearby(ra,dec,fov,request.args.get('mode','auto'),selected)
    except ValueError as e:return jsonify(error=str(e)),400
    return jsonify(rows=rows,count=len(rows),note='目录中心点标注；不是目标形状或拍摄覆盖边界。')
@app.get('/api/target')
def target_records():
    q=request.args.get('q','').strip()
    if not q or len(q)>200: return jsonify(error='请输入目标名'),400
    key=ar.target_key(q)
    all_matches=[g for g in snapshot()[1] if ar.target_key(g['target'])==key]
    visible=[g for g in filtered() if ar.target_key(g['target'])==key]
    sample_needed=sum(g['geometry'] is None and any(f['status']=='pending' and f['version'] in ('raw','unknown') and 'bad' not in [p.casefold() for p in ar.Path(f['path']).parts] for f in g['files']) for g in all_matches)
    snapshot()
    item=next((t for t in cache['targets'] if t['key']==key),None)
    suggestions=[] if item else [dict(target=t['target'],files=t['files'],raw_seconds=t['raw_seconds']) for t in cache['targets'] if key and key in t['key']][:12]
    return jsonify(query=q,total_groups=len(all_matches),total_files=sum(g['count'] for g in all_matches),
                   solved_groups=sum(bool(g['geometry']) for g in all_matches),sample_needed=sample_needed,visible_groups=[brief(g) for g in visible],summary=item,suggestions=suggestions,
                   note='FITS OBJECT 名称匹配只证明本机索引有照片；FITS 指向与计划角度不是有效 WCS。')
@app.post('/api/solve-target')
def solve_target_job():
    if request.mimetype!='application/json': return jsonify(error='需要 JSON 请求'),415
    name=str((request.get_json(silent=True) or {}).get('target') or '').strip()
    if not name or len(name)>200: return jsonify(error='请输入索引中的目标名'),400
    matches=[g for g in snapshot()[1] if ar.target_key(g['target'])==ar.target_key(name)]
    if not matches: return jsonify(error='本地索引中没有这个目标'),404
    if not any(g['geometry'] is None and any(f['status']=='pending' and f['version'] in ('raw','unknown') and 'bad' not in [p.casefold() for p in ar.Path(f['path']).parts] for f in g['files']) for g in matches):
        return jsonify(error='这个目标没有可继续抽样的待确认原始批次'),409
    with job_lock:
        if scan_job and scan_job['state']=='running': return jsonify(error='目录扫描正在运行'),409
        if any(j['state']=='running' for j in jobs.values()): return jsonify(error='已有目标解析任务在运行'),409
        ident=uuid.uuid4().hex[:12]
        jobs[ident]=dict(id=ident,target=name,state='running',done=0,total=0,error=None)
    def work():
        try:
            def progress(done,total):
                with job_lock: jobs[ident].update(done=done,total=total)
            ar.sample_target(name,settings.load()['solver']['timeout'],progress)
            with job_lock: jobs[ident]['state']='complete'
        except Exception as e:
            with job_lock: jobs[ident].update(state='failed',error=str(e))
    threading.Thread(target=work,daemon=True,name='sample-'+ident).start()
    return jsonify(jobs[ident]),202
@app.get('/api/jobs/<ident>')
def job_status(ident):
    with job_lock: job=jobs.get(ident)
    return jsonify(job) if job else (jsonify(error='任务不存在；解析结果仍保存在索引中'),404)
@app.get('/api/group/<key>')
def group_detail(key):
    g=next((g for g in snapshot()[1] if g['id']==key),None)
    return (jsonify(g),200) if g else (jsonify(error='视场不存在；请刷新'),404)
@app.get('/api/query')
def query():
    try:
        p=ar.coord(request.args.get('ra'),request.args.get('dec'))
        if p is None: raise ValueError('坐标需为 RA 0–360、Dec -90–90 度')
        radius=float(request.args.get('radius','8'))
        if not math.isfinite(radius) or radius<=0 or radius>180: raise ValueError('附近半径需为 0–180 度')
    except ValueError as e: return jsonify(error=str(e)),400
    hits=[]; near=[]
    for g in filtered():
        if not g['geometry']: continue
        geom=g['geometry']; contains=ar.contains(geom,p); d=ar.distance(geom['center'],p)
        entry=dict(id=g['id'],target=g['target'],device=g['device'],distance=d,evidence=g['evidence'],representative_contains=contains)
        if contains: hits.append(entry)
        elif d<=radius: near.append(entry)
    return jsonify(point=p,contains=sorted(hits,key=lambda x:x['distance']),nearby=sorted(near,key=lambda x:x['distance']),note='仅判断查询坐标是否在代表帧内，不宣称覆盖整个目标；其他帧可能是抽样估算。')
@app.get('/api/intersections/<key>')
def intersections(key):
    gg=filtered(); g=next((x for x in gg if x['id']==key),None)
    if not g or not g['geometry']: return jsonify(error='该视场没有已确认边界'),404
    return jsonify(ids=[x['id'] for x in gg if x['id']!=key and x['geometry'] and ar.intersects(g['geometry'],x['geometry'])],note='代表帧边界几何相交候选；不代表能够合成。')
@app.get('/api/review')
def review():
    rows,gg=snapshot()
    evidence={f['id']:f['evidence'] for g in gg for f in g['files']}
    pending=sorted((r for r in rows if r['status']!='solved'),key=lambda r:(not bool(r.get('review_reason') or r.get('error') or r['status'] in ('failed','timeout')),r['path']))
    return jsonify([{k:r.get(k) for k in ['id','path','target','type','status','error']} | dict(evidence=evidence.get(r['id'],'待确认'),reason=(r.get('solution') or {}).get('error') or r.get('review_reason') or r.get('error') or ('抽样估算，尚未逐帧确认' if evidence.get(r['id'])=='抽样估算' else '尚未取得有效 WCS')) for r in pending])
@app.get('/api/resolve')
def resolve():
    q=request.args.get('q','').strip()
    if not q or len(q)>200: return jsonify(error='请输入目标名称或坐标'),400
    try:
        parts=re.split(r'[,\s]+',q)
        if len(parts)==2:
            c=ar.coord(*parts)
            if c: return jsonify(ra=c[0],dec=c[1],source='输入坐标（度）')
        if ':' in q or len(parts)==6:
            c=SkyCoord(q,unit=(u.hourangle,u.deg)); return jsonify(ra=c.ra.degree,dec=c.dec.degree,source='输入坐标（时角/度）')
        local=catalogs.find_name(q)
        if local:return jsonify(ra=local['ra'],dec=local['dec'],source='本地 CDS '+local['category']+' 目录中心',catalog=local['name'])
        # Only the name is sent online. No file paths, pixels or FITS metadata.
        url='https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?'+urllib.parse.quote(q)
        with urllib.request.urlopen(url,timeout=12) as r: xml=ET.fromstring(r.read(1_000_000))
        ra=xml.find('.//jradeg'); dec=xml.find('.//jdedeg')
        if ra is None or dec is None: raise ValueError('名称服务未找到目标')
        return jsonify(ra=float(ra.text),dec=float(dec.text),source='CDS Sesame')
    except Exception as e: return jsonify(error=f'名称/坐标解析失败：{e}。可直接输入十进制度坐标，例如 85.222 -2.433。'),400
@app.get('/previews/<key>.jpg')
def preview(key):
    if not re.fullmatch('[a-f0-9]{20}',key): return '',404
    return send_from_directory(ar.DATA/'previews',key+'.jpg')
if __name__=='__main__':
    ar.connect().close()
    app.run(host='127.0.0.1',port=8765,debug=False,threaded=True)
