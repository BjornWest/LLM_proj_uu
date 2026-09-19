"""Original task expansion, batch 03. Scripted/privileged, never model evidence.

Expected answers and native predicates are not imported by these drivers.
Record discovered values before emitting the deliberately wrong paired response.
"""
import datetime
import json
import re
from urllib.parse import urlsplit
from data.curation.expansion.webarena.extra_driver import ExtraDriver

BATCH = [118,124,146,226,269,313,319,329,334,351,28,29,30,31,69,164,189,232,299,359]
STATEFUL = set()
NAVIGATE = {118,269,351,299}


def qualifying_comment_count(rows, author):
    """Only displayed net scores establish more downvotes than upvotes."""
    identifiers = [row['id'] for row in rows]
    assert len(identifiers) == len(set(identifiers)), 'Duplicate comment IDs'
    count = 0
    for row in rows:
        score = row['score'].strip().replace('\u2212', '-')
        assert re.fullmatch(r'-?\d+', score), 'Unrecognized displayed comment score'
        assert row['author'], 'Missing comment author'
        count += row['author'] != author and int(score) < 0
    return count


class Batch03Driver(ExtraDriver):
    def finish(self, data=None, status='SUCCESS'):
        kind = 'mutate' if self.task_id in STATEFUL else 'navigate' if self.task_id in NAVIGATE else 'retrieve'
        self.response = {'task_type':kind,'status':status,'retrieved_data':data}
        return 'send_msg_to_user(' + repr(json.dumps(self.response)) + ')'

    def search(self, query):
        yield self.act(self.page.locator('#search'), 'fill', query)
        yield self.act(self.page.locator('#search'), 'press', 'Enter')
        self.record('search_results', {'query':query,'url':self.page.url})

    def advanced_name_search(self,query):
        yield self.act(self.page.get_by_role('link',name='Advanced Search',exact=True).first)
        yield self.act(self.page.locator('#name'),'fill',query)
        yield self.act(self.page.locator('#form-validate').get_by_role('button',name='Search',exact=True))
        self.record('advanced_search',{'query':query,'body':self.page.locator('main').inner_text()})

    def forum(self,name):
        yield self.act(self.page.get_by_role('link',name='Forums',exact=True))
        link=self.page.get_by_role('link',name=re.compile('^'+re.escape(name)+' —',re.I))
        for _ in range(12):
            if link.count():
                yield self.act(link)
                return
            yield self.act(self.page.get_by_role('link',name='Next',exact=True))
        raise AssertionError('Forum absent within index bound')

    def sort_price(self, ascending):
        page=self.page
        yield self.act(page.locator('select[data-role="sorter"]').first, 'select_option', 'price')
        loc=page.get_by_role('link',name=re.compile('Set '+('Ascending' if ascending else 'Descending')+' Direction$')).first
        if loc.count():
            yield self.act(loc)

    def wrong_destination(self):
        if self.negative:
            yield self.act(self.page.locator('a.logo'))
            assert urlsplit(self.page.url).path == '/'
            self.record('wrong_final_destination',self.page.url)

    def category(self, names):
        page=self.page
        yield self.act(page.get_by_role('menuitem',name=re.compile(re.escape(names[0])+'$')),'press','Enter')
        for name in names[1:]:
            yield self.act(page.locator('.filter-options-content a').filter(has_text=re.compile(r'^\s*'+re.escape(name)+r'\b',re.I)).first)

    def all_orders(self):
        yield from self.orders()
        yield self.act(self.page.locator('#limiter'),'select_option','50')
        rows=self.rows()
        self.record('all_order_rows',rows)
        assert len(rows)==37,'Unexpected seeded order baseline'
        return rows

    def steps(self):
        p,t=self.page,self.task_id
        if t in (189,232,299,359):
            rows=yield from self.all_orders()
            if t==359:
                row=next(r for r in rows if int(r[0])==148)
                value=[datetime.datetime.strptime(row[1],'%m/%d/%y').date().isoformat()]
            else:
                status='canceled' if t==299 else 'pending'
                row=next(r for r in rows if r[3].lower()==status)
                value=[float(row[2].replace('$','').replace(',',''))] if t==189 else [row[0]]
            self.record('matching_order',row)
            if t==299:
                yield self.act(p.locator('#my-orders-table tbody tr').filter(has_text=row[0]).get_by_role('link',name='View Order',exact=True))
                self.record('order_destination',p.url)
                yield from self.wrong_destination()
                yield self.finish()
            else:
                yield self.finish([] if self.negative else value)
        elif t==164:
            yield self.act(p.locator('.reviews-actions .action.view'))
            reviews=[]
            for _ in range(20):
                p.locator('.review-item').first.wait_for(state='visible')
                reviews.extend(p.locator('.review-item').evaluate_all('es=>es.map(e=>({title:e.querySelector(".review-title")?.innerText,rating:e.querySelector(".rating-result")?.getAttribute("title")}))'))
                nxt=p.locator('#product-review-container .pages-item-next a:visible').first
                if not nxt.count():break
                yield self.act(nxt)
            else:raise AssertionError('Review pagination bound exceeded')
            self.record('all_reviews',reviews)
            titles=list(dict.fromkeys(r['title'] for r in reviews if float(re.search(r'\d+(?:\.\d+)?',r['rating'])[0])<=40))
            yield self.finish([] if self.negative else titles)
        elif t==118:
            yield from self.search('mouth night guard')
            link=p.locator('.product-item-link').filter(has_text=re.compile(r'mouth|night|bruxism',re.I)).first
            yield self.act(link)
            self.record('bruxism_product',p.locator('h1').inner_text())
            yield from self.wrong_destination()
            yield self.finish()
        elif t==226:
            yield from self.advanced_name_search('Amazon Basic')
            products=[]
            for _ in range(12):
                products.extend(p.locator('li.product-item').evaluate_all('es=>es.filter(e=>e.querySelector(".product-item-link")&&e.querySelector(".price")).map(e=>({title:e.querySelector(".product-item-link").innerText,price:e.querySelector(".price").innerText}))'))
                nxt=p.locator('.pages-item-next a:visible').first
                if not nxt.count():break
                yield self.act(nxt)
            else:raise AssertionError('Product pagination bound exceeded')
            selected=[x for x in products if re.match(r'^Amazon\s*Basics?\b',x['title'],re.I)]
            self.record('brand_product_listing',{'all':products,'selected':selected,'rule':'Title starts Amazon Basic(s), optional space; excludes another-brand bundle mentioning Amazon Basics'})
            prices=[float(x['price'].replace('$','').replace(',',''))for x in selected]
            yield self.finish([] if self.negative else [{'min':min(prices),'max':max(prices)}])
        elif t==124:
            yield from self.search('wireless earphone')
            yield from self.sort_price(True)
            low=p.locator('.product-item .price').first.inner_text()
            self.record('ascending_first_page',p.locator('.product-item').all_inner_texts())
            yield from self.sort_price(False)
            high=p.locator('.product-item .price').first.inner_text()
            self.record('descending_first_page',p.locator('.product-item').all_inner_texts())
            value=[{'min':float(low.replace('$','').replace(',','')),'max':float(high.replace('$','').replace(',',''))}]
            yield self.finish([] if self.negative else value)
        elif t in (269,351):
            yield from self.category(['Clothing, Shoes & Jewelry','Women','Shoes'] if t==269 else ['Video Games','PlayStation 4','Accessories'])
            if t==269:
                yield self.act(p.locator('.filter-options-title').filter(has_text=re.compile('^Price$')))
                self.record('price_filter_choices',p.locator('.filter-options-content').all_inner_texts())
                yield self.act(p.locator('.filter-options-content a').filter(has_text=re.compile(r'\$0\.00.*\$24\.99')).first)
            else:
                yield from self.sort_price(True)
            self.record('category_result',{'url':p.url,'heading':p.locator('h1').inner_text()})
            yield from self.wrong_destination()
            yield self.finish()
        elif t==313:
            yield self.act(p.get_by_role('link',name='Contact Us',exact=True))
            body=p.locator('main').inner_text()
            self.record('contact_page',body)
            assert not re.search(r'\b\d{3}[-.) ]+\d{3}[-. ]+\d{4}\b',body),'Unexpected phone number requires review'
            # Only this inspected contact page, not proof that every site page lacks a phone.
            yield self.finish(['invented customer-service number'] if self.negative else None,
                              status='SUCCESS' if self.negative else 'NOT_FOUND_ERROR')
        elif t in (319,329):
            rows=yield from self.all_orders()
            dates=[(row,datetime.datetime.strptime(row[1],'%m/%d/%y').date()) for row in rows]
            chosen=[row for row,date in dates if (date.year==2022 and date.month==4 and row[3].lower()=='canceled') ] if t==319 else [row for row,date in dates if date==datetime.date(2023,4,19)]
            self.record('matching_orders',chosen)
            assert not chosen,'Nonempty target orders require detail inspection instead of zero shortcut'
            if t==319:
                yield self.finish([999] if self.negative else None,status='SUCCESS' if self.negative else 'NOT_FOUND_ERROR')
            else:
                yield self.finish([999] if self.negative else [0])
        elif t in (146,334):
            rows=yield from self.all_orders()
            # Enumerate actual eligible order details newest-first, retaining all inspected bodies.
            selected=[r for r in rows if ('/22' in r[1] and r[1].startswith('9/'))] if t==146 else rows
            found=[]
            for row in selected:
                yield self.act(p.locator('#my-orders-table tbody tr').filter(has_text=row[0]).get_by_role('link',name='View Order',exact=True))
                body=p.locator('#my-orders-table').inner_text()
                self.record('inspected_order_detail',{'order':row,'items':body})
                if t==146 and re.search(r'picture.*fram',body,re.I):
                    dims=re.search(r'(\d+)\s*["\u2033]?\s*[xX]\s*(\d+)',body)
                    assert dims,'Frame dimensions absent from order item'
                    found=[{'width':dims[1]+' inches','height':dims[2]+' inches'}]
                elif t==334 and re.search(r'muffin.*cornbread|cornbread.*muffin',body,re.I):
                    found=[datetime.datetime.strptime(row[1],'%m/%d/%y').date().isoformat()]
                if found:break
                yield self.act(p.get_by_role('link',name='My Orders',exact=True))
                yield self.act(p.locator('#limiter'),'select_option','50')
            assert found,'Target item not found through bounded order inspection'
            self.record('derived_order_answer',found)
            yield self.finish([] if self.negative else found)
        elif t in (28,29,30,31):
            yield from self.forum({28:'WorcesterMA',29:'DIY',30:'space',31:'photoshopbattles'}[t])
            yield self.act(p.get_by_role('button',name='Sort by: Hot',exact=True))
            yield self.act(p.get_by_role('link',name='New',exact=True))
            first=p.locator('.submission').first
            title=first.locator('.submission__title').inner_text()
            author=first.locator('a[href^="/user/"]').first.inner_text()
            self.record('newest_post',{'title':title,'author':author})
            yield self.act(first.locator('a[href^="/f/"]').filter(has_text=re.compile('comment',re.I)).first)
            comments=p.locator('.comment')
            comment_rows=comments.evaluate_all('''es=>es.map(e=>({id:e.id,
                author:Array.from(e.querySelectorAll('.comment__header a[href^="/user/"]')).find(x=>x.closest('.comment')===e)?.innerText,
                score:Array.from(e.querySelectorAll('.comment__vote .vote__net-score')).find(x=>x.closest('.comment')===e)?.innerText}))''')
            self.record('comments',{'rows':comment_rows,'body':p.locator('body').inner_text()})
            count=qualifying_comment_count(comment_rows,author)
            yield self.finish([] if self.negative else [{'username':author,'post_title':title,'count':count}])
        elif t==69:
            yield from self.forum('books')
            titles=p.locator('.submission__title').all_inner_texts()[:10]
            self.record('hot_top_ten',titles)
            chosen=[title for title in titles if 'bookshop.org' in title.lower()]
            assert len(chosen)==1,'Human semantic candidate no longer unique'
            yield self.act(p.get_by_role('link',name=chosen[0],exact=True))
            post=p.locator('.submission').first
            links=post.locator('a').evaluate_all('es=>es.map(e=>({text:e.innerText,href:e.getAttribute("href")}))')
            self.record('local_bookstore_post_links',links)
            urls=list(dict.fromkeys(re.findall(r'\b(?:https?://)?bookshop\.org\b',post.inner_text(),re.I)))
            assert urls,'Organization URL absent from actual post'
            yield self.finish([] if self.negative else urls)
        else:
            raise NotImplementedError('Stateful driver pending baseline coordination: '+str(t))
