import unittest
from unittest.mock import Mock
from intent_browser.background_pages import configure_pages

class BackgroundPagesTests(unittest.TestCase):
 def make_browser(self,after):
  page=Mock(); context=Mock();original=context.new_page
  event=Mock(value=page);event.__enter__=Mock(return_value=event);event.__exit__=Mock(return_value=False)
  context.expect_page.return_value=event
  browser=Mock();browser.new_context.return_value=context;session=browser.new_browser_cdp_session.return_value
  session.send.side_effect=[{'browserContextIds':['old']},{'browserContextIds':after},{'targetId':'target'}]
  return browser,context,original,session,page
 def test_exact_context_background_and_callback(self):
  browser,context,original,session,page=self.make_browser(['old','new'])
  callback=Mock();configure_pages(browser,after_page=callback)
  self.assertIs(browser.new_context(viewport={'width':1280,'height':720}),context)
  self.assertIs(context.new_page(),page)
  original.assert_not_called()
  session.send.assert_called_with('Target.createTarget',{'url':'about:blank','browserContextId':'new','background':True})
  callback.assert_called_once_with(page)
 def test_ambiguous_context_fails_before_target_creation(self):
  for ids in [['old'],['old','new','other']]:
   with self.subTest(ids=ids):
    browser,context,original,session,page=self.make_browser(ids)
    configure_pages(browser)
    with self.assertRaises(RuntimeError):browser.new_context()
    context.close.assert_called_once();original.assert_not_called()
    self.assertEqual(session.send.call_count,2)
 def test_legacy_option_preserves_original_page_call(self):
  browser=Mock();context=browser.new_context.return_value;original=context.new_page
  callback=Mock();configure_pages(browser,background=False,after_page=callback)
  self.assertIs(browser.new_context(),context);result=context.new_page()
  original.assert_called_once_with();callback.assert_called_once_with(result)
  browser.new_browser_cdp_session.assert_not_called()
if __name__=='__main__':unittest.main()
