"""Plain browser-derived plans: no grader_input or source-facts imports."""
import re
from datetime import datetime
from decimal import Decimal
from data.curation.expansion.tricky.authored.solver import click,fill,shop_cards,choose,records,news_cards
from data.curation.expansion.tricky.authored02.solver import cart_rows,remove,podcasts

def appointments(page):
 rows=[]
 for c in page.locator('#appointments-content .ant-list-item').all():
  title=c.locator('.ant-list-item-meta-title').inner_text();desc=c.locator('.ant-list-item-meta-description').inner_text();department,doctor=desc.split(' with ',1);rows.append({'date':title.split(' at ',1)[0],'doctor':doctor,'department':department})
 return rows

def plan(task,page,negative=False):
 p=task['parameters'];op=task['operation'];answer={}
 if task['site']=='shop':
  if op in ('set_quantities','budget_add','replace_query'):
   yield click('a[href="/sites/tricky/shop/cart"]')
   if op=='set_quantities':
    for title,q in p['quantities'].items():
     selector='.ant-list-item:has(.ant-list-item-meta-title:text-is("'+title+'")) input';yield fill(selector,str(q+1 if negative else q));yield {'action':'press','selector':selector,'text':'Tab'}
   elif op=='budget_add':
    total=sum(r['price']*r['quantity'] for r in cart_rows(page));yield click('a[href="/sites/tricky/shop"]');yield fill('input[placeholder="Search for products"]',p['query']);rows=[r for r in shop_cards(page) if r['price']+total<=p['budget']];selected=choose(rows,{'rank':p['rank']})
    if not negative:yield click('#add_to_cart_'+selected['id'])
    yield click('a[href="/sites/tricky/shop/cart"]')
   elif op=='replace_query':
    yield remove(p['remove']);yield click('a[href="/sites/tricky/shop"]');yield fill('input[placeholder="Search for products"]',p['query']);selected=choose(shop_cards(page),p)
    if not negative:yield click('#add_to_cart_'+selected['id'])
    yield click('a[href="/sites/tricky/shop/cart"]')
  elif op=='compose_cheapest':
   for i,query in enumerate(p['queries']):
    yield fill('input[placeholder="Search for products"]',query);selected=choose(shop_cards(page),{'rank':'price_min'})
    if negative and i==0:yield click('#add_to_cart_'+selected['id'])
    yield click('#add_to_cart_'+selected['id'])
   yield click('a[href="/sites/tricky/shop/cart"]')
 elif task['site']=='health':
  if op=='message_draft':
   text=p.get('literal')
   if text is None:
    yield click('a[href$="/medical-records"]');text=p['prefix']+next(r['notes'] for r in records(page) if r['title']==p['record_title'])
   yield click('a[href$="/messages"]');yield fill('#new-message-input','Wrong draft' if negative else text)
  elif op=='extrema_notes':
   yield click('a[href$="/medical-records"]');rows=records(page);old=min(rows,key=lambda r:r['date']);new=max(rows,key=lambda r:r['date']);answer={'oldest_title':old['title'],'oldest_note':old['notes'],'newest_title':new['title'],'newest_note':new['notes']}
  elif op=='message_appointment':
   yield click('a[href$="/messages"]');row=page.locator('#messages-content .ant-list-item').filter(has_text=p['message_contains']);doctor=row.locator('.ant-list-item-meta-title').inner_text();yield click('a[href$="/appointments"]');answer=next(r for r in appointments(page) if r['doctor']==doctor)
  elif op=='appointment_gap':
   yield click('a[href$="/appointments"]');dates=sorted(datetime.strptime(r['date'],'%Y-%m-%d') for r in appointments(page));answer={'days_between':(dates[-1]-dates[0]).days}
 elif task['site']=='news':
  if op=='alert_draft':
   yield click('#news-alerts-button');yield fill('input[placeholder="your.email@example.com"]',p['email']);selector='input[role="combobox"]';yield {'action':'press','selector':selector,'text':'ArrowDown'};yield {'action':'press','selector':selector,'text':'Home'}
   index=0 if negative else ['Daily','Weekly','Monthly'].index(p['frequency'])
   for _ in range(index):yield {'action':'press','selector':selector,'text':'ArrowDown'}
   yield {'action':'press','selector':selector,'text':'Enter'}
  elif op in ('search_article_quote','save_named_preserve'):
   yield fill('#news-search-input',p['title']);yield {'action':'press','selector':'#news-search-input','text':'Enter'}
   if op=='search_article_quote':
    text=page.locator('#article-content .ant-typography').first.inner_text();answer={'title':page.locator('#article-title').inner_text(),'first_sentence':re.sub(r'\s+',' ',text).strip().split('. ',1)[0].rstrip('.')+'.'}
   else:
    if not negative:yield click('button:has-text("Add to Personalized News")')
    yield click('#news-logo-link');yield click('#personalized-news-button')
  elif op=='personalized_chronology':
   yield click('#personalized-news-button');saved=page.locator('.personalized-news h4').all_inner_texts();yield click('#news-logo-link');rows=news_cards(page);answer={'titles':[r['title'] for r in sorted(rows,key=lambda r:r['parsed_date']) if r['title'] in saved]}
 elif task['site']=='spotify':
  if op in ('podcast_list','podcast_compare'):
   yield click('a[href$="/spotify/podcasts"]');rows=podcasts(page)
   if op=='podcast_list':answer={'titles':sorted(r['title'] for r in rows if p['category'] in r['categories'] and r['rating']>=Decimal(str(p['min_rating'])))}
   else:
    chosen=[max([r for r in rows if category in r['categories']],key=lambda r:r['rating']) for category in p['categories']];answer={'technology_title':chosen[0]['title'],'wellness_title':chosen[1]['title'],'higher_rated_title':max(chosen,key=lambda r:r['rating'])['title']}
  elif op=='playlist_inventory':
   yield click('a[href$="/spotify/playlists"]');names=sorted(page.locator('.spotify-playlists .ant-card-head-title').all_inner_texts());answer={'names':names,'playlist_count':len(names)}
  elif op=='artist_bio_filter':
   yield click('a[href$="/spotify/artists"]');answer={'names':sorted(c.locator('h3').inner_text() for c in page.locator('.artist-card').all() if p['contains'] in c.locator('p').inner_text())}
  elif op=='compare_artist_catalog':
   groups=[]
   for artist in p['artists']:
    yield click('a[href$="/spotify/search"]');yield fill('#search-input',artist);yield {'action':'press','selector':'#search-input','text':'Enter'};titles=sorted(page.locator('.spotify-search .ant-card-meta-title').all_inner_texts());groups.append({'artist':artist,'song_count':len(titles),'titles':titles})
   answer=max(groups,key=lambda r:r['song_count'])
 if negative and task['kind']=='answer':
  key=next(iter(answer));answer[key]=answer[key]+1 if type(answer[key]) is int else ['wrong scripted control'] if isinstance(answer[key],list) else 'wrong scripted control'
 yield {'action':'finish','answer':answer if task['kind']=='answer' else None}
