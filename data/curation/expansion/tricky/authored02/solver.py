"""Browser-derived plans. No expected answer or private source fact access."""
import re
from decimal import Decimal
from datetime import datetime
from data.curation.expansion.tricky.authored.solver import click,fill,money,shop_cards,choose,records,news_cards

def cart_rows(page):
 return [{'title':r.locator('.ant-list-item-meta-title').inner_text(),'price':Decimal(r.locator('.ant-list-item-meta-description').inner_text().lstrip('$')),'quantity':int(r.locator('input').input_value())} for r in page.locator('.ant-list-item').all()]
def remove(title):return click('button[aria-label="Remove '+title+' from cart"]')
def podcasts(page):
 rows=[]
 for c in page.locator('.podcast-card').all():
  ps=c.locator('p').all_inner_texts();rows.append({'title':c.locator('h3').inner_text(),'host':ps[0].removeprefix('Host: '),'description':ps[1],'rating':Decimal(ps[2].removeprefix('Rating: ').split(' / ')[0]),'categories':ps[3].removeprefix('Categories: ').split(', ')})
 return rows

def plan(task,page,negative=False):
 op=task['operation'];p=task['parameters'];answer={}
 if task['site']=='shop':
  if op.startswith('cart_'):
   yield click('a[href="/sites/tricky/shop/cart"]');rows=cart_rows(page)
   if op=='cart_remove_price':
    targets=[r['title'] for r in rows if r['price']>p['above']]
    for title in targets:
     if not negative:yield remove(title)
   elif op=='cart_replace':
    yield remove(p['remove']);yield click('a[href="/sites/tricky/shop"]');yield fill('input[placeholder="Search for products"]',p['query']);r=choose(shop_cards(page),p)
    if not negative:yield click('#add_to_cart_'+r['id'])
    yield click('a[href="/sites/tricky/shop/cart"]')
   elif op=='cart_keep_rating':
    yield click('a[href="/sites/tricky/shop"]');yield fill('input[placeholder="Search for products"]',p['query']);best=choose(shop_cards(page),{'rank':'rating_max'})
    yield click('a[href="/sites/tricky/shop/cart"]')
    for r in rows:
     if r['title']!=best['title'] and not negative:yield remove(r['title'])
   elif op=='cart_empty':
    for i,r in enumerate(rows):
     if not negative or i>0:yield remove(r['title'])
   elif op=='cart_inventory':answer={'unit_count':sum(r['quantity'] for r in rows),'total_usd':money(sum(r['price']*r['quantity'] for r in rows))}
  elif op in ('unreviewed_titles','price_interval_titles'):
   yield fill('input[placeholder="Search for products"]',p['query']);rows=shop_cards(page)
   rows=[r for r in rows if r['rating'] is None] if op=='unreviewed_titles' else [r for r in rows if p['minimum']<=r['price']<p['maximum_exclusive']]
   answer={'titles':sorted(r['title'] for r in rows)}
  elif op=='category_minimum_difference':
   selected=[]
   for query in p['queries']:
    yield fill('input[placeholder="Search for products"]',query);selected.append(choose(shop_cards(page),{'rank':'price_min'}))
   answer={'book_title':selected[0]['title'],'bottle_title':selected[1]['title'],'difference_usd':money(selected[0]['price']-selected[1]['price'])}
 elif task['site']=='health':
  if op=='preview_missing':
   yield click('a[href$="/dashboard"]');preview=page.locator('#medical-records-list .ant-list-item-meta-title').all_inner_texts();yield click('a[href$="/medical-records"]');missing=[r for r in records(page) if r['title'] not in preview];assert len(missing)==1;answer={k:missing[0][k] for k in ['title','doctor']}
  elif op=='record_range_doctors':
   yield click('a[href$="/medical-records"]');answer={'doctors':sorted(r['doctor'] for r in records(page) if p['start']<=r['date']<=p['end'])}
  elif op=='message_record_join':
   yield click('a[href$="/messages"]');row=page.locator('#messages-content .ant-list-item').filter(has_text=p['message_contains']);sender=row.locator('.ant-list-item-meta-title').inner_text();yield click('a[href$="/medical-records"]');record=next(r for r in records(page) if r['doctor']==sender);answer={'sender':sender,'record_title':record['title']}
  elif op=='latest_listing_join':
   yield click('a[href$="/medical-records"]');latest=max(records(page),key=lambda r:r['date']);yield click('a[href$="/lab-results"]');labs=[x.split(' - ',1) for x in page.locator('#lab-results p').all_inner_texts()];lab=max(labs,key=lambda r:datetime.strptime(r[1],'%B %d, %Y %H:%M'));answer={'medical_record_title':latest['title'],'lab_result_title':lab[0]}
 elif task['site']=='news':
  rows=news_cards(page)
  if op in ('save_year','save_year_title'):
   selected=[r for r in rows if r['parsed_date'].year==p['year'] and (op=='save_year' or p['title_contains'] in r['title'])]
   if negative:selected=selected+[next(r for r in rows if r not in selected)]
   for r in selected:
    yield click('#read-more-button-'+r['id']);yield click('button:has-text("Add to Personalized News")');yield click('#news-logo-link')
   yield click('#personalized-news-button')
  elif op=='year_counts':answer={'count_'+str(y):sum(r['parsed_date'].year==y for r in rows) for y in p['years']}
  elif op=='oldest_quote':
   r=min(rows,key=lambda r:r['parsed_date']);yield click('#read-more-button-'+r['id']);text=page.locator('#article-content .ant-typography').first.inner_text();answer={'title':page.locator('#article-title').inner_text(),'first_sentence':re.sub(r'\s+',' ',text).strip().split('. ',1)[0].rstrip('.')+'.'}
 elif task['site']=='spotify':
  if op.startswith('podcast_'):
   yield click('a[href$="/spotify/podcasts"]');rows=[r for r in podcasts(page) if p['category'] in r['categories']];r=max(rows,key=lambda r:r['rating']) if op=='podcast_rank' else rows[0];answer={k:r[k] for k in ['title','host']+(['description'] if op=='podcast_details' else [])}
  elif op=='duo_savings':
   yield click('a[href$="/spotify/membership"]');prices=[]
   for title in ['Spotify Premium Individual','Spotify Premium Duo']:
    text=page.locator('[id^="pricing-plan-card-"]').filter(has_text=title).inner_text();prices.append(Decimal(re.search(r'US\$(\d+\.\d{2})',text).group(1)))
   answer={'monthly_savings_usd':money(prices[0]*2-prices[1])}
  elif op=='shared_artist_album':
   albums=[]
   for artist in p['artists']:
    yield click('a[href$="/spotify/search"]');yield fill('#search-input',artist);yield {'action':'press','selector':'#search-input','text':'Enter'};yield click('.spotify-search .ant-card-meta-description a');albums.append(set(page.locator('.spotify-artist-profile .ant-card-meta-description').all_inner_texts()))
   shared=albums[0]&albums[1];assert len(shared)==1;answer={'album':next(iter(shared))}
 if negative and task['kind']=='answer':
  key=next(iter(answer));answer[key]=answer[key]+1 if type(answer[key]) is int else ['wrong scripted control'] if isinstance(answer[key],list) else 'wrong scripted control'
 yield {'action':'finish','answer':answer if task['kind']=='answer' else None}
