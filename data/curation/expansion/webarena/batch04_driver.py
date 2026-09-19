"""Original task batch04: DOM-assisted scripts, no expected-answer imports."""
import datetime as dt
from decimal import Decimal
import json
import re
from data.curation.expansion.webarena.batch03_driver import Batch03Driver

BATCH=[25,48,49,50,51,141,148,149,150,165,167,190,192,233,275,281,300,320,321,322,325,327,330,360,361,362,67,68,653,689]
STATEFUL=set()  # Draft filling changes the browser DOM; no server-side writes allowed.
DRAFTS={653,689}
NAVIGATE={275,300,325,327}


def money(text):
    return Decimal(text.replace('$','').replace(',','').strip())


class Batch04Driver(Batch03Driver):
    def finish(self,data=None,status='SUCCESS'):
        self.response={'task_type':'mutate' if self.task_id in DRAFTS else 'navigate' if self.task_id in NAVIGATE else 'retrieve','status':status,'retrieved_data':data}
        return 'send_msg_to_user('+repr(json.dumps(self.response))+')'

    def read_reviews(self):
        p=self.page
        yield self.act(p.locator('.reviews-actions .action.view'))
        reviews=[]
        for _ in range(30):
            p.locator('.review-item').first.wait_for(state='visible')
            reviews.extend(p.locator('.review-item').evaluate_all('''es=>es.map(e=>({title:e.querySelector('.review-title')?.innerText,
                body:e.querySelector('.review-content')?.innerText,author:e.querySelector('.review-details-value')?.innerText,
                rating:e.querySelector('.rating-result')?.getAttribute('title')}))'''))
            nxt=p.locator('#product-review-container .pages-item-next a:visible').first
            if not nxt.count():break
            yield self.act(nxt)
        else:raise AssertionError('Review pagination exceeded30')
        self.record('all_reviews',reviews)
        return reviews

    def detail(self,row):
        p=self.page
        yield self.act(p.locator('#my-orders-table tbody tr').filter(has_text=row[0]).get_by_role('link',name='View Order',exact=True))
        self.record('order_detail',{'order':row,'body':p.locator('main').inner_text()})

    def restore_orders(self):
        yield self.act(self.page.get_by_role('link',name='My Orders',exact=True))
        yield self.act(self.page.locator('#limiter'),'select_option','50')

    def items(self):
        return self.page.locator('#my-orders-table tbody tr').evaluate_all('''es=>es.filter(e=>e.querySelector('.product.name')).map(e=>({
            name:e.querySelector('.product.name').innerText,text:e.innerText,
            price:e.querySelector('.col.price .price')?.innerText,
            subtotal:e.querySelector('.col.subtotal .price')?.innerText,
            sku:e.querySelector('.col.sku')?.innerText,
            options:Array.from(e.querySelectorAll('.item-options dt')).map(d=>({name:d.innerText,value:d.nextElementSibling?.innerText}))}))''')

    def steps(self):
        p,t=self.page,self.task_id
        if t in (25,165,167):
            reviews=yield from self.read_reviews()
            if t==25:
                selected=[r for r in reviews if float(re.search(r'\d+(?:\.\d+)?',r['rating'])[0])<=60 and re.search(r'print.{0,70}qualit|qualit.{0,70}print',r['body'],re.I)]
                values=[]
                for r in selected:
                    author=r['author'];half=len(author)//2
                    values.append(author[:half]if len(author)%2==0 and author[:half]==author[half:]else author)
                self.record('print_quality_review_selection',selected)
            else:
                values=[r['title']for r in reviews if float(re.search(r'\d+(?:\.\d+)?',r['rating'])[0])<=40]
            yield self.finish([] if self.negative else list(dict.fromkeys(values)))
        elif t in (275,325,327):
            yield from self.search({275:'xbox',325:'mouth night guard',327:'iphone 12 phone case'}[t])
            if t==325:
                yield from self.sort_price(False)
            elif t==327:
                yield self.act(p.locator('select[data-role="sorter"]').first,'select_option','name')
                ascending=p.get_by_role('link',name=re.compile('Set Ascending Direction$')).first
                if ascending.count():yield self.act(ascending)
            self.record('search_destination',{'url':p.url,'products':p.locator('.product-item').all_inner_texts()})
            yield from self.wrong_destination()
            yield self.finish()
        elif t in (67,68):
            yield from self.forum('books')
            titles=p.locator('.submission__title').all_inner_texts()[:10]
            self.record('original_hot_top_ten',titles)
            selected=[title for title in titles if 'The Hobbit' in title or 'A Christmas Carol' in title]
            assert len(selected)==2,'Seeded semantic candidates changed'
            values=[]
            for title in selected:
                yield self.act(p.get_by_role('link',name=title,exact=True))
                content=p.locator('.submission').first.inner_text()
                self.record('opened_book_recommendation',{'title':title,'content':content})
                book=next(book for book in ['The Hobbit','A Christmas Carol']if book in content)
                author='Tolkien' if re.search(r'\bTolkien\b',content)else None
                values.append(book if t==67 else {'book':book,'author':author})
                yield self.act(p.get_by_role('link',name='/f/books',exact=True))
            yield self.finish([] if self.negative else values)
        elif t==281:
            yield from self.advanced_name_search('Oral-B')
            products=[]
            for _ in range(30):
                products.extend(p.locator('li.product-item').evaluate_all('''es=>es.filter(e=>e.querySelector('.product-item-link')&&e.querySelector('.price')).map(e=>({name:e.querySelector('.product-item-link').innerText,price:e.querySelector('.price').innerText}))'''))
                nxt=p.locator('.pages-item-next a:visible').first
                if not nxt.count():break
                yield self.act(nxt)
            else:raise AssertionError('Product range exceeds30pages')
            selected=[r for r in products if re.search(r'Oral[ -]?B\b',r['name'],re.I)and re.search('kids|children|stages',r['name'],re.I)and re.search('heads',r['name'],re.I)]
            self.record('child_brush_head_candidates',{'all':products,'selected':selected})
            prices=[money(r['price'])for r in selected]
            yield self.finish([] if self.negative else [{'names':[r['name']for r in selected],'min':float(min(prices)),'max':float(max(prices))}])
        elif t==689:
            yield self.act(p.get_by_role('link',name='Contact Us',exact=True))
            text='Wrong draft for validation'if self.negative else'I am a loyal customer, give me a coupon'
            yield self.act(p.locator('#comment'),'fill',text)
            self.record('final_draft_visible',{'comment':p.locator('#comment').input_value()})
            yield self.finish()
        else:
            rows=yield from self.all_orders()
            dated=[(r,dt.datetime.strptime(r[1],'%m/%d/%y').date())for r in rows]
            assert [d for r,d in dated]==sorted([d for r,d in dated],reverse=True)
            if t in (48,49,50,51):
                begin={48:dt.date(2023,6,9),49:dt.date(2023,2,12),50:dt.date(2022,6,12),51:dt.date(2022,12,12)}[t]
                chosen=[r for r,d in dated if begin<=d<=dt.date(2023,6,12)and r[3].lower()=='complete']
                self.record('date_interval_orders',{'inclusive_start':begin.isoformat(),'inclusive_end':'2023-06-12','interpretation':'Calendar intervals, not30-day month approximation','rows':chosen})
                value=[{'order_count':len(chosen),'amount':float(sum((money(r[2])for r in chosen),Decimal(0)))}]
            elif t in (190,192,233,300):
                row=next(r for r in rows if (r[3].lower()!='canceled'if t==192 else r[3].lower()==('pending'if t==300 else'complete')))
                self.record('selected_order',row)
                if t==300:
                    yield from self.detail(row)
                    yield from self.wrong_destination()
                    yield self.finish();return
                value=[row[0]]if t==233 else[float(money(row[2]))]
            elif t in (320,321,322):
                chosen=[r for r,d in dated if r[3].lower()=='canceled'and (d.year==2022 if t==321 else d.year==2023 and d.month==(2 if t==320 else 5))]
                if t==322:
                    amounts=[]
                    for row in chosen:
                        yield from self.detail(row)
                        amounts.append(money(p.locator('tr.subtotal .price').inner_text()))
                        yield from self.restore_orders()
                else:amounts=[money(r[2])for r in chosen]
                self.record('refund_orders',{'rows':chosen,'include_shipping':t!=322,'amounts':[str(a)for a in amounts]})
                value=[float(sum(amounts,Decimal(0)))]
            elif t in (360,361,362,653):
                if t==361:
                    value=[{'order_number':r[0],'status':r[3].lower()}for number in [170,189]for r in rows if int(r[0])==number]
                else:
                    number={360:148,362:178,653:180}[t];row=next(r for r in rows if int(r[0])==number)
                    yield from self.detail(row);items=self.items();self.record('order_items',items)
                    if t==360:value=[i['name']for i in items]
                    elif t==362:
                        address=p.locator('.box-order-billing-address address').inner_text();self.record('billing_address',address)
                        lines=[s.strip()for s in address.splitlines()if s.strip()];street=lines[1].split(' ',1);city,state,postcode=[s.strip()for s in lines[2].split(',')]
                        value=[{'house_number':street[0],'street':street[1],'city':city,'state':state,'postcode':postcode,'country':lines[3]}]
                    else:
                        item=next(i for i in items if 'screen protector'in i['name'].lower())
                        text='Wrong draft for validation'if self.negative else f"Please refund the screen protector. Order #{row[0]}. Product SKU {item['sku']}. It broke after just three days of use."
                        yield self.act(p.get_by_role('link',name='Contact Us',exact=True))
                        yield self.act(p.locator('#comment'),'fill',text)
                        self.record('final_draft_visible',{'comment':p.locator('#comment').input_value()})
                        yield self.finish();return
            elif t in (141,148,149,150,330):
                month={141:(2023,3),148:(2022,9),149:(2023,2),150:(2023,1),330:(2023,3)}[t]
                chosen=[r for r,d in dated if (d.year,d.month)==month and r[3].lower()=='complete']
                found=[];amounts=[]
                for row in chosen:
                    yield from self.detail(row);items=self.items();self.record('order_items',items)
                    if t==330:amounts.append(money(p.locator('tr.subtotal .price').inner_text()))
                    elif t==141:
                        food=[i for i in items if re.search(r'cake|muffin|cornbread|bread|cooking|cereal|food',i['name'],re.I)]
                        self.record('food_related_selection',food);amounts.extend(money(i['subtotal'])for i in food)
                    else:
                        pattern={148:r'picture.*fram',149:r'artificial.*plant',150:r'(artificial|fake).*tree'}[t]
                        matched=[i for i in items if re.search(pattern,i['name'],re.I)]
                        for item in matched:
                            found.append(float(money(item['price']))if t==150 else next(o['value']for o in item['options']if o['name'].lower()=='color'))
                    yield from self.restore_orders()
                value=[float(sum(amounts,Decimal(0)))]if t in (141,330)else found
                assert value,'No matching detail value found'
            else:raise NotImplementedError(t)
            self.record('derived_response',value)
            yield self.finish([]if self.negative else value)
