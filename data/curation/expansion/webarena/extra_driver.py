"""Ten additional original templates. Privileged scripted browser drivers only."""
import json
import re
from data.curation.expansion.webarena.browser_batch import Driver

EXTRA = [231, 298, 358, 274, 386, 399, 404, 595, 640, 731]
KINDS = {231:'retrieve',298:'navigate',358:'retrieve',274:'navigate',386:'retrieve',
         399:'mutate',404:'mutate',595:'mutate',640:'mutate',731:'mutate'}


class ExtraDriver(Driver):
    def __init__(self, task_id, negative=False):
        super().__init__(task_id)
        self.negative = negative

    def finish(self, data=None):
        self.response = {'task_type': KINDS[self.task_id], 'status': 'SUCCESS', 'retrieved_data': data}
        return 'send_msg_to_user(' + repr(json.dumps(self.response)) + ')'

    def forum(self, name):
        yield self.act(self.page.get_by_role('link', name='Forums', exact=True))
        link = self.page.get_by_role('link', name=re.compile('^' + re.escape(name) + ' —'))
        for _ in range(12):
            if link.count():
                yield self.act(link)
                return
            yield self.act(self.page.get_by_role('link', name='Next', exact=True))
        raise AssertionError('Forum not found within twelve index pages')

    def steps(self):
        page, task = self.page, self.task_id
        self.record('initial_visible_state', {'url': page.url})
        if task in (231, 298, 358):
            yield from self.orders()
            rows = self.rows()
            self.record('order_rows', rows)
            if task == 231:
                row = next(r for r in rows if r[3].lower() == 'canceled')
                yield self.finish([] if self.negative else [row[0]])
            elif task == 298:
                row = page.locator('#my-orders-table tbody tr').filter(has_text='Complete').first
                yield self.act(row.get_by_role('link', name='View Order', exact=True))
                self.record('order_details', {'url': page.url})
                if self.negative:
                    yield self.act(page.locator('a.logo'))
                yield self.finish()
            else:
                row = page.locator('#my-orders-table tbody tr').filter(has_text='000000187')
                yield self.act(row.get_by_role('link', name='View Order', exact=True))
                shipping = page.locator('.box-order-shipping-method .box-content').inner_text().strip()
                self.record('shipping_method', shipping)
                yield self.finish([] if self.negative else [shipping])
        elif task == 274:
            yield self.act(page.locator('#search'), 'fill', 'usb wifi')
            yield self.act(page.locator('#search'), 'press', 'Enter')
            self.record('search_results', {'url': page.url})
            if self.negative:
                yield self.act(page.locator('a.logo'))
            yield self.finish()
        elif task == 386:
            yield self.act(page.locator('#search'), 'fill', 'UGREEN')
            yield self.act(page.locator('#search'), 'press', 'Enter')
            link = page.locator('.product-item-link').filter(has_text=re.compile('Lightning.*3.5', re.I)).first
            for _ in range(10):
                if link.count():
                    break
                yield self.act(page.locator('.pages-item-next a:visible').first)
            yield self.act(link)
            rating = float(page.locator('.product-reviews-summary .rating-result [itemprop="ratingValue"]').inner_text())
            self.record('product_rating', {'title':page.locator('h1').inner_text(),'rating_percent':rating})
            yield self.finish([] if self.negative else [rating])
        elif task == 399:
            yield self.act(page.get_by_role('button', name='MarvelsGrantMan136', exact=True))
            yield self.act(page.get_by_role('link', name='Profile', exact=True))
            yield self.act(page.get_by_role('link', name='Edit biography', exact=True))
            value = 'Wrong biography for negative validation' if self.negative else 'I am a robot'
            yield self.act(page.locator('textarea'), 'fill', value)
            yield self.act(page.get_by_role('button', name='Save', exact=True))
            yield self.act(page.get_by_role('link', name='/u/MarvelsGrantMan136', exact=True))
            assert page.get_by_role('complementary').get_by_text(value, exact=True).is_visible()
            self.record('persisted_biography', {'value':value})
            yield self.finish()
        elif task == 404:
            yield from self.forum('books')
            yield self.act(page.get_by_role('button', name='Sort by: Hot', exact=True))
            yield self.act(page.get_by_role('link', name='New', exact=True))
            first = page.locator('.submission').first
            self.record('newest_post_before_vote', first.inner_text())
            name = 'Downvote' if self.negative else 'Upvote'
            yield self.act(first.get_by_role('button', name=name, exact=True))
            self.record('newest_post_after_vote', first.inner_text())
            yield self.finish()
        elif task == 595:
            yield from self.forum('space')
            first = page.locator('.submission').first
            # The comments link opens the original post even if its title is an external image.
            yield self.act(first.locator('a[href^="/f/space/"]').filter(has_text=re.compile('comment', re.I)).first)
            name = re.compile('^Unsubscribe') if self.negative else re.compile('^Subscribe')
            yield self.act(page.get_by_role('button', name=name))
            self.record('subscription_state', page.get_by_role('complementary').inner_text())
            yield self.finish()
        elif task == 640:
            yield from self.forum('books')
            yield self.act(page.get_by_role('link', name='Submit', exact=True))
            title = 'Wrong title for negative validation' if self.negative else 'book reading Meet up!'
            yield self.act(page.locator('#submission_title'), 'fill', title)
            yield self.act(page.locator('#submission_body'), 'fill', 'virtual meetup for book reading on March 15th')
            yield self.act(page.get_by_role('button', name='Create submission', exact=True))
            self.record('created_post', {'title':title,'url':page.url})
            assert page.get_by_role('heading', name=title, exact=True).is_visible()
            yield self.finish()
        elif task == 731:
            yield self.act(page.get_by_role('button', name='MarvelsGrantMan136', exact=True))
            yield self.act(page.get_by_role('link', name='Profile', exact=True))
            yield self.act(page.get_by_role('link', name='Nvidia RTX 4090', exact=True))
            yield self.act(page.get_by_role('link', name='Edit', exact=True))
            original = page.locator('#submission_body').input_value()
            # Preserve the original body; replace our prior validation line for the paired negative.
            base = original.split('\nEDIT:')[0]
            value = base + ('\nEDIT: incorrect validation line' if self.negative else '\nEDIT: This news aged well')
            yield self.act(page.locator('#submission_body'), 'fill', value)
            yield self.act(page.get_by_role('button', name='Edit submission', exact=True))
            self.record('edited_post', {'original':original,'new':value,'url':page.url})
            assert 'EDIT:' in page.locator('body').inner_text()
            yield self.finish()
        else:
            raise ValueError(task)
