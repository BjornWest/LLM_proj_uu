"""Adversarial checker tests: correct HTTP alone must never establish conformance."""
import pytest
from .conformance import Document,product_check,quote_check,review_check,run

P={'product_id':'sku-a','name':'Laptop A','category':'laptops','attributes':{'ram_gb':16}}
O={'offer_id':'offer-a','product_id':'sku-a','price_minor':12345,'stock_quantity':3}
G={'axes':[{'field':'ram_gb'}]}
PRODUCT='''<main><h2>Laptop A</h2><strong id="selected-sku">sku-a</strong><select name="option_ram_gb"><option value="ram-16" selected>16 GB</option></select><table class="fact-table"><tr><th>RAM</th><td>16 GB</td></tr></table><section aria-label="Offer"><p class="price">123.45 SEK per unit</p><p>Online warehouse stock: 3</p></section></main>'''


@pytest.mark.parametrize('old,new',[('sku-a','sku-b'),('123.45 SEK','120.45 SEK'),('stock: 3','stock: 4'),('<td>16 GB</td>','<td>32 GB</td>'),('value="ram-16"','value="ram-32"')])
def test_product_corruption_is_rejected(old,new):
    # Labels are canonical schema metadata, not copied from the renderer under test.
    from environments.product_review_sites.data import field_info
    html=PRODUCT.replace('<th>RAM</th>','<th>'+field_info('laptops','ram_gb')[0]+'</th>')
    product_check(Document(html).root,P,O,G,{'ram_gb':'ram-16'})
    with pytest.raises(AssertionError):product_check(Document(html.replace(old,new)).root,P,O,G,{'ram_gb':'ram-16'})


QUOTE='''<section id="offer-quote" data-offer-id="offer-a"><strong>Unavailable</strong><ul><li>insufficient stock</li></ul><dl><dt>Items</dt><dd>246.90 SEK</dd><dt>Shipping</dt><dd id="shipping-total">20.00 SEK</dd><dt>Total</dt><dd id="delivered-total">266.90 SEK</dd></dl><p id="arrival-days">Ready in 4 calendar days after ordering.</p></section>'''
E={'eligible':False,'reason_codes':['insufficient_stock'],'shipping_minor':2000,'total_minor':26690,'ready_days':4}


@pytest.mark.parametrize('old,new',[('Unavailable','Available'),('266.90','246.90'),('20.00','0.00'),('246.90','123.45'),('Ready in 4','Ready in 2'),('insufficient stock','unknown')])
def test_quote_corruption_is_rejected(old,new):
    quote_check(Document(QUOTE).root,E,O,2,'delivery')
    with pytest.raises(AssertionError):quote_check(Document(QUOTE.replace(old,new)).root,E,O,2,'delivery')


ROW={'review_id':'r1','article_id':'m1','reviewer_id':'u1','body':'My sister said these rubbed her heels.'}
REVIEW='''<section id="reader-panel"><article id="r1"><p>Panel member: u1</p><p class="panel-report-body">My sister said these rubbed her heels.</p><a href="/reviews/m1#r1">Permanent link</a></article></section>'''


@pytest.mark.parametrize('old,new',[('her heels.','my heels.'),('Panel member: u1','Panel member: u2'),('/reviews/m1#r1','/reviews/m1#wrong'),('Permanent link','First-hand use')])
def test_review_corruption_or_annotation_leak_rejected(old,new):
    review_check(Document(REVIEW).root,[ROW])
    with pytest.raises(AssertionError):review_check(Document(REVIEW.replace(old,new)).root,[ROW])


def test_evidence_output_never_overwritten(tmp_path):
    (tmp_path/'report.json').write_text('historical')
    with pytest.raises(FileExistsError):run({},tmp_path,tmp_path)
    assert (tmp_path/'report.json').read_text()=='historical'


def test_review_identity_binding_accepts_grouped_order_but_rejects_corruption():
    rows=[dict(ROW,review_id="r2",body="Second",subject={"id":"sku-b"}),
          dict(ROW,subject={"id":"sku-a"})]
    first='<section><a href="/variants/sku-a">sku-a</a>'+REVIEW.split('<section id="reader-panel">')[1].split('</section>')[0]+'</section>'
    second='<section><a href="/variants/sku-b">sku-b</a>'+REVIEW.split('<section id="reader-panel">')[1].split('</section>')[0].replace('r1','r2').replace(ROW['body'],'Second')+'</section>'
    html='<section id="reader-panel">'+first+second+'</section>'
    review_check(Document(html).root,rows)
    for corrupt in (html.replace('Second',ROW['body']),html.replace('sku-b','sku-a'),
                    html.replace(second,''),html.replace('</section>',second+'</section>',1)):
        with pytest.raises(AssertionError):review_check(Document(corrupt).root,rows)
