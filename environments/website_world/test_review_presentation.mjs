// Small renderer/handler controls. Fake DOM verifies plumbing, not AX/browser.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('./review_presentation.js',import.meta.url),'utf8');
const {renderReviews,appendMore} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const e = value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const corpus = {rating_summary:{average_rating:4.7,rating_count:10,written_review_count:5,rating_only_count:5},
  reviews:Array.from({length:10},(_,i)=>({review_id:`review-${i}`,reviewer:`Reviewer ${i}`,sku_id:`sku-${i%2}`,rating:i===1?5:4,
    text:i<5?(i===1?'Very slippery on wet paths.':'<script>not executable</script>'):' '}))};
// Native rating-only records use an empty string, not whitespace.
for(const r of corpus.reviews.slice(5))r.text='';
const product={id:'page',reviewCorpus:corpus}, settings={mode:'paged',initialCount:2,batchSize:2};
const original=JSON.stringify(product);
const first=renderReviews(product,{e},settings);
assert.equal((first.match(/<article /g)||[]).length,2);
assert(first.includes('4.7 / 5 from 10 ratings. 5 written reviews; 5 ratings without comments.'));
assert(first.includes('Very slippery on wet paths.')&&first.includes('Reviewer 1 · 5 / 5'));
assert(first.includes('&lt;script&gt;not executable&lt;/script&gt;')&&!first.includes('<script>'));
assert(first.includes('aria-controls="customer-comments-page"'));
const appended=[], counter={textContent:''};
const section={dataset:{customerReviewProduct:'page'},querySelector(selector){return selector==='[data-review-list]'?
  {insertAdjacentHTML(position,html){assert.equal(position,'beforeend');appended.push(html);}}:counter;}};
const button={isConnected:true,closest(){return section;},remove(){this.isConnected=false;}};
assert(appendMore(button));assert.equal(counter.textContent,'Showing 4 of 5 written comments.');
assert(button.isConnected);assert(appendMore(button));assert.equal(counter.textContent,'Showing 5 of 5 written comments.');
assert(!button.isConnected);assert.equal(appendMore(button),false);
const all=first+appended.join('');
for(let i=0;i<5;i++)assert.equal((all.match(new RegExp(`data-review-id="review-${i}"`,'g'))||[]).length,1);
for(let i=5;i<10;i++)assert(!all.includes(`data-review-id="review-${i}"`));
const again=renderReviews(product,{e},settings);
assert.equal((again.match(/<article /g)||[]).length,5);assert(!again.includes('data-review-load-more'));
assert.equal(JSON.stringify(product),original);
const inline=renderReviews({...product,id:'inline-page'},{e},{mode:'inline'});
assert.equal((inline.match(/<article /g)||[]).length,5);assert(!inline.includes('data-review-load-more'));
assert.equal(renderReviews({id:'missing'},{e},settings),'');
const empty=renderReviews({id:'empty',reviewCorpus:{...corpus,reviews:[]}},{e},settings);
assert(empty.includes('No written comments are recorded.')&&!empty.includes('data-review-load-more'));
console.log(JSON.stringify({passed:true,checks:['native summary unchanged','initial two comments','high stars plus negative text retained',
  'escaped content','two progressive batches','exact-once native IDs','rating-only rows stay in aggregate','progress survives rerender',
  'complete inline mode','absent corpus omitted','no empty load-more control'],scope:'Pure renderer and fake-DOM controls, no browser/AX evidence'}));
