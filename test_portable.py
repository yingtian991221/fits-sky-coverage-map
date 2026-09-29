"""Portable tests: temporary generated fixtures, no private archive or ASTAP required."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
import archive as ar
import settings
import roots
import app as web


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ar.TMP)
        self.base=Path(self.temp.name)
        self.source=self.base/'photos'; self.source.mkdir()
        self.data=self.base/'project'/'data'
        for sub in ('previews','solutions'): (self.data/sub).mkdir(parents=True)
        self.patches=[patch.object(ar,'DATA',self.data),patch.object(ar,'DB',self.data/'archive.sqlite'),
                      patch.object(settings,'FILE',self.data/'settings.json'),patch.object(roots,'BASE',self.data.parent),
                      patch.object(roots,'CONFIG',self.data/'roots.json')]
        for p in self.patches:p.start()
        web.cache.clear();web.scan_job=None
        self.client=web.app.test_client()

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        web.cache.clear();web.scan_job=None
        self.temp.cleanup()

    def test_empty_installation_and_optional_solver(self):
        self.assertEqual(self.client.get('/api/summary').json['files'],0)
        self.assertEqual(self.client.get('/api/roots').json['roots'],[])
        self.assertEqual(self.client.get('/api/settings').json['settings'],settings.DEFAULTS)
        with patch('settings.solver_info',return_value=dict(resolved_executable='astap',executable_found=True,catalog_accessible=True,catalog_dir='',database='')):
            cmd=settings.solver_command('input.fits','output',False)
        self.assertNotIn('-D',cmd); self.assertNotIn('-d',cmd)

    def test_custom_solver_and_directory_override_preserve_headers(self):
        rule={'path':str(self.source),'telescope':'My refractor'}
        config={'solver':{'database':'d80','timeout':120},'device_overrides':[rule]}
        self.assertEqual(self.client.post('/api/settings',json=config).status_code,200)
        meta=dict(camera='Camera A',telescope='Old header name',focal=500,date=None)
        ar.identify_device(meta,self.source/'frame.fits')
        self.assertEqual(meta['telescope'],'Old header name')
        self.assertEqual(meta['telescope_display'],'My refractor')
        ar.identify_device(meta,self.base/'other'/'frame.fits')
        self.assertEqual(meta['telescope_display'],'Old header name')
        self.assertEqual(settings.load()['solver']['database'],'d80')
        config['solver']['database']='d80 -bad'
        self.assertEqual(self.client.post('/api/settings',json=config).status_code,400)

    def test_overlapping_scan_roots_are_rejected(self):
        child=self.source/'night';child.mkdir()
        self.assertEqual(self.client.post('/api/roots',json={'path':str(self.source)}).status_code,200)
        self.assertEqual(self.client.post('/api/roots',json={'path':str(child)}).status_code,400)
        self.assertEqual(roots.get_roots(),[str(self.source)])

    def test_existing_wcs_without_solver_unknown_version_and_repeat(self):
        w=WCS(naxis=2);w.wcs.crpix=[64,64];w.wcs.crval=[359.98,50];w.wcs.cdelt=[-.001,.001];w.wcs.ctype=['RA---TAN','DEC--TAN']
        h=w.to_header();h['IMAGETYP']='Light';h['OBJECT']='Portable fixture';h['EXPTIME']=300
        pixels=np.random.default_rng(7).normal(100,3,(128,128)).astype('float32')
        for y in range(12,120,16):
            for x in range(12,120,16):pixels[y,x]=1000
        p=self.source/'wcs.fits';fits.writeto(p,pixels,h)
        digest=hashlib.sha256(p.read_bytes()).hexdigest()
        with patch('settings.solver_command',side_effect=AssertionError('ASTAP must not run')):
            stats=ar.scan(self.source)
        self.assertEqual(stats['header_wcs'],1)
        rows=ar.records();self.assertEqual(rows[0]['version'],'unknown')
        self.assertEqual(rows[0]['status'],'solved')
        g=ar.groups(rows)[0];self.assertTrue(ar.contains(g['geometry'],[359.98,50]))
        self.assertEqual(ar.target_summaries(rows,[g])[0]['raw_seconds'],0)
        repeat=ar.scan(self.source);self.assertEqual(repeat['unchanged'],1)
        self.assertEqual(len(ar.records()),1)
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),digest)
        self.assertEqual(self.client.get('/api/query?ra=359.98&dec=50').status_code,200)

    def test_all_batches_including_unknown_version_are_sampled(self):
        batch=[dict(root=str(self.source),path=str(self.source/'one.fits'),version='unknown',id='a',device='Camera',target=None)]
        other=[dict(batch[0],id='b',target='Other')]
        with patch.object(ar,'records',return_value=[]),patch.object(ar,'batches',return_value=[batch,other]),patch.object(ar,'partition') as solve:
            ar.sample_roots(0,90,[str(self.source)])
            self.assertEqual(solve.call_count,2)

if __name__=='__main__':unittest.main()
