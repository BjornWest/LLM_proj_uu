"""Concrete review narratives. Context/attribution labels stay in structured records.

Each authored sentence has one declared aspect/stance. Other aspects are omitted,
not announced as unrated. Second-hand passages retain quoted speaker attribution.
"""
from string import Formatter

SENTENCES={
 'comfort':{
  'positive':(
   'Walked round town in these all Saturday and my feet were still happy when I got home.',
   'Two hours on foot yesterday, no aching soles for once. These are staying in the rotation.',
   'Bought the {size}s for a city break. We barely sat down all weekend and I never wanted to take them off.'),
  'negative':(
   'Fine for the first ten minutes, but after walking around all afternoon I was desperate to get them off.',
   'My feet were aching halfway through our walk along the coast. I ended up wishing I had worn my old pair.',
   'The {size}s felt fine in the shop. Several hours of sightseeing was another story: sore feet by lunchtime.'),
  'neutral':(
   'Did a long walk yesterday. About average for comfort, no better or worse than my old pair.',
   'Wore these all day round town. Nothing remarkable about the comfort either way.',
   'Several miles in, they felt much like any other pair I own. Neither particularly comfy nor uncomfortable.'),
  'mixed':(
   'First half of our day out was fine. By the walk back to the station my feet were aching.',
   'Lovely underfoot on the long riverside path, uncomfortable once we spent a few hours on harder pavements.',
   'One all-day outing was really comfortable; on the next one I kept wanting to take them off.')},
 'heel_rubbing':{
  'positive':(
   'Same story on both long walks this week: a raw patch just above my heel.',
   'Hours of sightseeing left both heels rubbed sore where the back edge sits.',
   'Had to stop and put plasters on my heels halfway through our afternoon walk.'),
  'negative':(
   'A full day walking around the city and not a mark on either heel.',
   'I usually get a sore patch at the back on longer walks. Not with these, even after several hours.',
   'The back edge never rubbed my heels during our long walk on Sunday.'),
  'neutral':(
   'After a couple of long walks I still cannot tell whether the heel contact is something I mind.',
   'There is some contact at the heel on long walks; I have no clear opinion on it yet.',
   'Undecided about the heel area after our all-day outing. Nothing I would call clearly good or bad.'),
  'mixed':(
   'No rubbing on Saturday’s long walk, but a sore heel after Sunday’s.',
   'One heel was fine through our whole afternoon out; the other rubbed by the time we got home.',
   'Some longer walks leave my heels untouched. On others the back edge rubs.')},
 'keyboard_comfort':{
  'positive':(
   'Spent Sunday drafting a report on it. The keys felt nice under my fingers even a few hours in.',
   'I write a lot for work and have settled into this keyboard really easily. My hands are happy with it.',
   'Went for the {keyboard} layout. A couple of long writing sessions later, the keyboard still feels comfortable.'),
  'negative':(
   'Writing up my notes gets uncomfortable surprisingly quickly. I keep reaching for an external keyboard.',
   'My fingers were aching after a couple of hours working on a document. I do not get on with these keys.',
   'Got the {keyboard} layout, but it is the feel of the keys I dislike. Long stretches of writing hurt my hands.'),
  'neutral':(
   'Wrote a few reports on it this week. The keyboard feels fairly ordinary, neither pleasant nor unpleasant.',
   'No strong feelings about the keys after a week of writing on it. About average for me.',
   'I have been using it for work documents. Keyboard comfort is much the same as on my old laptop.'),
  'mixed':(
   'Fine for a few emails. Halfway through a long draft, the keyboard starts to feel uncomfortable.',
   'Some writing sessions feel effortless on these keys; other days my fingers ache after an hour.',
   'I like the keyboard for short notes, less so when I spend the whole morning writing.')},
 'fan_noise':{
  'positive':(
   'Halfway through writing a report the fan spun up loudly enough that I put my headphones on.',
   'Trying to finish a document in a quiet room, with that fan whining away, really got on my nerves.',
   'Only a document open and the fan kept distracting me. I would not want to write in a library with it.'),
  'negative':(
   'Wrote up a whole week’s notes in a quiet room and could barely hear the thing.',
   'The fan stayed unobtrusive while I worked through a long draft. No need to turn the music up.',
   'Worked on documents next to someone studying. Neither of us was bothered by fan noise.'),
  'neutral':(
   'I can hear the fan while working on a document, but I have no strong feelings about the sound.',
   'Fan noise during my writing sessions seems fairly average. It is not a selling point or a particular complaint.',
   'Still undecided about the fan sound after a few evenings writing on it.'),
  'mixed':(
   'Quiet for some writing sessions, distractingly loud for others, with much the same document open.',
   'Most of my draft went fine, then the fan got irritating. It settled down again later.',
   'One evening I barely heard it while writing; the next I wanted headphones to cover the fan.')},
 'pet_acceptance':{
  'positive':(
   'Normally my {pet} sniffs a new food and walks off. This one disappeared from the bowl straight away.',
   'Tried the {recipe} recipe and my {pet} tucked straight in. Clean bowls all week.',
   'No mixing it with the old food to persuade my {pet}. Put it down and it got eaten eagerly.'),
  'negative':(
   'My {pet} sniffed the bowl, looked at me and walked away. Tried again the next day, same result.',
   'The {recipe} recipe has been a complete refusal here. My {pet} leaves it in the bowl.',
   'Bought this hoping for a change, but my {pet} would not eat it. Back to the old food.'),
  'neutral':(
   'My {pet} eats it, with about the same enthusiasm as the old food. No obvious preference either way.',
   'Nothing much changed at mealtimes. My {pet} seems fairly indifferent to the switch.',
   'The {recipe} recipe gets an ordinary reaction here. My {pet} neither seeks it out nor avoids it.'),
  'mixed':(
   'Clean bowl on Monday, untouched on Tuesday. Hard to know whether another pack would get eaten.',
   'My {pet} tucked in at first, then started leaving it. Some meals still go better than others.',
   'The {recipe} recipe is hit and miss with my {pet}: eager one day, refused the next.')},
 'pack_handling':{
  'positive':(
   'Easy to get a portion out without food going all over the counter. Makes mealtimes a bit less fiddly.',
   'The {weight} kg pack is easier to handle than I expected when putting food out.',
   'Opening and handling the pack for each meal has been straightforward. No wrestling with it.'),
  'negative':(
   'Getting a portion out is awkward and I keep spilling food round the bowl.',
   'The {weight} kg pack is a nuisance to handle at feeding time. I keep having to put it down and change my grip.',
   'I find the pack fiddly to open and handle when getting a meal ready.'),
  'neutral':(
   'Handling the pack at mealtimes is unremarkable. Not especially easy or especially awkward.',
   'I have no strong opinion on the packaging after feeding from it for a week.',
   'About as convenient to handle as the packs I normally use. Nothing much to say either way.'),
  'mixed':(
   'Easy enough to portion from when full, much more awkward once I got near the end.',
   'Some meals I get the food out neatly. Other times the pack is a pain to handle.',
   'Opening it was straightforward; handling it without spilling has been less consistent.')},
 'taste_enjoyment':{
  'positive':(
   'Opened one with dinner and really liked it. I would happily get this again.',
   'This went down very nicely. Had another taste the following evening and liked it just as much.',
   'Gave it a try after work. Really enjoyed the flavour, glad I picked it up.'),
  'negative':(
   'A few sips were enough for me. Really did not like the flavour and left the rest.',
   'Opened it with dinner, tried to give it a chance, but the taste just was not for me.',
   'Tasted this last night. I wish I had chosen something else; I did not enjoy it.'),
  'neutral':(
   'Finished my glass, but would not go looking for it. Nothing I particularly loved or hated about the taste.',
   'Tried it with dinner. The flavour left me fairly indifferent.',
   'Had a taste, had another. Still no strong feelings about the flavour either way.'),
  'mixed':(
   'Liked the first few sips, but got tired of the flavour about halfway through.',
   'There are things I like in the taste and things that put me off. Still a mixed bag after a second glass.',
   'Some mouthfuls were lovely; others had a flavour I really did not enjoy.')},
 'bitterness':{
  'positive':(
   'That bitter finish hangs around well after a sip.',
   'Quite a bitter kick at the end. I noticed it from the first mouthful.',
   'Poured a glass and the bitterness was the first thing that hit me.'),
  'negative':(
   'I kept waiting for a bitter kick at the end, but it never showed up.',
   'Did not get any noticeable bitterness when I drank it.',
   'No sharp bitter finish for me, even after a few sips.'),
  'neutral':(
   'Cannot really place the bitterness after trying it. I have no clear view on that part.',
   'I am on the fence about calling it bitter after a glass.',
   'Still unsure what to say about the bitterness, even after another taste.'),
  'mixed':(
   'Barely bitter straight from the fridge, much more so once it warmed up.',
   'Some sips had a bitter edge, others did not seem bitter at all.',
   'I noticed bitterness in my first glass but not in the next one.')},
 'dryness':{
  'positive':(
   'Pretty dry on my palate, especially at the finish.',
   'Had a glass with dinner and it came across as dry to me.',
   'The dry finish was quite noticeable when I tasted it.'),
  'negative':(
   'Did not come across as dry to me at all when I tasted it.',
   'There was enough sweetness in my glass that I would not describe it as dry.',
   'I was expecting dry, but that is not how it tasted to me.'),
  'neutral':(
   'After a glass I still could not decide whether to call it dry.',
   'I cannot place it clearly on dryness from the way it tasted.',
   'No firm opinion on how dry it is after trying it with dinner.'),
  'mixed':(
   'Some sips seemed dry, others noticeably less so.',
   'Dry to me at first, then much less dry later in the glass.',
   'I called the first glass dry, but the next one did not taste that way to me.')},
}

# Optional concrete details. None imply an aspect judgment or repeat a spec table.
DETAILS={
 'footwear':('', 'I went for the {colour} ones.', ''),
 'laptops':('', 'Mine is the {ram} GB RAM / {storage} GB version.', ''),
 'dog_food':('', 'I ordered the {weight} kg pack.', ''),
 'cat_food':('', 'This was the {recipe} recipe.', ''),
 'beer':('', 'Picked up {pack_order} to try.', ''),
 'wine':('', 'Mine was the {vintage} vintage.', ''),
}
SLOT_FIELDS={'size':'size_eu','colour':'colour','keyboard':'keyboard_layout','ram':'ram_gb',
 'storage':'storage_gb','recipe':'recipe','weight':'net_weight_kg','pack_order':'pack_count','vintage':'vintage'}


def render_natural(report,product):
    choice=report['template_choices'];attrs=product['attributes'];family=product['category']
    model=product['name'].split(' — ')[0]
    slots={slot:attrs[field] for slot,field in SLOT_FIELDS.items() if field in attrs}
    if 'pack_count' in attrs:slots['pack_order']='one' if attrs['pack_count']==1 else f'a {attrs["pack_count"]}-pack'
    slots['pet']='dog' if family=='dog_food' else 'cat'
    statements=[SENTENCES[a['aspect_id']][a['stance']][(choice['stance']+i)%3] for i,a in enumerate(report['assessments'])]
    # No explicit marker for an omitted aspect; a complaint-only account can remain
    # unassessed on a different aspect while still being a substantive review.
    detail=DETAILS[family][choice['facts']]
    if detail:statements.insert(0,detail)
    fields=sorted({SLOT_FIELDS[name] for template in statements for _,name,_,_ in Formatter().parse(template) if name in SLOT_FIELDS})
    prose=' '.join(s.format(**slots) for s in statements)
    kind=report['usage_reports'][0]['experience_kind']
    if kind=='hearsay':
        relative=('dad','sister','partner','colleague')[choice['ending']]
        lead=(f'My {relative} bought {model} and sent me this:',f'This is what my {relative} said about their {model}:',
              f'My {relative} tried {model}. Here is what they said:')[choice['intro']]
        prose=lead+' “'+prose+'”'
    elif kind=='actual_use':
        if choice['intro']==1:prose=f'Went for {model}. '+prose
    else:raise ValueError('Natural review templates require substantive actual or second-hand experience')
    return prose,fields
