"""Trusted BrowserGym chat ingress; never infer human authority from page text.

Installed after reset, so task-supplied initial messages remain the goal. The
BrowserGym JS binding dynamically calls this callback on its private chat object.
No request thread touches Playwright; the owner thread pumps queued callbacks.
"""
from copy import deepcopy


class HumanChat:
    def __init__(self, chat, trace):
        self.chat, self.trace = chat, trace
        self.saved = chat._js_user_message_received_callback
        self.pending = []
        self.sequence = 0
        self.callback = self.receive
        chat._js_user_message_received_callback = self.callback

    def receive(self, msg):
        if not isinstance(msg, str):
            raise ValueError('Human chat input must be text')
        index = len(self.chat.messages)
        result = self.saved(msg=msg)
        self.sequence += 1
        record = {'sequence': self.sequence, 'source': 'browsergym_private_chat_callback',
                  'chat_index': index, 'message': msg,
                  'timestamp': self.chat.messages[index]['timestamp']}
        self.pending.append(record)
        self.trace.event('human_chat_captured', **record, delivered=False)
        return result

    def enqueue(self, conversation, delivery, step):
        """Bind pending messages; only PolicyDelivery can confirm model delivery."""
        for record in self.pending:
            source = delivery.register('human_message', record['message'], step=step,
                provenance={k: v for k, v in record.items() if k != 'message'})
            conversation.add_human_message(record['message'], source_id=source)
            self.trace.event('human_chat_queued_for_policy', step=step,
                             sequence=record['sequence'], content_id=source)
        self.pending.clear()

    def close(self):
        self.trace.event('human_chat_closed', pending=deepcopy(self.pending),
                         scope='Captured pending messages are not confirmed delivery')
        if self.chat._js_user_message_received_callback == self.callback:
            self.chat._js_user_message_received_callback = self.saved
