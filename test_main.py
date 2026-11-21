import os
from pathlib import Path
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import main
from validation_engine import make_test_file

class OnlineTests(unittest.TestCase):
    def test_auth_and_structured_footer_error(self):
        with patch.dict(os.environ, {'SCV_LOOKUP_TOKEN':'unit-test-only'}), TestClient(main.app) as c:
            for path,body in [('/api/validate',{'source':'bad'}),('/api/lab/run',{'code':'FAILED_IMPORT','records':[]}),('/postcodes/lookup',{'postcode_keys':['E13DT']})]:
                self.assertEqual(c.post(path,json=body).status_code,401)
            headers={'Authorization':'Bearer unit-test-only'}
            r=c.post('/api/validate',json={'source':'bad'},headers=headers)
            self.assertEqual(r.status_code,400)
            self.assertEqual(r.json()['code'],'FAILED_IMPORT')
            self.assertEqual(c.post('/api/import/inspect',content=b'bad',headers=headers).json()['source'],'bad')
            self.assertEqual(c.get('/health').json()['engine'],'python')

    def test_validation_and_lab(self):
        source=make_test_file([{'SCVID':'X1','Title':'Mr','Customer First Forename':'Alex','Customer Surname or Company Name':'Smith','Account Status Code':'FFSTP','Address Line 1':'1 Example Lane','Address Line 2':'London','Post Code':'E1 3DT','Aggregate Balance':'10.00','Compensatable Amount':'10.00'}])
        with patch.dict(os.environ, {'SCV_LOOKUP_TOKEN':'unit-test-only'}), patch.object(main,'postcode_lookup',return_value={'release':'2026-11','missing':[]}), TestClient(main.app) as c:
            headers={'Authorization':'Bearer unit-test-only'}
            result=c.post('/api/validate',json={'source':source},headers=headers)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(result.json()['affected'],0)
            lab=c.post('/api/lab/run',json={'code':'FAILED_IMPORT','records':[],'file':'bad'},headers=headers)
            self.assertEqual(lab.status_code,200,lab.text)
            self.assertTrue(lab.json()['findings'])

    def test_batches_pin_release_and_deduplicate(self):
        keys=[f'A{i:06d}' for i in range(5001)]
        with patch.object(main,'lookup',side_effect=lambda batch:{'postcode_release':'2026-11','results':{k:'Not Found' for k in batch.postcode_keys}}) as lookup:
            result=main.postcode_lookup(keys+[keys[0]])
            self.assertEqual(len(result['missing']),5001)
            self.assertEqual(lookup.call_count,2)
            self.assertEqual(lookup.call_args_list[1].args[0].postcode_release,'2026-11')

if __name__=='__main__': unittest.main()
