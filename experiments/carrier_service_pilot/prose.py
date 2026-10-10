"""Reusable grounded statement pools; no free-form model calls or hidden fact badges."""
POOLS = {
    ('punctuality', 'positive'): [
        'The parcel arrived on the day they said it would.', 'Delivered on the promised day, with no chasing from me.',
        'It turned up when expected.', 'Delivery was on time.', 'The delivery date held up.',
        'I had it by the promised date.', 'No delays after they received the parcel.', 'They stuck to the delivery date.'],
    ('punctuality', 'negative'): [
        'The parcel arrived {late_duration} late.', 'Delivery slipped by {late_duration}.',
        'I waited {late_duration} beyond the promised delivery date.', 'The promised day came and went without the parcel.',
        'It eventually arrived, {late_duration} late.', 'They missed the delivery date.',
        'The delivery took longer than they had promised.', 'The parcel was late getting here.'],
    ('window', 'positive'): [
        'The driver came during the agreed window.', 'They kept to the time slot.', 'Delivery was within my chosen slot.',
        'The appointment window was respected.', 'The driver arrived between {window}.',
        'I could plan around the delivery slot this time.', 'They came when the booking said they would.',
        'No waiting beyond the booked delivery window.'],
    ('window', 'negative'): [
        'They missed the agreed time slot.', 'The driver came outside the booked window.',
        'I arranged to be there for {window}, but that was not when they came.',
        'The delivery window was not kept.', 'The booked slot did not match when the driver arrived.',
        'Choosing a time slot did not help on this delivery.', 'They did not stick to my chosen window.',
        'I could not rely on the delivery slot.'],
    ('handoff', 'positive'): [
        'They brought the parcel to my apartment door.', 'The driver came upstairs with it.',
        'Delivered to my door rather than left downstairs.', 'It reached the apartment door as promised.',
        'The parcel was handed over at my apartment.', 'No trip downstairs to retrieve this one.',
        'They got it all the way to my door.', 'The driver made it to the right apartment door.'],
    ('handoff', 'negative'): [
        'They left my package in the lobby.', 'I had to go downstairs for a parcel that should have come to my door.',
        'It was left at the building entrance instead of my apartment.', 'The driver stopped at the lobby.',
        'Door delivery turned into a trip downstairs.', 'My parcel never made it past the lobby.',
        'They had access, but still left it downstairs.', 'It was left in the lobby despite the door-delivery service.'],
    ('handling', 'positive'): [
        'The packaging arrived intact.', 'The box was in good condition when it reached me.',
        'No visible damage to the parcel.', 'The packaging looked fine on arrival.',
        'It arrived without a battered box.', 'The parcel was dry and undamaged.',
        'Nothing to complain about with the condition of the packaging.', 'The box survived the journey well.'],
    ('handling', 'negative'): [
        'The box arrived {condition}.', 'The packaging was {condition} by the time it got here.',
        'Not impressed with the {condition} box on arrival.', 'The parcel reached me with {condition} packaging.',
        'I received a {condition} parcel.', 'The outer packaging was damaged on the way here.',
        'The parcel was visibly damaged at delivery.', 'The box did not arrive in good condition.'],
    ('tracking', 'positive'): [
        'Tracking kept up with the parcel.', 'The tracking updates were accurate.',
        'I could follow the delivery without guessing where it was.', 'The tracking page was useful throughout.',
        'The tracking status matched what actually happened.', 'Updates appeared as the parcel moved.',
        'Tracking was clear on this order.', 'No misleading statuses in the tracking.'],
    ('tracking_stale', 'negative'): [
        'Tracking was still showing an old status when the parcel arrived.', 'The tracking page barely kept up.',
        'Tracking stayed stuck on an earlier stage.', 'The updates lagged behind the delivery.',
        'I received the parcel before tracking showed it had arrived.', 'The tracking information was out of date.'],
    ('tracking_false_attempt', 'negative'): [
        'Tracking claimed a delivery attempt, but nobody came at that time.',
        'I was home when tracking said they had tried to deliver; there was no attempt then.',
        'A delivery attempt appeared in tracking even though the driver had not been here.',
        'The attempted-delivery update did not match what happened.',
        'They logged an attempt before anyone actually came to the building.',
        'I got an attempted-delivery status without an actual visit at that time.'],
    ('notification', 'positive'): [
        'The {notification} message came when it was useful.', 'I got the promised {notification} notification.',
        'The {notification} update gave me useful notice.', 'They sent the {notification} message in time.',
        'The {notification} notification worked as promised.', 'I appreciated getting the {notification} message.'],
    ('notification_missing', 'negative'): [
        'The promised {notification} message never came.', 'No {notification} notification, despite the service offering one.',
        'I did not receive the {notification} update.', 'The {notification} message was missing.',
        'They failed to send the promised {notification} notification.', 'I was left without the {notification} message.'],
    ('notification_late', 'negative'): [
        'The {notification} message arrived too late to help.', 'The {notification} update came after the event.',
        'I got the {notification} notification, but only afterwards.', 'The {notification} message lagged behind what happened.',
        'That {notification} update would have been useful earlier.', 'The {notification} notification came too late.'],
    ('collection', 'neutral'): [
        'I collected it from {point_name}.', 'This delivery went to {point_name} for collection.',
        'I picked the parcel up at {point_name}.', 'Collection was at {point_name}.'],
    ('locker', 'positive'): [
        'The locker was available around the clock.', 'No opening hours to work around with the locker.',
        'The 24-hour locker access was convenient.', 'I could collect from the locker at any hour.'],
    ('fallback_retry', 'neutral'): [
        'The first delivery could not be completed; they came back the next day.',
        'After the failed first attempt, they delivered the next day.',
        'It took a second visit after the first handover could not go ahead.'],
    ('fallback_collection', 'neutral'): [
        'After the failed home delivery, the parcel went to {point_name}.',
        'I had to collect from {point_name} after the first home-delivery attempt.',
        'The fallback was collection at {point_name}.'],
}


def statement(observation, rng, uses):
    pool = POOLS[(observation['pool'], observation['sentiment'])]
    weights = [1 / (1 + uses.get(t, 0)) ** 2 for t in pool]
    template = rng.choices(pool, weights)[0]
    uses[template] = uses.get(template, 0) + 1
    return {'aspect': observation['aspect'], 'sentiment': observation['sentiment'],
            'text': template.format(**observation['slots']), 'evidence_ids': observation['evidence_ids'],
            'template_id': f"{observation['pool']}:{observation['sentiment']}:{pool.index(template)}"}


def combine(statements, rng):
    # Keep the shuffled order within each sentiment, and whichever sentiment came
    # first. Context statements lead so they cannot interrupt the contrast.
    sentiments = list(dict.fromkeys(s['sentiment'] for s in statements
                                    if s['sentiment'] != 'neutral'))
    ordered = [s for s in statements if s['sentiment'] == 'neutral']
    for sentiment in sentiments:
        ordered.extend(s for s in statements if s['sentiment'] == sentiment)
    pieces = []
    for i, item in enumerate(ordered):
        text = item['text']
        if i and {ordered[i-1]['sentiment'], item['sentiment']} == {'positive', 'negative'} and rng.random() < .65:
            connector = rng.choice(('But ', 'However, ', 'On the other hand, '))
            text = connector + text[0].lower() + text[1:]
            text = text.replace(' i ', ' I ')
            if text.startswith(connector + 'i '):
                text = connector + 'I ' + text[len(connector)+2:]
        pieces.append(text)
    return ' '.join(pieces)
