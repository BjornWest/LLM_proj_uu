"""Privileged browser-derived solver; no reference answer or target-ID reads."""
import json
import re
from intent_browser.backend import Completion
from intent_browser.trace import write_json

SORT_LABELS={'rating-desc':'Highest Rated','date-newest':'Newest First','price-asc':'Price: Low to High'}


class Driver:
    def __init__(self,task,negative,holder):
        self.task=task;self.negative=negative;self.holder=holder;self.iterator=None;self.checks=[]

    def actions(self,page):
        c=self.task.contract;answer='Done'
        if c['kind']=='cart_total':
            for title in ['Bluff','Lenovo ThinkPad X1 Carbon Ultra']:
                yield ('fill',page.get_by_placeholder('Search for products'),title)
                cards=page.locator('[id^="product_card_"]')
                card=cards.filter(has_text=title).first
                yield ('click',card.locator('[id^="add_to_cart_"]'),None)
            yield ('click',page.get_by_role('menuitem',name='View Shopping Cart').locator('a'),None)
            text=page.locator('body').inner_text()
            match=re.search(r'Total:\s*\$([\d,.]+)',text)
            if not match: raise ValueError('Visible cart total missing')
            answer=match[1].replace(',','')
            if self.negative:answer='0.00'
        else:
            yield ('fill',page.get_by_placeholder('Search for products'),c['query'])
            if c['sort']:
                combo=page.get_by_role('combobox',name='Sort Products Dropdown')
                yield ('press',combo,'ArrowDown')
                yield ('press',combo,'Home')
                for _ in range({'price-asc':1,'rating-desc':5,'date-newest':6}[c['sort']]):
                    yield ('press',combo,'ArrowDown')
                yield ('press',combo,'Enter')
            cards=page.locator('[id^="product_card_"]')
            selected=cards.last if self.negative and c['kind']=='purchase' and cards.count()>1 else cards.first
            if c['kind']=='price':
                price=selected.locator('[aria-label^="Price: $"]').get_attribute('aria-label').split('$')[1]
                answer='0.00' if self.negative else price
            else:
                if not (self.negative and c['sort'] is None):
                    yield ('click',selected.locator('[id^="add_to_cart_"]'),None)
                yield ('click',page.get_by_role('menuitem',name='View Shopping Cart').locator('a'),None)
                if not (self.negative and c['sort'] is None):yield ('click',page.locator('#checkout-button'),None)
        yield ('finish',None,answer)

    def complete(self,messages):
        page=self.holder['env'].unwrapped.page
        if self.iterator is None:self.iterator=self.actions(page)
        op,loc,value=next(self.iterator)
        if op=='finish':
            write_json(self.task.trace.directory/'remaining-driver.json',{'checks':self.checks,'answer':value})
            code=f'send_msg_to_user({value!r})'
        else:
            bid=loc.get_attribute('bid',timeout=4000)
            assert bid and f'[{bid}]' in messages[-1]['content'],'Target absent from delivered current AX'
            self.checks.append({'operation':op,'bid':bid,'argument':value})
            code=f'{op}({bid!r}'+(f',{value!r}' if value is not None else '')+')'
        return Completion(code,{'source':'privileged-rendered-page-script'},request={'messages':messages,'model':None})
