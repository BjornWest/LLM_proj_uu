"""Remaining original read-only shopping tasks; scripts do not import source answers."""
import datetime as dt
import json,re
from decimal import Decimal
from data.curation.expansion.webarena.batch05_driver import Batch05Driver,reviewer_name
from data.curation.expansion.webarena.batch04_driver import money

BATCH=[22,23,24,26,47,125,126,159,160,161,162,238,239,240,241,242,270,271,272,273,279,280,282,283,284,286,326,328,335,336,337,338,352,353,354,355,368,376,384,385]
HELD={47:'Unspecified past-months interval',159:'Best criterion undefined',160:'Best criterion undefined',161:'Best criterion undefined',162:'Best criterion undefined',283:'Latest models and release interval need independently sourced catalog coverage',368:'Whole-catalog sale absence not established by bounded search'}
STATEFUL=set()
NAVIGATE={238,239,240,241,242,270,271,272,273,284,286,326,328,352,353,354,355}
CATEGORIES={238:['Video Games','PlayStation 4','Accessories'],239:['Health & Household','Diet & Sports Nutrition','Nutrition Bars & Drinks'],240:['Clothing, Shoes & Jewelry','Men','Uniforms, Work & Safety'],241:['Beauty & Personal Care','Skin Care'],242:['Health & Household','Household Supplies'],270:['Clothing, Shoes & Jewelry','Men','Shoes'],271:['Beauty & Personal Care','Makeup','Makeup Remover'],272:['Beauty & Personal Care','Oral Care',"Children's Dental Care"],273:['Home & Kitchen','Furniture','Accent Furniture'],352:['Health & Household','Diet & Sports Nutrition','Nutrition Bars & Drinks'],353:['Clothing, Shoes & Jewelry','Sport Specific Clothing','Competitive Swimwear'],354:['Home & Kitchen','Furniture','Living Room Furniture'],355:['Home & Kitchen','Bedding',"Kids' Bedding"]}

def review_matches(task,review):
    body=review['body'];both=review['title']+' '+body
    if task==22:return bool(re.search(r'under\s*water',both,re.I))
    if task==23:return bool(re.search(r'finger\s*print',both,re.I)and re.search(r'no\b|not\b|resist|reduc|free|less',both,re.I))
    if task==24:return bool(re.search(r'overpriced|too expensive|unfair|not worth|price.{0,30}(high|ridiculous)',both,re.I))
    if task==26:return bool(re.search(r'customer service|customer support|technical support|epson.{0,20}(call|contact)|call.{0,20}epson',both,re.I)and re.search(r'bad|poor|horr|rude|worst|not|never|complain|unhelp|useless',both,re.I))
    if task==384:return bool(re.search(r'broken|broke|peeling|rub away|chipping|loosened',both,re.I))
    if task==385:return bool(re.search(r'cute|beautiful|pretty|prettier|chic|classy|looks really nice|stunning',body,re.I))
    raise ValueError(task)

def echo_third_generation_speaker(name):
    return bool(re.match(r'(?:Amazon\s+)?Echo\s+Dot\b',name,re.I)and re.search(r'3rd|third|3(?:\s*gen)',name,re.I)and not re.search(r'charger|adapter|mount|stand|holder|case',name,re.I))

def standalone_ssd_candidate(name):
    primary=re.split(r'\b(?:for|compatible)\b',name,maxsplit=1,flags=re.I)[0]
    excluded=r'enclosure|adapter|cable|case|duplicator|USB\s+hub|upgrade\s+kit|barebone|surface\s+(?:pro|go)|touch.?screen|\b(?:processor|desktop|tablet|console|laptop|computers?|RAM|CPU|G?DDR[23456])\b'
    return bool(re.search(r'\bSSD\b|solid\s+state\s+(?:drive|disk)',primary,re.I)and not re.search(excluded,primary,re.I))

class Batch06Driver(Batch05Driver):
    def finish(self,data=None,status='SUCCESS'):
        self.response={'task_type':'navigate'if self.task_id in NAVIGATE else'retrieve','status':status,'retrieved_data':data}
        return 'send_msg_to_user('+repr(json.dumps(self.response))+')'

    def open_product(self,product):
        yield from self.advanced_name_search(' '.join(product['name'].split()[:3]))
        yield self.act(self.page.locator('.product-item-link').filter(has_text=product['name']).first)
        body='\n'.join([self.page.locator('h1').inner_text(),*self.page.locator('.product.attribute.description').all_inner_texts(),*self.page.locator('#product-attribute-specs-table').all_inner_texts()])
        self.record('own_product_detail',{'product':product,'body':body,'excludes_related_products':True})
        return body

    def steps(self):
        p,t=self.page,self.task_id
        if t in HELD:raise AssertionError('Source-only hold: '+HELD[t])
        if t in (22,23,24,26,384,385):
            if t in (384,385):
                yield from self.advanced_name_search('EYZUTAK');products=yield from self.product_list()
                assert len(products)==1,'More than one case requires broader review collection'
                yield from self.open_product(products[0])
            reviews=yield from self.read_reviews();selected=[r for r in reviews if review_matches(t,r)]
            self.record('semantic_review_selection',{'task':t,'all_reviews':reviews,'selected':selected,'rule':'Visible text matching, independently audited semantics required; not model inference'})
            if t in (22,24):
                assert not selected,'Unexpected matching review requires non-null response schema'
                yield self.finish(None,'SUCCESS'if self.negative else'NOT_FOUND_ERROR')
            else:
                # Review author is one actual rendered field; repeated substrings are not automatically a DOM duplicate.
                authors=list(dict.fromkeys(r['author']for r in selected));assert authors
                yield self.finish([]if self.negative else authors)
            return
        if t in (326,328):
            yield from self.search('Canon photo printer'if t==326 else'iphone 12 phone case')
            if t==328:yield from self.sort_price(True)
            self.record('search_sort_state',{'url':p.url,'sort':p.locator('select[data-role="sorter"]').first.input_value(),'products':p.locator('li.product-item').all_inner_texts()})
            yield from self.wrong_destination();yield self.finish();return
        if t in CATEGORIES:
            self.record('requested_category_path',CATEGORIES[t]);yield from self.category(CATEGORIES[t])
            self.record('category_arrival',{'url':p.url,'title':p.locator('h1').inner_text(),'filters':p.locator('.filter-options').inner_text()})
            if t in (270,271,272,273):
                ceiling={270:Decimal('30'),271:Decimal('46.99'),272:Decimal('78'),273:Decimal('199')}[t]
                links=p.locator('.filter-options-content a').evaluate_all('es=>es.map(e=>({text:e.innerText,href:e.href}))')
                candidates=[x for x in links if re.search(r'\$0(?:\.00)?\s*-\s*\$'+re.escape(str(ceiling))+r'(?:\.00)?\b',x['text'])]
                self.record('native_price_filter_choices',{'ceiling':str(ceiling),'links':links,'matching':candidates})
                assert len(candidates)==1,'Original UI has no unique exact requested price bucket'
                yield self.act(p.locator('.filter-options-content a').filter(has_text=candidates[0]['text']).first)
            elif t in (238,239,240,241,242):
                yield from self.sort_price(False)
                products=p.locator('li.product-item').evaluate_all('es=>es.filter(e=>e.querySelector(".price")).map(e=>({name:e.querySelector(".product-item-link").innerText,price:e.querySelector(".price").innerText,url:e.querySelector(".product-item-link").href}))')
                assert products and [money(x['price'])for x in products]==sorted([money(x['price'])for x in products],reverse=True)
                self.record('descending_category_products',products)
                yield self.act(p.locator('.product-item-link').first)
            else:yield from self.sort_price(t in (352,353))
            self.record('final_requested_category_state',{'url':p.url,'body':p.locator('main').inner_text()})
            yield from self.wrong_destination();yield self.finish();return
        if t in (335,336,337,338):
            rows=yield from self.all_orders();dates=[dt.datetime.strptime(r[1],'%m/%d/%y').date()for r in rows];assert dates==sorted(dates,reverse=True)
            pattern={335:r'body butter',336:r'conditioner',337:r'olive.*bread|bread.*olive',338:r'toothpaste'}[t]
            found=None
            for row,date in zip(rows,dates):
                yield from self.detail(row);items=self.items();selected=[item for item in items if re.search(pattern,item['name'],re.I)]
                self.record('newest_first_item_check',{'order':row,'items':items,'selected':selected})
                if selected:found=date.isoformat();break
                yield from self.restore_orders()
            assert found,'No matching product in complete history'
            yield self.finish(['1900-01-01']if self.negative else[found]);return
        if t==376:
            yield from self.advanced_name_search('Echo Dot');products=yield from self.product_list()
            selected=[x for x in products if echo_third_generation_speaker(x['name'])]
            reviews=[]
            for product in selected:
                yield from self.open_product(product)
                if p.locator('.reviews-actions .action.view').count():reviews.extend((yield from self.read_reviews()))
            self.record('echo_dot_review_availability',{'products':products,'selected':selected,'reviews':reviews})
            assert not reviews,'Reviews exist; cannot emit source null response'
            yield self.finish(None,'SUCCESS'if self.negative else'NOT_FOUND_ERROR');return
        if t in (125,126,279,280,282):
            query={125:'teeth grinding mouth guard',126:'Canon photo printer',279:'Sony',280:'Anker',282:'Nike'}[t]
            yield from (self.search(query)if t in (125,126)else self.advanced_name_search(query))
            products=yield from self.product_list()
            if t==125:selected=[x for x in products if re.search(r'mouth.*guard|night.*guard|guard.*teeth|bruxism',x['name'],re.I)]
            elif t==126:selected=[x for x in products if re.search('Canon',x['name'],re.I)and re.search('printer',x['name'],re.I)and not re.search(r'ink|cartridge|toner|paper|case|cable|adapter',x['name'],re.I)]
            elif t==279:
                candidates=[x for x in products if re.match('Sony\\b',x['name'],re.I)and re.search(r'headphone|headset',x['name'],re.I)];selected=[]
                for product in candidates:
                    if re.search('Bluetooth',product['name'],re.I):selected.append(product);continue
                    body=yield from self.open_product(product)
                    if re.search('Bluetooth',body,re.I):selected.append(product)
            elif t==280:selected=[x for x in products if re.search(r'\bAnker\b',x['name'],re.I)and re.search(r'charger',x['name'],re.I)and not re.search(r'Fit for Anker|compatible with Anker',x['name'],re.I)]
            else:
                candidates=[x for x in products if re.match('Nike\\b',x['name'],re.I)];selected=[]
                for product in candidates:
                    if re.search(r'slide',product['name'],re.I):selected.append(product);continue
                    if re.search('Benassi',product['name'],re.I):
                        body=yield from self.open_product(product)
                        if re.search(r'slide|slipper',body,re.I):selected.append(product)
            self.record('product_membership',{'query':query,'all':products,'selected':selected,'scope':'Visible product names; individual details where title lacks requested feature. Not native-gold membership.'})
            assert selected;prices=[money(x['price'])for x in selected];answer={'min':float(min(prices)),'max':float(max(prices))}
            if t in (279,280,282):answer['names']=[x['name']for x in selected]
            yield self.finish([]if self.negative else[answer]);return
        if t in (284,286):
            yield from self.advanced_name_search('shoe'if t==284 else'ssd');products=yield from self.product_list()
            candidates=[x for x in products if re.search(r'organiz|rack|storag',x['name'],re.I)]if t==284 else[x for x in products if standalone_ssd_candidate(x['name'])]
            candidates.sort(key=lambda x:money(x['price']));self.record('capacity_candidates',candidates);selected=None
            for candidate in candidates:
                body=yield from self.open_product(candidate)
                if t==284:
                    pairs=[int(x)for x in re.findall(r'(\d+)\s+pairs?',body,re.I)]
                    pockets=[int(x)for x in re.findall(r'(\d+)\s+(?:large\s+fabric\s+)?pockets?',body,re.I)]
                    assert pairs or pockets,'Unknown capacity in cheaper candidate'
                    enough=any(n>=12 for n in pairs)or any(n>=24 for n in pockets)
                else:
                    capacities=[Decimal(x)for x in re.findall(r'(\d+(?:\.\d+)?)\s*TB\b',body,re.I)]
                    assert capacities or re.search(r'\d+\s*GB\b',body,re.I),'Unknown SSD capacity'
                    enough=any(n>=1 for n in capacities)
                if enough:selected=candidate;break
            assert selected;self.record('capacity_selected',selected)
            yield from self.wrong_destination();yield self.finish();return
        raise NotImplementedError(t)
