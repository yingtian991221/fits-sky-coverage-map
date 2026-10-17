import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import disk_cache
import app

class CacheTests(unittest.TestCase):
    def test_persistent_hit_without_network_and_eviction(self):
        with tempfile.TemporaryDirectory(dir=app.ar.TMP) as temp, patch.object(disk_cache,'FILE',Path(temp)/'cache.sqlite'), patch.object(disk_cache,'LIMIT',8):
            response=MagicMock();response.read.return_value=b'12345';response.headers.get_content_type.return_value='image/jpeg'
            with patch('urllib.request.urlopen') as remote:
                remote.return_value.__enter__.return_value=response
                self.assertFalse(disk_cache.fetch('https://example.test/a')[2])
            with patch('urllib.request.urlopen',side_effect=OSError('offline')):
                self.assertEqual(disk_cache.fetch('https://example.test/a'),(b'12345','image/jpeg',True))
            with patch('urllib.request.urlopen') as remote:
                remote.return_value.__enter__.return_value=response
                disk_cache.fetch('https://example.test/b')
            self.assertEqual(disk_cache.stats()['objects'],1)
            self.assertLessEqual(disk_cache.stats()['bytes'],8)

    def test_only_fixed_survey_paths_allowed(self):
        client=app.app.test_client()
        for path in ('https://example.test','dss/../secret','dss/Norder3/Dir0/Npix1.fits'):
            self.assertEqual(client.get('/cached/'+path).status_code,404)
        with patch.object(disk_cache,'fetch',return_value=(b'tile','image/jpeg',True)) as fetch:
            r=client.get('/cached/dss/Norder3/Dir0/Npix1.jpg')
            self.assertEqual(r.status_code,200)
            self.assertEqual(r.headers['X-Disk-Cache'],'HIT')
            self.assertEqual(fetch.call_args.args[0],'https://alasky.cds.unistra.fr/DSS/DSSColor/Norder3/Dir0/Npix1.jpg')

    def test_details_do_not_send_full_fits_headers(self):
        group={'id':'demo','geometry':None,'files':[dict(path='frame.fits',header='PRIVATE HEADER'*1000,solution={'wcs_header':'WCS'})]}
        with patch.object(app,'snapshot',return_value=([],[group])):
            r=app.app.test_client().get('/api/group/demo')
        self.assertNotIn('header',r.json['files'][0])
        self.assertNotIn('solution',r.json['files'][0])
        self.assertEqual(r.json['files'][0]['path'],'frame.fits')

    def test_properties_cannot_bypass_local_cache_via_remote_mirrors(self):
        properties=b'hips_order = 9\nhips_service_url = https://remote.test\nhips_service_url_1 = https://mirror.test\n'
        with patch.object(disk_cache,'fetch',return_value=(properties,'text/plain',True)):
            response=app.app.test_client().get('/cached/dss/properties')
        self.assertNotIn(b'remote.test',response.data)
        self.assertNotIn(b'mirror.test',response.data)
        self.assertIn(b'hips_service_url = http://localhost/cached/dss',response.data)
        self.assertEqual(response.headers['Cache-Control'],'no-store')

if __name__=='__main__':unittest.main()
