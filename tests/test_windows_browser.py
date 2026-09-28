import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from intent_browser.windows_browser import StartupCleanup, WindowsChrome
from intent_browser.windows_layout import rectangles, validate_layout, place_page


def page(url='about:blank', empty=True):
    item=Mock()
    item.url=url
    item.is_closed.return_value=False
    item.evaluate.return_value=empty
    return item


class CleanupTests(unittest.TestCase):
    def test_only_original_empty_pages(self):
        with tempfile.TemporaryDirectory() as tmp:
            blank, modified, navigated, existing, agent = [page() for _ in range(5)]
            existing.url='https://example.invalid'
            browser=Mock(contexts=[Mock(pages=[blank, modified, navigated, existing])])
            cleanup=StartupCleanup(browser,tmp)
            modified.evaluate.return_value=False
            navigated.url='https://other.invalid'
            cleanup.after_page(agent)
            blank.close.assert_called_once_with(run_before_unload=False)
            for p in [modified,navigated,existing,agent]: p.close.assert_not_called()
            cleanup.after_page(page())
            blank.close.assert_called_once()
            self.assertTrue(json.loads((Path(tmp)/'windows-startup-cleanup.json').read_text())['agent_page_open'])

    def test_no_replacement_no_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            startup=page(); closed=page();closed.is_closed.return_value=True
            cleanup=StartupCleanup(Mock(contexts=[Mock(pages=[startup])]),tmp)
            cleanup.after_page(startup);cleanup.after_page(closed)
            startup.close.assert_not_called();self.assertFalse(cleanup.attempted)

    def test_error_nonfatal_no_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            startup=page();startup.evaluate.side_effect=RuntimeError('detached')
            cleanup=StartupCleanup(Mock(contexts=[Mock(pages=[startup])]),tmp)
            cleanup.after_page(page());cleanup.after_page(page())
            self.assertEqual(cleanup.results[0]['outcome'],'retained_error')
            startup.evaluate.assert_called_once();startup.close.assert_not_called()

    def test_already_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            startup=page();cleanup=StartupCleanup(Mock(contexts=[Mock(pages=[startup])]),tmp)
            startup.is_closed.return_value=True;cleanup.after_page(page())
            self.assertEqual(cleanup.results[0]['outcome'],'already_closed')

    def test_launcher_close_is_idempotent(self):
        chrome=object.__new__(WindowsChrome)
        chrome._closed=False;chrome.chat_chrome=Mock();child=chrome.chat_chrome
        chrome.powershell=Mock();chrome.start={'pid':123};chrome.listener=Mock();chrome.relays=[]
        chrome.close();chrome.close()
        child.close.assert_called_once();chrome.powershell.assert_called_once();chrome.listener.close.assert_called_once()

    def test_layout_report_does_not_overwrite_input_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/'windows-layout.json';config.write_text('{"display":"test"}')
            chrome=object.__new__(WindowsChrome);chrome.directory=Path(tmp)
            chrome.layout={'display':'test'};chrome.layout_results=[];chrome.powershell=Mock()
            with patch('intent_browser.windows_layout.place_page',return_value={'placed':True}):
                chrome._place(page(),'chat')
            self.assertEqual(config.read_text(),'{"display":"test"}')
            self.assertEqual(json.loads((Path(tmp)/'windows-layout-result.json').read_text()),[{'placed':True}])

    def test_invalid_port_before_launch(self):
        for port in [True,0,65536,'123']:
            with self.subTest(port=port),self.assertRaises(ValueError):WindowsChrome('.',port)


class LayoutTests(unittest.TestCase):
    def test_negative_display_work_area(self):
        self.assertEqual(rectangles({'X':-1920,'Y':-45,'Width':1920,'Height':1032}),
                         {'browser':[-1920,-45,1344,1032],'chat':[-576,-45,576,1032]})

    def test_bottom_work_area_remains_free(self):
        boxes=rectangles({'X':-1920,'Y':-45,'Width':1920,'Height':1032},height_fraction=.8)
        self.assertEqual(boxes['browser'],[-1920,-45,1344,826])
        self.assertEqual(boxes['chat'],[-576,-45,576,826])
        for value in [0,True,1.1,float('nan')]:
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate_layout({'display':'test','height_fraction':value})

    def test_invalid_fraction(self):
        for fraction in [True,0,1,'0.7',float('nan')]:
            with self.subTest(fraction=fraction),self.assertRaises(ValueError):
                validate_layout({'display':'test','browser_fraction':fraction})

    def test_title_restored_after_positioning_failure(self):
        target=page();target.evaluate.return_value='old'
        def fail(script):raise RuntimeError('screen disconnected')
        with self.assertRaises(RuntimeError):place_page(target,'chat',{'display':'test'},fail)
        self.assertEqual(target.evaluate.call_count,2)
        self.assertEqual(target.evaluate.call_args.args[1]['previous'],'old')

if __name__=='__main__':unittest.main()
