"""Adversarial task399: correct biography followed by a persisted wrong overwrite.

Uses the same native v3 runner and original objective. This is a negative browser
case, not an alteration to native grading or to any historical episode.
"""
from data.curation.expansion.webarena import native_case_next as native
from data.curation.expansion.webarena.extra_driver import ExtraDriver


class BiographyHistoryDriver(ExtraDriver):
    def __init__(self, task_id, negative=False):
        if task_id != 399:
            raise ValueError('This history audit covers only original task399')
        super().__init__(task_id, negative=False)

    def steps(self):
        for action in super().steps():
            if not action.startswith('send_msg_to_user('):
                yield action
                continue
            page = self.page
            self.record('correct_before_wrong_overwrite', {'goal_value':'I am a robot'})
            yield self.act(page.get_by_role('link', name='Edit biography', exact=True))
            value = 'Wrong final biography after correct update'
            yield self.act(page.locator('textarea'), 'fill', value)
            yield self.act(page.get_by_role('button', name='Save', exact=True))
            yield self.act(page.get_by_role('link', name='/u/MarvelsGrantMan136', exact=True))
            assert page.get_by_role('complementary').get_by_text(value, exact=True).is_visible()
            assert not page.get_by_role('complementary').get_by_text('I am a robot', exact=True).count()
            self.record('persisted_wrong_final_biography', {'value':value,'goal_completed':False})
            yield self.finish()


if __name__ == '__main__':
    native.ExtraDriver = BiographyHistoryDriver
    native.main()
