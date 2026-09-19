"""Browser-derived final cohort plans; grader references are never read."""
import re
from decimal import Decimal
from datetime import datetime
from data.curation.expansion.tricky.authored.solver import click,fill,money,shop_cards,choose,records,news_cards
from data.curation.expansion.tricky.authored02.solver import cart_rows,remove,podcasts,plan as previous_plan
from data.curation.expansion.tricky.authored03.solver import appointments

def plan(task,page,negative=False):
 p=task['parameters'];op=task['operation'];answer={}
 if op=='shared_artist_album':yield from previous_plan(task,page,negative);return
 if task['site']=='shop':
  if op in ('description_match','review_star_counts'):
   rows=[]
   for title in p['titles']:
    yield fill('input[placeholder="Search for products"]',title);selected=choose(shop_cards(page),{'named':title});yield click('a[href$="/product/'+selected['id']+'"]')
    if op=='description_match':rows.append({'title':page.locator('h2').last.inner_text(),'description':page.get_by_role('heading',name='Description',exact=True).locator('xpath=following-sibling::*[1]').inner_text()})
    else:rows.append(sum(int(re.search(r': (\d+) out of 5',r.get_attribute('aria-label')).group(1))==p['rating'] for r in page.locator('[aria-label^="Rating by"]').all()))
    yield click('a[href="/sites/tricky/shop"]')
   answer=next(r for r in rows if p['contains'] in r['description']) if op=='description_match' else dict(zip(p['keys'],rows))
  elif op=='compose_ranked':
   for i,spec in enumerate(p['selections']):
    yield fill('input[placeholder="Search for products"]',spec['query']);selected=choose(shop_cards(page),spec)
    if negative and i==0:yield click('#add_to_cart_'+selected['id'])
    yield click('#add_to_cart_'+selected['id'])
   yield click('a[href="/sites/tricky/shop/cart"]')
  elif op in ('budget_quantity','remove_largest_subtotal'):
   yield click('a[href="/sites/tricky/shop/cart"]');rows=cart_rows(page)
   if op=='budget_quantity':
    target=next(r for r in rows if r['title']==p['title']);other=sum(r['price']*r['quantity'] for r in rows if r['title']!=p['title']);qty=int((Decimal(str(p['budget']))-other)//target['price']);assert qty>0;selector='.ant-list-item:has(.ant-list-item-meta-title:text-is("'+target['title']+'")) input';yield fill(selector,str(qty+1 if negative else qty));yield {'action':'press','selector':selector,'text':'Tab'}
   elif not negative:yield remove(max(rows,key=lambda r:r['price']*r['quantity'])['title'])
 elif task['site']=='health':
  if op=='record_lab_gap':
   yield click('a[href$="/medical-records"]');record=next(r for r in records(page) if r['title']==p['title']);yield click('a[href$="/lab-results"]');label=next(x for x in page.locator('#lab-results p').all_inner_texts() if x.startswith(p['title']+' - '));lab=datetime.strptime(label.split(' - ',1)[1],'%B %d, %Y %H:%M');answer={'days_later':(lab.date()-datetime.strptime(record['date'],'%Y-%m-%d').date()).days}
  elif op=='message_quote':
   yield click('a[href$="/messages"]');row=page.locator('#messages-content .ant-list-item').filter(has_text=p['contains']);answer={'sender':row.locator('.ant-list-item-meta-title').inner_text(),'message':row.locator('.ant-list-item-meta-description').inner_text()}
  elif op in ('latest_record_draft','record_note_filter'):
   yield click('a[href$="/medical-records"]');rows=records(page)
   if op=='latest_record_draft':
    r=max(rows,key=lambda r:r['date']);text='Question about '+r['title']+': '+r['notes'];yield click('a[href$="/messages"]');yield fill('#new-message-input','Wrong draft' if negative else text)
   else:answer={'titles':[r['title'] for r in sorted(rows,key=lambda r:r['date']) if re.search(r'\b'+re.escape(p['word'])+r'\b',r['notes'],re.I)]}
  elif op=='appointment_record_join':
   yield click('a[href$="/appointments"]');appt=min(appointments(page),key=lambda r:r['date']);yield click('a[href$="/medical-records"]');record=max(records(page),key=lambda r:r['date']);answer={'appointment_doctor':appt['doctor'],'record_doctor':record['doctor']}
 elif task['site']=='news':
  rows=news_cards(page)
  def open_article(title):
   yield fill('#news-search-input',title);yield {'action':'press','selector':'#news-search-input','text':'Enter'}
  if op=='date_range_titles':answer={'titles':[r['title'] for r in sorted(rows,key=lambda r:r['parsed_date']) if p['start']<=r['parsed_date'].strftime('%Y-%m-%d')<=p['end']]}
  elif op=='article_date_gap':
   dates=[next(r['parsed_date'] for r in rows if r['title']==title) for title in p['titles']];answer={'days_between':abs((dates[1]-dates[0]).days)}
  elif op=='article_numeric_facts':
   yield from open_article(p['title']);text=page.locator('#article-content .ant-typography').first.inner_text();percent=int(re.search(r'(\d+)%',text).group(1));assert 'next decade' in text;answer={'reduction_percent':percent,'horizon_years':10}
  elif op=='save_article_titles':
   for i,title in enumerate(p['titles']):
    yield from open_article(title)
    if not negative or i>0:yield click('button:has-text("Add to Personalized News")')
    yield click('#news-logo-link')
   yield click('#personalized-news-button')
  elif op=='article_content_match':
   matches=[]
   for title in p['titles']:
    yield from open_article(title);text=page.locator('#article-content .ant-typography').first.inner_text()
    if p['contains'] in text:matches.append({'title':page.locator('#article-title').inner_text(),'first_sentence':re.sub(r'\s+',' ',text).strip().split('. ',1)[0].rstrip('.')+'.'})
    yield click('#news-logo-link')
   assert len(matches)==1;answer=matches[0]
 elif task['site']=='spotify':
  if op in ('plan_capacity','family_savings'):
   yield click('a[href$="/spotify/membership"]');rows=[]
   for c in page.locator('[id^="pricing-plan-card-"]').all():
    text=c.inner_text();title=next(x for x in text.splitlines() if x.startswith('Spotify Premium '));price=Decimal(re.search(r'US\$(\d+\.\d{2})',text).group(1));capacity=int(re.search(r'Up to (\d+) premium accounts',text).group(1)) if 'Up to' in text else 2 if 'two people' in text else 1 if 'one account' in text else None;assert capacity;rows.append({'plan':title,'price':price,'account_limit':capacity})
   if op=='plan_capacity':
    chosen=min([r for r in rows if r['account_limit']>=p['minimum_accounts']],key=lambda r:r['price']);answer={'plan':chosen['plan'],'monthly_usd':money(chosen['price']),'account_limit':chosen['account_limit']}
   else:duo=next(r['price'] for r in rows if r['plan']=='Spotify Premium Duo');family=next(r['price'] for r in rows if r['plan']=='Spotify Premium Family');answer={'monthly_savings_usd':money(2*duo-family)}
  elif op=='podcast_category_intersection':
   yield click('a[href$="/spotify/podcasts"]');rows=[r for r in podcasts(page) if set(p['categories']).issubset(r['categories'])];answer={'hosts':sorted(r['host'] for r in rows),'podcast_count':len(rows)}
 if negative and task['kind']=='answer':
  key=next(iter(answer));answer[key]=answer[key]+1 if type(answer[key]) is int else ['wrong scripted control'] if isinstance(answer[key],list) else 'wrong scripted control'
 yield {'action':'finish','answer':answer if task['kind']=='answer' else None}
