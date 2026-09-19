import unittest
from data.curation.expansion.webarena.batch03_driver import qualifying_comment_count


class CommentCountTest(unittest.TestCase):
    def test_counts_only_negative_other_author(self):
        rows = [{'id':'a','author':'other','score':'\u22122'},
                {'id':'b','author':'poster','score':'-20'},
                {'id':'c','author':'third','score':'0'},
                {'id':'d','author':'fourth','score':'3'}]
        self.assertEqual(qualifying_comment_count(rows,'poster'),1)

    def test_empty_comments(self):
        self.assertEqual(qualifying_comment_count([],'poster'),0)

    def test_unknown_score_and_duplicate_fail_closed(self):
        for rows in [[{'id':'a','author':'other','score':'unknown'}],
                     [{'id':'a','author':'other','score':'-1'}]*2]:
            with self.subTest(rows=rows),self.assertRaises(AssertionError):
                qualifying_comment_count(rows,'poster')
