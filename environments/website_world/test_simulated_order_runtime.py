"""Authored receipt projection controls; native/browser acceptance is separate."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from .simulated_order_runtime import public_confirmation


class ConfirmationProjectionControls(unittest.TestCase):
    def fixture(self):
        runtime=SimpleNamespace(world={'world_id':'world','quote_as_of':'2026-10-08'},public_catalogs={'shop':{'products':[
            {'name':'Actual product','canonicalProductId':'product','options':[{'key':'size','label':'Size'}],
             'variants':[{'offerId':'offer','skuId':'sku','selection':{'size':'42'}}]}]}})
        record={'retailer_id':'shop','world_id':'world','simulated':True,'status':'confirmed','order_id':'SIM1',
            'items':[{'offer_id':'offer','product_id':'product','sku_id':'sku','quantity':1}],
            'address':{'name':'Person','street':'Street','unit':'4','postcode':'12345','city':'City'},
            'delivery_instructions':'Door four','shipments':[{'delivery':{'company':'Carrier','name':'Standard',
             'type':'parcel_locker','location':{'name':'Box A','address':'Different pickup street'}},
             'arrival':{'status':'estimated','earliest_date':'2026-10-09','latest_date':'2026-10-11'},'shippingMinor':10}],
            'currency':'SEK','subtotal_minor':100,'discount_minor':0,'shipping_minor':10,'total_minor':110,
            'submission':{'private_binding':'never public'},'submission_sha256':'private-pin'}
        return runtime,record

    def test_only_receipt_display_fields_and_native_amounts_are_public(self):
        runtime,record=self.fixture();before=deepcopy(record)
        result=public_confirmation(runtime,'shop',record)
        self.assertEqual(result['totalMinor'],110);self.assertEqual(result['items'][0]['options'],'Size: 42')
        self.assertEqual(result['address']['unit'],'4')
        self.assertEqual(result['shipments'][0]['location']['address'],'Different pickup street')
        self.assertEqual(result['shipments'][0]['arrival'],'2026-10-09 to 2026-10-11')
        self.assertNotIn('submission',result);self.assertNotIn('private_binding',str(result))
        result['address']['unit']='mutated';self.assertEqual(record,before)

    def test_foreign_unconfirmed_or_wrong_native_subject_rejects(self):
        for key,value in [('retailer_id','foreign'),('world_id','foreign'),('simulated',False),('status','pending')]:
            runtime,record=self.fixture();record[key]=value
            with self.assertRaises(ValueError):public_confirmation(runtime,'shop',record)
        runtime,record=self.fixture();record['items'][0]['sku_id']='foreign'
        with self.assertRaises(ValueError):public_confirmation(runtime,'shop',record)


if __name__=='__main__':unittest.main()
