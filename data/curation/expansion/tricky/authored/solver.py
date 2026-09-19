"""Privileged navigation plans; facts are extracted from live rendered pages.

Generators emit ordinary browser actions only. They never read grader_input or
source-facts.json. The same plans can be rehearsed with Playwright or BrowserGym.
"""
import re
from datetime import datetime
from decimal import Decimal

def click(selector):return {'action':'click','selector':selector}
def fill(selector,text):return {'action':'fill','selector':selector,'text':text}
def money(x):return f'{Decimal(str(x)):.2f}'
def shop_cards(page):
 rows=[]
 for card in page.locator('[id^="product_card_"]').all():
  price=card.locator('[aria-label^="Price: $"]').get_attribute('aria-label').split('$')[1]
  rate=card.locator('[aria-label^="Product Rating:"]').get_attribute('aria-label');m=re.search(r'Rating: ([\d.]+)',rate)
  rows.append({'id':card.get_attribute('id').removeprefix('product_card_'),'title':card.locator('.ant-card-meta-title').inner_text(),'price':Decimal(price),'rating':Decimal(m[1]) if m else None})
 return rows

def choose(rows,spec):
 if 'named' in spec:rows=[r for r in rows if r['title']==spec['named']]
 if 'min_rating' in spec:rows=[r for r in rows if r['rating'] is not None and r['rating']>=Decimal(str(spec['min_rating']))]
 if 'max_price_exclusive' in spec:rows=[r for r in rows if r['price']<Decimal(str(spec['max_price_exclusive']))]
 if not rows:raise ValueError('No live candidate satisfies task filters')
 rank=spec.get('rank')
 return max(rows,key=lambda r:r['rating'] if r['rating'] is not None else -1) if rank=='rating_max' else min(rows,key=lambda r:r['price']) if rank=='price_min' else rows[0]

def records(page):
 rows=[]
 for card in page.locator('[aria-label^="Medical Record:"]').all():
  title=card.get_attribute('aria-label').split(': ',1)[1];fields={}
  for p in card.locator('p').all_inner_texts():
   key,value=p.split(':',1);fields[key.lower()]=value.strip()
  rows.append({'title':title,**fields})
 return rows

def news_cards(page):
 rows=[]
 for card in page.locator('[id^="news-card-"]').all():
  id=card.get_attribute('id').removeprefix('news-card-')
  if id=='sponsored-ad':continue
  rows.append({'id':id,'title':card.locator('[id^="article-title-"]').inner_text(),'date':card.locator('[id^="article-date-"]').inner_text().removeprefix('Published on: '),'parsed_date':datetime.strptime(card.locator('[id^="article-date-"]').inner_text().removeprefix('Published on: '),'%B %d, %Y')})
 return rows

def plan(task,page,negative=False):
 op=task['operation'];params=task['parameters'];answer={}
 if task['site']=='shop':
  def search(query):yield fill('input[placeholder="Search for products"]',query)
  def detail(title):
   yield from search(title)
   selected=choose(shop_cards(page),{'named':title})
   yield click('a[href$="/product/'+selected['id']+'"]')
  if op=='price_difference':
   prices=[]
   for title in params['titles']:
    yield from detail(title);prices.append(Decimal(next(x[1:] for x in page.locator('h4').all_inner_texts() if re.fullmatch(r'\$\d+\.\d{2}',x))))
    yield click('a[href="/sites/tricky/shop"]')
   answer={'difference_usd':money(prices[1]-prices[0])}
  elif op=='compare_reviews':
   rows=[]
   for title in params['titles']:
    yield from detail(title);count=page.locator('[aria-label^="Rating by"]').count();rows.append({'title':title,'review_count':count});yield click('a[href="/sites/tricky/shop"]')
   answer=max(rows,key=lambda r:r['review_count'])
  elif op=='filter_lookup':
   yield from search(params['query']);selected=choose(shop_cards(page),params);answer={'title':selected['title'],'price_usd':money(selected['price'])}
  elif op in ('compose_cart','sum_ranked'):
   prices=[]
   for i,spec in enumerate(params['selections']):
    yield from search(spec['query']);candidates=shop_cards(page);selected=choose(candidates,spec);prices.append(selected['price'])
    if op=='compose_cart':
     if negative and i==0:
      # Actual quantity violation, not synthetic final-state mutation.
      yield click('#add_to_cart_'+selected['id'])
     yield click('#add_to_cart_'+selected['id'])
   if op=='compose_cart':yield click('a[href="/sites/tricky/shop/cart"]')
   else:answer={'total_usd':money(sum(prices))}
 elif task['site']=='health':
  yield click('a[href$="/medical-records"]');rows=records(page)
  if op=='record_fields':r=next(r for r in rows if r['title']==params['title']);answer={k:r[k] for k in ['doctor','date']}
  elif op=='latest_record':r=max(rows,key=lambda r:r['date']);answer={k:r[k] for k in ['title','date']}
  elif op=='count_records':answer={'record_count':sum(r['date']<params['before'] for r in rows)}
  elif op=='cross_page_dates':
   record=next(r for r in rows if r['title']==params['title']);yield click('a[href$="/lab-results"]');text=next(t for t in page.locator('#lab-results p').all_inner_texts() if t.startswith(params['title']+' - '));answer={'medical_record_date':record['date'],'lab_result_timestamp':text.split(' - ',1)[1]}
 elif task['site']=='news':
  rows=news_cards(page)
  if op=='save_articles':
   selected=[min(rows,key=lambda r:r['parsed_date']),max(rows,key=lambda r:r['parsed_date'])] if 'rank_dates' in params else [next(r for r in rows if r['title']==title) for title in params['titles']]
   if negative:selected=selected+[next(r for r in rows if r not in selected)]
   for r in selected:
    yield click('#read-more-button-'+r['id']);yield click('button:has-text("Add to Personalized News")');yield click('#news-logo-link')
   yield click('#personalized-news-button')
  elif op=='two_article_quotes':
   values=[]
   for title in params['titles']:
    r=next(r for r in rows if r['title']==title);yield click('#read-more-button-'+r['id']);text=page.locator('#article-content .ant-typography').first.inner_text();values.append(re.sub(r'\s+',' ',text).strip().split('. ',1)[0].rstrip('.')+'.');yield click('#news-logo-link')
   answer=dict(zip(['music_article','creative_article'],values))
  elif op=='year_titles':answer={'titles':[r['title'] for r in sorted(rows,key=lambda r:r['parsed_date']) if r['parsed_date'].year==params['year']]}
 elif task['site']=='spotify':
  def search(value):
   yield click('a[href$="/spotify/search"]');yield fill('#search-input',value);yield {'action':'press','selector':'#search-input','text':'Enter'}
  if op=='artist_catalog':
   yield from search(params['artist']);answer={'titles':sorted(page.locator('.spotify-search .ant-card-meta-title').all_inner_texts())}
  elif op=='plan_difference':
   yield click('a[href$="/spotify/membership"]');prices=[]
   for title in params['plans']:
    card=page.locator('[id^="pricing-plan-card-"]').filter(has_text=title);prices.append(Decimal(re.search(r'US\$(\d+\.\d{2})',card.inner_text()).group(1)))
   answer={'difference_usd':money(prices[1]-prices[0])}
  elif op=='track_album':
   yield from search(params['title']);artist=page.locator('.spotify-search .ant-card-meta-description a').inner_text();yield click('.spotify-search .ant-card-meta-description a');album=page.locator('.spotify-artist-profile .ant-card').filter(has_text=params['title']).locator('.ant-card-meta-description').inner_text();answer={'artist':artist,'album':album}
  elif op=='biography_catalog':
   yield click('a[href$="/spotify/artists"]');card=page.locator('.artist-card').filter(has_text=params['biography_contains']);artist=card.locator('h3').inner_text();yield from search(artist);answer={'artist':artist,'titles':sorted(page.locator('.spotify-search .ant-card-meta-title').all_inner_texts())}
 else:raise ValueError(task['site'])
 if negative and task['kind']=='answer':
  key=next(iter(answer));answer[key]=answer[key]+1 if type(answer[key]) is int else ['wrong scripted control'] if isinstance(answer[key],list) else 'wrong scripted control'
 yield {'action':'finish','answer':answer if task['kind']=='answer' else None}
