"""Fictional room inventory and availability for the local booking demonstration."""
DAYS = ['Tuesday', 'Wednesday', 'Thursday']
ROOMS = [
    {'id': 'a101', 'name': 'Å101', 'building': 'Ångström', 'capacity': 4, 'equipment': 'Whiteboard',
     'free': [[9, 10], [11, 12], [14, 16]]},
    {'id': 'a204', 'name': 'Å204', 'building': 'Ångström', 'capacity': 6, 'equipment': 'Screen · whiteboard',
     'free': [[10, 12], [13, 15]]},
    {'id': 'e112', 'name': 'E112', 'building': 'Ekonomikum', 'capacity': 4, 'equipment': 'Whiteboard',
     'free': [[9.5, 11], [13, 16]]},
    {'id': 'e203', 'name': 'E203', 'building': 'Ekonomikum', 'capacity': 2, 'equipment': 'Quiet room',
     'free': [[9, 12], [14, 17]]},
    {'id': 'b014', 'name': 'B014', 'building': 'Blåsenhus', 'capacity': 6, 'equipment': 'Screen · whiteboard',
     'free': [[10, 12], [14, 17]]},
]


def minutes(value):
    hour, minute = value.split(':')
    if len(value) != 5 or not hour.isdigit() or not minute.isdigit() or int(minute) not in (0, 30):
        raise ValueError('Choose a half-hour start time')
    return int(hour) * 60 + int(minute)


def free_intervals(room, day):
    # Fixed synthetic week, with different Wednesday/Thursday availability.
    shift = DAYS.index(day) * 30
    return [(int(start * 60) + shift, min(17 * 60, int(end * 60) + shift))
            for start, end in room['free']]


def available(room, day, time, duration, bookings):
    start = minutes(time)
    end = start + duration
    return any(left <= start and end <= right for left, right in free_intervals(room, day)) and not any(
        b.get('room_id') == room['id'] and b['day'] == day
        and start < minutes(b['time']) + b['duration'] and minutes(b['time']) < end
        for b in bookings
    )


def book(value, bookings):
    room = next((r for r in ROOMS if r['id'] == value.get('room_id')), None)
    day, time = value.get('day'), value.get('time')
    if room is None or day not in DAYS or not isinstance(time, str):
        raise ValueError('Choose a room, day and time')
    if str(value.get('duration')) not in ('30', '60') or str(value.get('people')) not in tuple(map(str, range(1, 7))):
        raise ValueError('Choose 30 or 60 minutes and 1–6 people')
    duration, people = int(value['duration']), int(value['people'])
    if people > room['capacity']:
        raise ValueError('The room is too small for this group')
    if not available(room, day, time, duration, bookings):
        raise ValueError('This room is no longer available for the whole interval')
    return {'room_id': room['id'], 'room': room['name'], 'building': room['building'],
            'day': day, 'time': time, 'duration': duration, 'people': people}


def public_rooms(bookings):
    return [{**{k: v for k, v in room.items() if k != 'free'},
             'availability': {day: [f'{minute//60:02d}:{minute%60:02d}' for minute in range(540, 1020, 30)
                                    if available(room, day, f'{minute//60:02d}:{minute%60:02d}', 30, bookings)]
                              for day in DAYS}} for room in ROOMS]


def first_available(building, day, duration, people, bookings):
    for start in range(540, 1020, 30):
        time = f'{start//60:02d}:{start%60:02d}'
        for room in sorted(ROOMS, key=lambda r: r['name']):
            if room['building'] == building and room['capacity'] >= people and available(room, day, time, duration, bookings):
                return book({'room_id': room['id'], 'day': day, 'time': time,
                             'duration': duration, 'people': people}, bookings)
    return None
