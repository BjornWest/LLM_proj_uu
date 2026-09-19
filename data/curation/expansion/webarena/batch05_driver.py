"""Additional original shopping tasks; privileged read-only scripted validation."""
import datetime as dt
from decimal import Decimal
import json
import re
from data.curation.expansion.webarena.batch04_driver import Batch04Driver,money

BATCH=[142,143,144,145,147,166,191,225,227,228,229,230,234,235,261,262,263,264,276,277,278,285,301,302,323,331,332,333,387,388]
STATEFUL=set()
NAVIGATE={261,262,263,264,276,277,278,285,301,302}
ABSENCE={166,191,225,234,235,301,302}

def reviewer_name(value):
    half=len(value)//2
    return value[:half]if len(value)%2==0 and value[:half]==value[half:]else value

def numeric_rating(review):
    return Decimal(re.search(r'\d+(?:\.\d+)?',review['rating'])[0])/20

def switch_capacities(text):
    """Recognize explicit Switch-game/game-card counts, never generic SD capacity."""
    patterns=[r'(\d+)\s+(?:units?\s+)?Nintendo\s+Switch(?:\s+Lite)?\s+games?\b',
              r'(\d+)\s+game\s+cards?\b']
    return sorted({int(n)for pattern in patterns for n in re.findall(pattern,text,re.I)})

class Batch05Driver(Batch04Driver):
    def finish(self,data=None,status='SUCCESS'):
        self.response={'task_type':'navigate'if self.task_id in NAVIGATE else'retrieve','status':status,'retrieved_data':data}
        return 'send_msg_to_user('+repr(json.dumps(self.response))+')'

    def product_list(self):
        products=[]
        for _ in range(30):
            products.extend(self.page.locator('li.product-item').evaluate_all('''es=>es.filter(e=>e.querySelector('.product-item-link')&&e.querySelector('.price')).map(e=>({name:e.querySelector('.product-item-link').innerText,url:e.querySelector('.product-item-link').href,price:e.querySelector('.price').innerText}))'''))
            nxt=self.page.locator('.pages-item-next a:visible').first
            if not nxt.count():break
            yield self.act(nxt)
        else:raise AssertionError('Product pagination bound30')
        self.record('all_catalog_matches',products)
        return products

    def menu_category(self,names):
        for index,name in enumerate(names):
            loc=self.page.get_by_role('menuitem',name=re.compile(re.escape(name)+'$'))
            yield self.act(loc,'press','Enter'if index==len(names)-1 else('ArrowDown'if index==0 else'ArrowRight'))
        self.record('category_destination',{'url':self.page.url,'title':self.page.locator('h1').inner_text()})

    def steps(self):
        p,t=self.page,self.task_id
        if t in (261,262,263,264):
            names={261:['Electronics','Headphones'],262:['Clothing, Shoes & Jewelry','Men','Shoes'],263:['Clothing, Shoes & Jewelry','Women','Clothing'],264:['Office Products','Office Furniture & Lighting','Cabinets, Racks & Shelves']}[t]
            yield from self.menu_category(names)
            yield from self.wrong_destination();yield self.finish();return
        if t in (276,277,278):
            yield from self.search({276:'switch accessories',277:'batteries for iphone 13',278:'green tea bag for weight loss'}[t])
            yield from self.wrong_destination();yield self.finish();return
        if t in (166,225,387,388):
            if t==166:
                reviews=yield from self.read_reviews()
            else:
                brand='Sephora'if t==225 else'EYZUTAK'
                yield from self.advanced_name_search(brand)
                products=yield from self.product_list()
                matches=[x for x in products if re.search('brush'if t==225 else'case',x['name'],re.I)]
                assert matches,'No relevant product found'
                reviews=[]
                for product in matches:
                    yield from self.advanced_name_search(' '.join(product['name'].split()[:3]))
                    yield self.act(p.locator('.product-item-link').filter(has_text=product['name']).first)
                    if p.locator('.reviews-actions .action.view').count():
                        review_rows=yield from self.read_reviews()
                    else:
                        self.record('product_without_reviews',{'product':product,'body':p.locator('main').inner_text()})
                        review_rows=[]
                    reviews.extend(review_rows)
            if t in (166,225):
                selected=[r for r in reviews if numeric_rating(r)<=(2 if t==166 else 3)]
                self.record('low_rating_reviews',selected);assert not selected,'Expected absence requires different response, do not silently label'
                yield self.finish(None,'SUCCESS'if self.negative else'NOT_FOUND_ERROR')
            else:
                selected=[r for r in reviews if (numeric_rating(r)>=4 if t==387 else numeric_rating(r)<=2)]
                authors=list(dict.fromkeys(reviewer_name(r['author'])for r in selected))
                self.record('selected_review_authors',selected)
                yield self.finish([]if self.negative else authors)
            return
        if t in (227,228,229,230):
            brand={227:'EYZUTAK',228:'Sephora',229:'UGREEN',230:'Perricone MD'}[t]
            yield from self.advanced_name_search(brand)
            products=yield from self.product_list()
            selected=[r for r in products if re.match(re.escape(brand)+r'\b',r['name'],re.I)]
            self.record('brand_membership',{'brand':brand,'rule':'Visible title starts with requested brand, case insensitive','selected':selected})
            assert selected,'No brand product'
            prices=[money(r['price'])for r in selected]
            yield self.finish([]if self.negative else[{'min':float(min(prices)),'max':float(max(prices))}]);return
        if t==285:
            yield from self.advanced_name_search('Nintendo Switch')
            products=yield from self.product_list()
            candidates=sorted([x for x in products if re.search('card',x['name'],re.I)and re.search('holder|case',x['name'],re.I)],key=lambda x:money(x['price']))
            self.record('capacity_candidates_by_price',candidates)
            selected=None
            for candidate in candidates:
                yield from self.advanced_name_search(' '.join(candidate['name'].split()[:3]))
                yield self.act(p.locator('.product-item-link').filter(has_text=candidate['name']).first)
                body='\n'.join([p.locator('h1').inner_text(),*p.locator('.product.attribute.description').all_inner_texts(),*p.locator('#product-attribute-specs-table').all_inner_texts()]);self.record('capacity_product_detail',{'candidate':candidate,'body':body,'scope':'Own title, description and specification table; excludes related-product modules'})
                capacities=switch_capacities(body)
                assert capacities,'Unrecognized capacity; cannot safely skip a cheaper candidate'
                if any(n>=15 for n in capacities):selected=candidate;break
            assert selected,'Capacity not established from visible detail'
            yield from self.wrong_destination();yield self.finish();return
        rows=yield from self.all_orders()
        dated=[(r,dt.datetime.strptime(r[1],'%m/%d/%y').date())for r in rows]
        assert [d for r,d in dated]==sorted([d for r,d in dated],reverse=True)
        if t in (191,234,235,301,302):
            wanted={191:'processing',234:'hold',235:'delivery',301:'processing',302:'delivery'}[t]
            selected=[r for r in rows if wanted in r[3].lower()]
            self.record('status_absence',{'searched_status':wanted,'complete_history_rows':rows,'matches':selected});assert not selected
            yield self.finish(None,'SUCCESS'if self.negative else'NOT_FOUND_ERROR');return
        if t==147:
            chosen=[r for r,d in dated if d.year==2022 and r[3].lower()=='complete'];found=[]
            for row in chosen:
                yield from self.detail(row)
                for item in self.items():
                    if re.search('picture.*fram',item['name'],re.I):
                        text=item['text'];m=re.search(r'(\d+)\s*["\u2033]?\s*[xX*]\s*(\d+)',text)
                        assert m,'No frame dimensions';found.append({'width':m[1]+' inches','height':m[2]+' inches'})
                yield from self.restore_orders()
            self.record('all_frame_sizes',found);assert found
            yield self.finish([]if self.negative else found);return
        if t in (142,143,144,145,323,331,332,333):
            def include(row,date):
                if t==323:return date.year==2022 and date.month==3 and row[3].lower()=='canceled'
                if row[3].lower()!='complete':return False
                return {142:date.year==2023 and date.month==1,143:date==dt.date(2023,1,29),
                  144:dt.date(2023,1,15)<=date<=dt.date(2023,1,31),145:date.year==2022 and date.month==3,
                  331:date.year==2022 and date.month==7,332:date.year==2023 and date.month<=3,
                  333:date.year==2022 and date.month==11}[t]
            selected=[(r,d)for r,d in dated if include(r,d)];amounts=[];months={1:Decimal(0),2:Decimal(0),3:Decimal(0)}
            for row,date in selected:
                yield from self.detail(row);items=self.items()
                if t in (331,332,333):amount=money(p.locator('tr.subtotal .price').inner_text())
                else:
                    if t==142:matched=[i for i in items if re.search(r'hair|conditioner|shampoo',i['name'],re.I)]
                    elif t==143:matched=[i for i in items if re.search(r'topiary|artificial|decora|picture.*fram',i['name'],re.I)]
                    elif t in (144,145):matched=[i for i in items if re.search(r'bread|muffin|cornbread|pasta|sauce|cooking|kitchen|baking|seasoning|chocolate|coffee|tea\b|food|beef|potato|gravy|juice|beverage',i['name'],re.I)]
                    else:matched=[i for i in items if not re.search(r'AC[- ]DC.*Adapter',i['name'],re.I)]
                    amount=sum((money(i['subtotal'])for i in matched),Decimal(0));self.record('selected_line_items',{'order':row,'all_items':items,'selected':matched})
                amounts.append(amount)
                if t==332:months[date.month]+=amount
                yield from self.restore_orders()
            answer=[{'month':dt.date(2023,m,1).strftime('%B'),'total':float(v)}for m,v in months.items()]if t==332 else[float(sum(amounts,Decimal(0)))]
            self.record('derived_totals',{'rows':[(r,d.isoformat())for r,d in selected],'line_subtotals':[str(v)for v in amounts],'answer':answer})
            yield self.finish([]if self.negative else answer);return
        raise NotImplementedError(t)
