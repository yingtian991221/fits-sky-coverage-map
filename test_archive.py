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

if __name__=='__main__': unittest.main(verbosity=2)
