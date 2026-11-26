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
        source=make_test_file([{'SCVID':'X1','Title':'Mr','Customer First Forename':'Alex','Customer Surname or Company Name':'Smith','Account Status Code':'FFSTP','Address Line 1':'1 Example Lane','Address Line 2':'London','Post Code':'E1 3DT','Account Balance in Sterling':'10.00','Aggregate Balance':'10.00','Compensatable Amount':'10.00'}])
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

    def test_speech_marks_and_aggregate_reconciliation(self):
        record = {
            'SCVID': 'X1', 'Title': 'Mr', 'Sort Code': '123456', 'Account Number': '1',
            'IBAN': 'malformed-unused', 'Account Balance in Sterling': '10.00', 'Aggregate Balance': '9.99',
        }
        source = make_test_file([record]).replace('|Mr|', '|"Mr"|')
        with patch.dict(os.environ, {'SCV_LOOKUP_TOKEN': 'unit-test-only'}), TestClient(main.app) as client:
            headers = {'Authorization': 'Bearer unit-test-only'}
            response = client.post('/api/validate', json={'source': source, 'selected': ['FFSTP_5', 'FFSTP_6D']}, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            speech_marks, aggregate = result['results'][-2:]
            self.assertEqual(speech_marks[0]['cells'][3:5], [['"Mr"'], ['Speech marks were found.']])
            self.assertEqual(len(aggregate), 1)
            self.assertEqual(aggregate[0]['cells'][2:5], [['9.99'], ['10.00'], ['0.01']])
            self.assertEqual(result['gradingAffectedRecords'][-2:], [1, 1])

            repeated = make_test_file([record, record])
            response = client.post('/api/validate', json={'source': repeated, 'selected': ['FFSTP_6D']}, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result['gradingAffectedRecords'][-1], 0)
            self.assertEqual(len(result['results'][-1]), 1)
            self.assertIn('repeated customer/account rows', result['results'][-1][0]['cells'][5][0])

if __name__=='__main__': unittest.main()
