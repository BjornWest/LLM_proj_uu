"""Fixed privileged reads for exclusively leased worker clones; no SQL RPC.

Projections preserve the curation vote/post/wishlist readers. SQL execution and
instance validation stay on the host. No benchmark/manual clone is admissible.
"""
import json
import subprocess
if __package__:
    from .worker_site_clones import inspect
else:
    from worker_site_clones import inspect

USER = 'MarvelsGrantMan136'
EMAIL = 'emma.lopez@gmail.com'

class StateReader:
    def __init__(self, site, container_id, canonical):
        self.site, self.container_id, self.canonical = site, container_id, canonical
    def validate(self):
        if inspect(self.site, self.canonical)['Id'] != self.container_id:
            raise ValueError('Worker instance changed; grading refused')
    def sql(self, query):
        self.validate()
        if self.site == 'forum':
            raw = subprocess.check_output(['docker','exec','--user','postgres',self.container_id,'psql','-d','postmill','-Atc',query], text=True, stderr=subprocess.PIPE, timeout=30)
        else:
            php='$e=require "/var/www/magento2/app/etc/env.php";$c=$e["db"]["connection"]["default"];$p=new PDO("mysql:host=".$c["host"].";dbname=".$c["dbname"],$c["username"],$c["password"],[PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION]);echo json_encode($p->query($argv[1])->fetchAll(PDO::FETCH_ASSOC));'
            raw = subprocess.check_output(['docker','exec',self.container_id,'php','-r',php,query], text=True, stderr=subprocess.PIPE, timeout=30)
        self.validate()
        return raw
    def rows(self, query):
        if self.site == 'forum':
            return [json.loads(line) for line in self.sql('SELECT row_to_json(q) FROM ('+query+')q').splitlines() if line]
        return json.loads(self.sql(query))
    def submission_ids(self):
        if self.site != 'forum': raise ValueError('Wrong site for submission IDs')
        return [int(value) for value in self.sql('SELECT id FROM submissions ORDER BY id').splitlines()]
    def posts_since(self, baseline):
        if self.site != 'forum' or not isinstance(baseline,list) or any(type(x) is not int for x in baseline):
            raise ValueError('Invalid trusted submission baseline')
        ids = sorted(set(self.submission_ids()) - set(baseline))
        if not ids: return []
        return self.rows('SELECT s.id,s.forum_id,f.name AS forum_name,s.user_id,u.username,s.title,s.body,s.url,s.timestamp,s.edited_at,s.visibility,s.moderated '
            'FROM submissions s JOIN forums f ON f.id=s.forum_id JOIN users u ON u.id=s.user_id '
            'WHERE s.id IN ('+','.join(map(str,ids))+') ORDER BY s.id')
    def vote_state(self, target):
        if self.site != 'forum' or type(target) is not int or target <= 0: raise ValueError('Invalid trusted vote target')
        return {'target':self.rows(f'SELECT id,forum_id,title,timestamp,net_score FROM submissions WHERE id={target}'),
                'vote':self.rows(f"SELECT v.submission_id,v.upvote,u.username FROM submission_votes v JOIN users u ON u.id=v.user_id WHERE v.submission_id={target} AND u.username='{USER}'"),
                'ui_newest':self.rows(f'SELECT id,timestamp,title FROM submissions WHERE forum_id=(SELECT forum_id FROM submissions WHERE id={target}) ORDER BY id DESC LIMIT 1'),
                'timestamp_newest':self.rows(f'SELECT id,timestamp,title FROM submissions WHERE forum_id=(SELECT forum_id FROM submissions WHERE id={target}) ORDER BY timestamp DESC,id DESC LIMIT 1')}
    def wishlist_state(self):
        if self.site != 'shopping': raise ValueError('Wrong site for wishlist state')
        owner=self.rows("SELECT entity_id,email FROM customer_entity WHERE email='"+EMAIL+"'")
        if len(owner)!=1: raise ValueError('Expected one fixture owner')
        lists=self.rows('SELECT wishlist_id,customer_id,shared FROM wishlist WHERE customer_id='+str(int(owner[0]['entity_id'])))
        if len(lists)!=1: raise ValueError('Expected one fixture wishlist')
        identity=int(lists[0]['wishlist_id'])
        items=self.rows("SELECT i.wishlist_item_id,i.wishlist_id,i.product_id,i.store_id,i.qty,i.description,COALESCE(v1.value,v0.value) AS product_name FROM wishlist_item i JOIN eav_attribute a ON a.attribute_code='name' AND a.entity_type_id=4 LEFT JOIN catalog_product_entity_varchar v0 ON v0.entity_id=i.product_id AND v0.attribute_id=a.attribute_id AND v0.store_id=0 LEFT JOIN catalog_product_entity_varchar v1 ON v1.entity_id=i.product_id AND v1.attribute_id=a.attribute_id AND v1.store_id=i.store_id WHERE i.wishlist_id="+str(identity)+' ORDER BY i.wishlist_item_id')
        options=self.rows('SELECT o.* FROM wishlist_item_option o JOIN wishlist_item i ON i.wishlist_item_id=o.wishlist_item_id WHERE i.wishlist_id='+str(identity)+' ORDER BY o.option_id')
        return {'owner':owner[0],'wishlist':lists[0],'items':items,'options':options}
