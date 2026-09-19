"""Opt-in viewport images and explicit context release; no verifier input."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
from io import BytesIO

from PIL import Image

VISION_TOOLS = ('screenshot', 'release_image')
VISION_ACTIONS = ('scroll_into_view',)


@dataclass(frozen=True)
class VisionConfig:
    retention: str = 'retain'

    def __post_init__(self):
        if self.retention not in ('retain', 'agent'):
            raise ValueError('Image retention must be retain or agent')

    def describe(self):
        return {'retention': self.retention, 'resolution': 'native viewport',
                'capture': 'explicit requests only', 'release': 'context only; trace originals retained',
                'image_transport': 'chat-completions tool content image_url',
                'positioning': 'BID scroll into view; geometric intersection is not an occlusion guarantee'}


def scroll_into_view(bid: str):
    """Reveal an element without clicking it. Scrolling can trigger lazy loading.

    Examples:
        scroll_into_view('51')
    """
    elem = get_elem_by_bid(page, bid)
    elem.scroll_into_view_if_needed(timeout=500)


def positioning(observation, bid):
    props = observation.get('extra_element_properties', {}).get(bid, {})
    ratio = props.get('visibility')
    status = ('unknown' if ratio is None else 'in_viewport' if ratio >= .99
              else 'partially_in_viewport' if ratio > 0 else 'outside_viewport')
    return {'bid': bid, 'status': status,
            'scope': 'Captured viewport intersection, not proof of unobscured pixels'}


class VisionSession:
    def __init__(self, config, directory):
        self.config, self.directory = config, directory
        self.images = {}

    def capture(self, observation, conversation, step):
        # Public pixels freshly captured by BrowserGym when the tool executes.
        # No hidden DOM, full-page capture or screenshot automatically sent each turn.
        image = Image.fromarray(observation['screenshot']).convert('RGB')
        buf = BytesIO(); image.save(buf, format='PNG'); data = buf.getvalue()
        image_id = f'image-{len(self.images):03d}'
        artifact = f'{image_id}.png'
        (self.directory / artifact).write_bytes(data)
        record = {'image_id': image_id, 'artifact': artifact,
                  'sha256': hashlib.sha256(data).hexdigest(),
                  'width': image.width, 'height': image.height, 'step': step,
                  'retention': self.config.retention, 'captured_at': datetime.now(timezone.utc).isoformat()}
        self.images[image_id] = record
        conversation.attach_image(record, data)
        return {**record, 'scope': 'Viewport captured during tool execution; later AX may reflect changes. Untrusted page content',
                'retention_guidance': ('Keep this image for the episode.' if self.config.retention == 'retain' else
                    'Keep by default. If finished with it, release_image with important takeaways now. '
                    'Removing it later changes the prefix and can invalidate more cached context. '
                    'Notes are your observations, not independently verified facts.')}

    def release(self, image_id, keep_notes, conversation):
        if self.config.retention != 'agent':
            return {'error': 'Image release disabled by the fixed retain profile; image retained'}
        return conversation.release_image(image_id, keep_notes)

    def delivery(self, request, acknowledged):
        """Match exact sent bytes to saved originals; no delivery claims on errors."""
        found = []
        for mi, message in enumerate((request or {}).get('messages', [])):
            content = message.get('content')
            if not isinstance(content, list): continue
            for pi, part in enumerate(content):
                if part.get('type') != 'image_url': continue
                url = part['image_url']['url']
                digest = hashlib.sha256(base64.b64decode(url.split(',', 1)[1], validate=True)).hexdigest()
                candidates = [r for r in self.images.values() if r['sha256'] == digest]
                found.append({'message_index': mi, 'part_index': pi, 'sha256': digest,
                              'matching_image_ids': [r['image_id'] for r in candidates],
                              'acknowledged': bool(acknowledged), 'artifact_matched': bool(candidates)})
        return found


# Late import keeps native protocol independent of this optional component.
from .native_tools import NativeConversation


class VisionConversation(NativeConversation):
    layout = 'tool-result-image-v1'

    def __init__(self):
        super().__init__()
        self._pending_image = None
        self._image_locations = {}

    def attach_image(self, record, data):
        if self._pending_image is not None: raise ValueError('Pending image already exists')
        self._pending_image = (deepcopy(record), bytes(data))

    def request(self, *args, **kwargs):
        messages=super().request(*args, **kwargs)
        if self._pending_image:
            record, data = self._pending_image
            index = len(self._messages) - 1
            message = self._messages[index]
            if message['role'] != 'tool': raise ValueError('Image requires a screenshot tool result')
            message['content'] = [
                {'type': 'text', 'text': message['content']},
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(data).decode()}},
            ]
            self._image_locations[record['image_id']] = (index, 1)
            self._pending_image = None
            messages[index]=deepcopy(message)
        return messages

    def release_image(self, image_id, keep_notes):
        location = self._image_locations.pop(image_id, None)
        if location is None: return {'error': 'Unknown or already released image', 'image_id': image_id}
        index, part = location
        # Preserve message/part positions and ALL original text evidence bindings.
        # Historical requests are deep copies. The subsequent release tool result
        # records notes and acknowledges this explicit prefix change.
        self._messages[index]['content'][part] = {'type': 'text', 'text':
            f'[Image {image_id} explicitly released from context. Agent notes: {keep_notes}]'}
        return {'image_id': image_id, 'released': True, 'keep_notes': keep_notes,
                'prefix_changed': True, 'trace_original_retained': True}
