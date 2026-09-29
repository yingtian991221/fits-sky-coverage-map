"""Fetch five compact CDS/VizieR object lists beside this project for local sky labels.

This never reads or uploads FITS. Run explicitly to refresh the cached lists.
"""
import collections, json, re, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
from astropy.coordinates import SkyCoord
import astropy.units as u

BASE=Path(__file__).resolve().parent
DATA=BASE/'data'
RAW=DATA/'catalog_sources'
RAW.mkdir(parents=True,exist_ok=True)
SPECS={
    'ngc':('VII/118/ngc2000','Name,_RA.icrs,_DE.icrs'),
    'messier_names':('VII/118/names','Object,Name'),
    'abell_north':('VII/110A/table3','ACO,_RA.icrs,_DE.icrs'),
    'abell_south':('VII/110A/table4','ACO,_RA.icrs,_DE.icrs'),
    'ldn':('VII/7A/ldn','LDN,_RA.icrs,_DE.icrs'),
    'lbn':('VII/9/catalog','Seq,_RA.icrs,_DE.icrs'),
}
def fetch(name,source,fields):
    url='https://cdsarc.cds.unistra.fr/viz-bin/asu-tsv?'+urllib.parse.urlencode({'-source':source,'-out':fields,'-out.max':'unlimited'})
    saved=RAW/(name+'.tsv')
    try:
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url,timeout=90) as response: data=response.read(15_000_000)
                if len(data)>=15_000_000: raise ValueError('目录响应超过 15 MB')
                content=data.decode('utf8')
                if '#INFO\tError=' in content: raise ValueError('VizieR 目录返回错误')
                saved.write_text(content,encoding='utf8')
                break
            except Exception:
                if attempt==2: raise
                time.sleep(2*(attempt+1))
    except Exception:
        if not saved.exists(): raise
        content=saved.read_text(encoding='utf8')
    lines=[line for line in content.splitlines() if line and not line.startswith('#')]
    if len(lines)<4: raise ValueError(f'{name} 没有数据行')
    columns=lines[0].split('\t')
    rows=[]
    for line in lines[3:]:
        fields=line.split('\t')
        if len(fields)!=len(columns): continue
        rows.append(dict(zip(columns,[x.strip() for x in fields])))
    return url,rows
def position(row):
    try:
        if '_RAJ2000' in row:
            ra=float(row['_RAJ2000']);dec=float(row['_DEJ2000'])
        else:
            sky=SkyCoord(row['_RA.icrs'],row['_DE.icrs'],unit=(u.hourangle,u.deg))
            ra=sky.ra.degree;dec=sky.dec.degree
        return (ra,dec) if 0<=ra<360 and -90<=dec<=90 else None
    except (KeyError,ValueError,TypeError):return None
def sesame(name):
    url='https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?'+urllib.parse.quote(name)
    with urllib.request.urlopen(url,timeout=20) as response: xml=ET.fromstring(response.read(500_000))
    ra=xml.find('.//jradeg');dec=xml.find('.//jdedeg')
    if ra is None or dec is None: raise ValueError('Sesame 无坐标：'+name)
    return float(ra.text),float(dec.text)
def build():
    responses={};provenance={}
    for key,(source,fields) in SPECS.items():
        url,rows=fetch(key,source,fields)
        responses[key]=rows;provenance[key]={'catalog':source,'url':url,'rows':len(rows)}
        print(key,len(rows),flush=True)
    result=[];seen=set();ngc_positions={}
    def add(category,name,point,source):
        if point is None or (category,name) in seen:return
        seen.add((category,name))
        result.append(dict(category=category,name=name,ra=round(point[0],6),dec=round(point[1],6),source=source))
    for row in responses['ngc']:
        name=row['Name'].strip();point=position(row)
        if point:ngc_positions[name]=point
        if name.isdigit(): add('NGC','NGC '+str(int(name)),point,'VII/118/ngc2000')
    missing=[]
    for row in responses['messier_names']:
        match=re.fullmatch(r'M\s*(\d+)',row['Object'].strip(),re.I)
        if not match:continue
        number=int(match.group(1));name='M '+str(number)
        point=ngc_positions.get(row['Name'].strip())
        if point:add('Messier',name,point,'VII/118/names + ngc2000')
        else:missing.append(name)
    for name in sorted(set(missing),key=lambda x:int(x.split()[1])):
        try:add('Messier',name,sesame(name),'CDS Sesame')
        except Exception as e:print('unresolved',name,str(e),flush=True)
    for key in ('abell_north','abell_south'):
        for row in responses[key]:
            if row['ACO'].isdigit():add('Abell','Abell '+str(int(row['ACO'])),position(row),provenance[key]['catalog'])
    for row in responses['ldn']:
        if row['LDN'].isdigit():add('LDN','LDN '+str(int(row['LDN'])),position(row),'VII/7A/ldn')
    for row in responses['lbn']:
        if row['Seq'].isdigit():add('LBN','LBN '+str(int(row['Seq'])),position(row),'VII/9/catalog')
    counts=dict(collections.Counter(x['category'] for x in result))
    if counts.get('NGC',0)<7000 or counts.get('Messier',0)<100 or counts.get('Abell',0)<3900 or counts.get('LDN',0)<1700 or counts.get('LBN',0)<1000:
        raise ValueError('星表数量不足，拒绝覆盖旧索引：'+str(counts))
    (DATA/'catalogs.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    (DATA/'catalog-manifest.json').write_text(json.dumps({'sources':provenance,'counts':counts,'unresolved_messier':[x for x in missing if ('Messier',x) not in seen]},ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(counts,ensure_ascii=False),flush=True)
if __name__=='__main__':build()
