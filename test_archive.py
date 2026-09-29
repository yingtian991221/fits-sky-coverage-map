"""Regression fixtures are isolated unit tests, never inserted into the real archive."""
import unittest, tempfile, json, sqlite3, os, time
from unittest.mock import patch
from pathlib import Path
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
import archive as a
import catalogs
from app import app
import roots as source_roots

def fixture(ra=359.9,dec=5,rotation=35):
    w=WCS(naxis=2); w.wcs.crpix=[500.5,400.5]; w.wcs.crval=[ra,dec]; w.wcs.ctype=['RA---TAN','DEC--TAN']
    t=np.radians(rotation); w.wcs.cd=np.array([[-np.cos(t),np.sin(t)],[np.sin(t),np.cos(t)]])*.003
    h=w.to_header(); g=a.geometry(h,1000,800)
    return dict(g,wcs_header=h.tostring(sep='\n',padding=False),pixel_width=1000,pixel_height=800)

class GeometryTests(unittest.TestCase):
    def test_asiair_acquisition_from_saved_fits_header(self):
        meta=dict(version='unknown',header="CREATOR = 'ZWO ASIAIR Plus' / Capture software\nIMAGETYP= 'Light   '\n")
        a.capture_version_from_saved_header(meta)
        self.assertEqual(meta['version'],'raw')
        processed=dict(version='unknown',header=meta['header']+'HISTORY calibrated\n')
        a.capture_version_from_saved_header(processed)
        self.assertEqual(processed['version'],'unknown')
    def test_date_loc_is_display_basis_without_losing_utc(self):
        meta=dict(date='2025-09-22T18:18:20.593',header="DATE-LOC= '2025-09-23T02:18:20.593' / local\n")
        a.local_time_from_header(meta)
        self.assertEqual(meta['date_local'][:10],'2025-09-23')
        self.assertEqual(meta['date'][:10],'2025-09-22')
        self.assertEqual(meta['local_offset_hours'],8)
        only=dict(date='2026-08-29T11:59:04',header='')
        a.local_time_from_header(only)
        self.assertIsNone(only['date_local'])
        self.assertEqual(only['time_basis'],'FITS DATE-OBS (UTC)')
    def test_gaoyazi_scope_identity_keeps_header_value(self):
        meta=dict(camera='ZWO ASI6200MM Pro',telescope='Newt 800',focal=728.0,date='2025-12-24',filter='L',exposure=300,width=9576,height=6388,binning=[1,1])
        a.identify_device(meta,r'X:\Example\Gaoyazi_CAM_6200MM\scope_SR130APO\done\frame.fits')
        self.assertEqual(meta['telescope'],'Newt 800')
        self.assertEqual(meta['telescope_display'],'Sky Rover 130 APO')
        self.assertIn('Sky Rover 130 APO',meta['device'])
        self.assertIn('728.0',meta['device'])
        a.identify_device(meta,r'X:\Example\Gaoyazi_CAM_6200MM\scope_sw200\done\frame.fits')
        self.assertEqual(meta['telescope_display'],'Sky-Watcher 200 Newtonian')
        self.assertEqual(meta['telescope_source'],'Gaoyazi 镜筒目录')
        a.identify_device(meta,r'X:\Example\OtherCamera\scope_SR130APO\frame.fits')
        self.assertEqual(meta['telescope_display'],'Newt 800')
        meta['focal']=674.0;meta['telescope']='iOptron CEM40/GEM45/HAE43 210101+'
        a.identify_device(meta,r'X:\Example\140PH_cam_2600MCDuo1\done\M 24\frame.fit')
        self.assertEqual(meta['telescope'],'iOptron CEM40/GEM45/HAE43 210101+')
        self.assertEqual(meta['telescope_display'],'140PH 目录')
        self.assertIn('650–799 mm',meta['device'])
    def test_target_alias(self):
        self.assertEqual(a.target_key('M45'),a.target_key('M 45'))
        self.assertEqual(a.target_key('NGC-7331'),a.target_key('NGC 7331'))
    def test_ra_wrap_and_pole(self):
        for dec in [5,88,-88]:
            g=fixture(dec=dec)
            self.assertTrue(a.contains(g,[359.9,dec])); self.assertTrue(a.contains(g,[.1,dec]))
            self.assertFalse(a.contains(g,[180,0])); self.assertLess(g['roundtrip_px'],1e-5)
    def test_intersections_rotation_and_containment(self):
        g=fixture(); near=fixture(ra=.2,rotation=-35); far=fixture(ra=30)
        self.assertTrue(a.intersects(g,near)); self.assertTrue(a.intersects(near,g)); self.assertTrue(a.intersects(g,g))
        self.assertFalse(a.intersects(g,far))
    def test_pointing_is_not_wcs(self):
        with self.assertRaises(ValueError): a.geometry(fits.Header({'RA':85,'DEC':-2}),100,100)
    @unittest.skipUnless(os.environ.get('SKY_ARCHIVE_TEST_REAL')=='1', 'requires private FITS solutions')
    def test_real_solutions_roundtrip(self):
        for r in a.records():
            if r['status']!='solved': continue
            g={**r['solution'],'pixel_width':r['width'],'pixel_height':r['height']}
            self.assertTrue(a.contains(g,g['center'])); self.assertLess(g['roundtrip_px'],.1)
            self.assertTrue(.02<g['scale'][0]<120)
    def test_adaptive_split(self):
        def r(i,ra):return dict(id=str(i),status='solved',solution=dict(center=[ra,0],rotation=10,scale=[1,1]))
        result=a.partition([r(i,10 if i<4 else 15) for i in range(8)])
        self.assertEqual([len(x) for x,_ in result],[4,4]); self.assertTrue(all(stable for _,stable in result))
    def test_failed_sample_cannot_confirm_neighbours(self):
        rr=[dict(id=str(i),status='pending',solution=None) for i in range(5)]
        rr[0].update(status='solved',solution=dict(center=[10,0],rotation=10,scale=[1,1])); rr[2]['status']='failed'
        result=a.partition(rr)
        self.assertFalse(any(stable for _,stable in result))
        self.assertEqual(sum(len(x) for x,_ in result),5)
    def test_quality_constant_and_truncated(self):
        with tempfile.TemporaryDirectory(dir=a.TMP) as d:
            p=Path(d)/'flat.fits'; fits.writeto(p,np.zeros((40,40),dtype='int16'))
            with self.assertRaises(ValueError): a.quality_preview(p,dict(id='test',width=40,height=40,hdu=0))
            p.write_bytes(p.read_bytes()[:3000])
            with self.assertRaises(ValueError): a.metadata(p)

class DirectoryWorkflowTests(unittest.TestCase):
    def test_add_scan_repeat_and_remove_without_touching_fits(self):
        with tempfile.TemporaryDirectory(dir=a.TMP) as directory:
            base=Path(directory); source=base/'source'; source.mkdir()
            frame=source/'frame.fits'
            fits.writeto(frame,np.ones((20,20),dtype='int16'),header=fits.Header({'IMAGETYP':'Light','OBJECT':'TEST-SKY','EXPTIME':120}))
            original=frame.read_bytes()
            with patch.object(source_roots,'BASE',base/'project'), patch.object(source_roots,'CONFIG',base/'roots.json'), patch.object(a,'DB',base/'test.sqlite'):
                client=app.test_client()
                self.assertEqual(client.post('/api/roots',json={'path':str(source)}).status_code,200)
                self.assertEqual(len(client.get('/api/roots').get_json()['roots']),1)
                self.assertEqual(client.post('/api/roots',json={'path':str(source)}).status_code,200)
                self.assertEqual(len(source_roots.get_roots()),1)
                self.assertEqual(client.post('/api/scan',json={'roots':[str(source)],'sample':False}).status_code,202)
                for _ in range(100):
                    job=client.get('/api/scan').get_json()['job']
                    if job['state']=='complete': break
                    time.sleep(.05)
                self.assertEqual(job['state'],'complete')
                self.assertEqual(job['results'][0]['stats']['total'],1)
                with a.connect() as connection:
                    self.assertEqual(connection.execute('SELECT count(*) FROM files').fetchone()[0],1)
                connection.close()
                repeated=a.scan(source)
                self.assertEqual(repeated['unchanged'],1)
                self.assertEqual(frame.read_bytes(),original)
                self.assertEqual(client.delete('/api/roots',json={'path':str(source)}).status_code,200)
                self.assertEqual(source_roots.get_roots(),[])

@unittest.skipUnless(os.environ.get('SKY_ARCHIVE_TEST_REAL')=='1', 'requires this installation\'s private FITS index')
class RealApiTests(unittest.TestCase):
    def setUp(self): self.client=app.test_client()
    def test_filters_queries_and_pending(self):
        gs=self.client.get('/api/groups').get_json(); confirmed=[g for g in gs if g['geometry']]
        self.assertGreaterEqual(len(confirmed),8)
        self.assertTrue(all(g['geometry'] is None for g in gs if g['evidence']=='待确认'))
        g=confirmed[0]; ra,dec=g['geometry']['center']
        hit=self.client.get(f'/api/query?ra={ra}&dec={dec}').get_json()
        self.assertIn(g['id'],[x['id'] for x in hit['contains']])
        self.assertEqual(self.client.get('/api/groups?device=nonexistent').get_json(),[])
        self.assertTrue(all('H' in x['exposures'] for x in self.client.get('/api/groups?filter=H').get_json()))
        self.assertEqual(self.client.get('/api/groups?from=2099-01-01').get_json(),[])
        self.assertEqual(self.client.get('/api/query?ra=nan&dec=0').status_code,400)
        self.assertEqual(self.client.get('/api/query?ra=361&dec=0').status_code,400)
        self.assertEqual(self.client.get('/api/resolve?q=85.2%20-2.4').get_json()['source'],'输入坐标（度）')
    def test_actual_intersection(self):
        gs=self.client.get('/api/groups').get_json()
        g=next(x for x in gs if x['target']=='m78_3' and x['geometry'])
        h=next(x for x in gs if x['target']=='IC 434' and x['geometry'])
        result=self.client.get('/api/intersections/'+g['id']).get_json()
        self.assertIn(h['id'],result['ids'])
    def test_name_failure_coordinates_independent(self):
        with patch('urllib.request.urlopen',side_effect=TimeoutError('test offline')):
            self.assertEqual(self.client.get('/api/resolve?q=M95').get_json()['source'],'本地 CDS Messier 目录中心')
            self.assertEqual(self.client.get('/api/resolve?q=unlisted-target').status_code,400)
            self.assertEqual(self.client.get('/api/resolve?q=161.58%2012.03').status_code,200)
    def test_m45_index_lookup_without_claiming_coverage(self):
        found=self.client.get('/api/target?q=M45').get_json()
        self.assertEqual(found['total_files'],161)
        self.assertEqual(found['sample_needed'],0)
        self.assertTrue(all(g['target']=='M 45' for g in found['visible_groups']))
        self.assertGreaterEqual(found['solved_groups'],1)
        g=next(g for g in found['visible_groups'] if g['geometry'])
        ra,dec=g['geometry']['center']
        hit=self.client.get(f'/api/query?ra={ra}&dec={dec}').get_json()
        self.assertIn(g['id'],[x['id'] for x in hit['contains']])
        self.assertEqual(self.client.post('/api/solve-target',json={'target':'M45'}).status_code,409)
        self.assertEqual(self.client.post('/api/solve-target',json={'target':'not-a-real-indexed-target'}).status_code,404)
    def test_local_date_filter_and_catalog_tiers(self):
        m45=self.client.get('/api/target?q=M45').get_json()['visible_groups']
        self.assertTrue(all(g['date_local'] for g in m45))
        self.assertTrue(any(g['date_local'][:10]=='2025-09-23' and g['date'][:10]=='2025-09-22' for g in m45))
        filtered=self.client.get('/api/groups?from=2025-09-23&to=2025-09-23').get_json()
        self.assertTrue(any(g['target']=='M 45' for g in filtered))
        overview=self.client.get('/api/catalog?ra=56.75&dec=24.11&fov=5&mode=overview').get_json()['rows']
        self.assertTrue(any(x['name']=='M 45' for x in overview))
        self.assertTrue(all(x['category']=='Messier' for x in overview))
        detailed=self.client.get('/api/catalog?ra=56.75&dec=24.11&fov=5&mode=detailed').get_json()['rows']
        self.assertTrue(any(x['category']=='NGC' for x in detailed))
        self.assertEqual(catalogs.nearby(56.75,24.11,5,'off'),[])
    def test_all_targets_and_cross_night_exposure(self):
        summary=self.client.get('/api/summary').get_json()
        self.assertGreaterEqual(summary['targets'],200)
        targets=self.client.get('/api/targets?q=Sh2%2096').get_json()
        target=next(t for t in targets if t['key']=='sh296')
        self.assertGreater(target['raw_seconds']/3600,70)
        self.assertGreaterEqual(target['mapped_groups'],1)
        detail=self.client.get('/api/target?q=Sh2%2096').get_json()
        self.assertEqual(detail['summary']['raw_seconds'],target['raw_seconds'])
        self.assertEqual(detail['total_files'],424)
        self.assertTrue(any(s['filters'] for s in target['systems']))
        self.assertEqual(self.client.get('/api/groups?evidence=已解析代表帧').status_code,200)

if __name__=='__main__': unittest.main(verbosity=2)
