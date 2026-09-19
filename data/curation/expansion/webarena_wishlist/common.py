"""Database reads and controlled wishlist cleanup on the explicitly owned clone only."""
import json,subprocess
NAME='curation-webarena-wishlist-v1';ORIGIN='http://localhost:17770';EMAIL='emma.lopez@gmail.com'
IMAGE='am1n3e/webarena-verified-shopping@sha256:3e8cb9b945ea9b1c94ab26dba53e8d12dd0406abbf4bf686fd3bb2b6a5908feb'
def command(*args):return subprocess.check_output(args,text=True).strip()
def inspect():
 d=json.loads(command('docker','inspect',NAME))[0];assert d['Config']['Labels'].get('intent.owner')=='curation-wishlist' and d['Config']['Image']==IMAGE and not d['Mounts']
 for cp,hp in [('80/tcp','17770'),('8877/tcp','17771')]:assert d['HostConfig']['PortBindings'][cp]==[{'HostIp':'127.0.0.1','HostPort':hp}]
 return {k:d[k]for k in ['Id','Image','Created','Mounts']}
def sql(q):
 inspect()
 # Credentials stay inside the owned container and are never printed or exported.
 php='$e=require "/var/www/magento2/app/etc/env.php";$c=$e["db"]["connection"]["default"];$p=new PDO("mysql:host=".$c["host"].";dbname=".$c["dbname"],$c["username"],$c["password"],[PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION]);$r=$p->query($argv[1]);echo json_encode($r->columnCount()?$r->fetchAll(PDO::FETCH_ASSOC):[]);'
 return json.loads(command('docker','exec',NAME,'php','-r',php,q))
def state():
 owner=sql("SELECT entity_id,email FROM customer_entity WHERE email='"+EMAIL+"'");assert len(owner)==1
 lists=sql('SELECT wishlist_id,customer_id,shared FROM wishlist WHERE customer_id='+str(owner[0]['entity_id']));assert len(lists)==1
 id=lists[0]['wishlist_id'];items=sql("SELECT i.wishlist_item_id,i.wishlist_id,i.product_id,i.store_id,i.qty,i.description,COALESCE(v1.value,v0.value) AS product_name FROM wishlist_item i JOIN eav_attribute a ON a.attribute_code='name' AND a.entity_type_id=4 LEFT JOIN catalog_product_entity_varchar v0 ON v0.entity_id=i.product_id AND v0.attribute_id=a.attribute_id AND v0.store_id=0 LEFT JOIN catalog_product_entity_varchar v1 ON v1.entity_id=i.product_id AND v1.attribute_id=a.attribute_id AND v1.store_id=i.store_id WHERE i.wishlist_id="+str(id)+' ORDER BY i.wishlist_item_id')
 options=sql('SELECT o.* FROM wishlist_item_option o JOIN wishlist_item i ON i.wishlist_item_id=o.wishlist_item_id WHERE i.wishlist_id='+str(id)+' ORDER BY o.option_id')
 return {'owner':owner[0],'wishlist':lists[0],'items':items,'options':options}
def clear_to_empty(initial):
 assert initial['items']==[] and initial['options']==[],'Only original empty wishlist baseline cleanup is supported'
 current=state();assert current['owner']==initial['owner'] and current['wishlist']==initial['wishlist']
 id=int(current['wishlist']['wishlist_id'])
 sql('DELETE o FROM wishlist_item_option o JOIN wishlist_item i ON i.wishlist_item_id=o.wishlist_item_id WHERE i.wishlist_id='+str(id))
 sql('DELETE FROM wishlist_item WHERE wishlist_id='+str(id))
 assert state()==initial
