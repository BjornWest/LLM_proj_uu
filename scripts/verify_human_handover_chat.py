"""BrowserGym chat DOM + native CDP human panel clicks; no model/site task run."""
import argparse,json,socket,threading,time,hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright
from browsergym.core.chat import Chat,get_chatbox_modern,CHATBOX_DIR
from intent_browser.human_handover import HumanHandoverController
from intent_browser.human_handover_ui import HumanHandoverUI


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    c=HumanHandoverController(journal_path=a.output/'events.jsonl')
    c.register('tab-1',title='Verification <script>not HTML</script>',url='https://retailer.example/verify')
    c.register('tab-2',title='Agent research',url='https://other.example/')
    c.handover('tab-1','Please complete verification while I compare another retailer.')
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    human_done=threading.Event();human_error=[]
    with HumanHandoverUI(c) as ui,sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=[f'--remote-debugging-port={port}','--remote-debugging-address=127.0.0.1'])
        page=browser.new_page(viewport={'width':500,'height':800})
        # Retain upstream markup, callback and add_message; only launch differs to
        # permit an independent CDP human client during owner-thread blocking.
        chat=object.__new__(Chat);chat.messages=[];chat.page=page
        page.expose_function('send_user_message',lambda msg:chat._js_user_message_received_callback(msg))
        page.set_content(get_chatbox_modern(CHATBOX_DIR))
        chat.add_message('assistant','I am comparing retailer offers. Please help with verification when requested.')
        attached=ui.attach_chat(page);assert attached['attached'] and not attached['already_attached']
        assert ui.attach_chat(page)['already_attached']
        assert page.locator('#human-handover-controls').count()==1
        page.get_by_role('button',name='Start helping',exact=True).wait_for()
        page.locator('#inputBox').fill('I can help with verification.');page.locator('#inputBox').press('Enter')
        page.wait_for_function('USER_MESSAGE_RECEIVED')
        assert [m['message'] for m in chat.messages if m['role']=='user']==['I can help with verification.']
        baseline=list(chat.messages)
        def human():
            try:
                with sync_playwright() as remote:
                    client=remote.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
                    human_page=client.contexts[0].pages[0]
                    human_page.get_by_role('button',name='Start helping',exact=True).click()
                    human_page.get_by_role('button',name='Finished',exact=True).wait_for()
                    human_page.screenshot(path=str(a.output/'chat-human-active.png'),full_page=False)
                    human_page.get_by_role('button',name='Finished',exact=True).click()
                    human_page.get_by_text('Waiting for fresh inspection by the agent.',exact=True).wait_for()
                    client.close()
            except Exception as exc:human_error.append(str(exc))
            finally:human_done.set()
        thread=threading.Thread(target=human);thread.start()
        # No Playwright owner-thread calls while the independent human acts.
        assert human_done.wait(20),'Human HTTP signal depended on owner thread'
        thread.join();assert not human_error,human_error
        assert c.snapshot()['tabs'][0]['state']=='returned'
        assert c.snapshot()['tabs'][1]['state']=='agent_controlled'
        assert chat.messages==baseline,'Control labels leaked into model-facing chat'
        page.screenshot(path=str(a.output/'chat-returned.png'),full_page=False)
        bad=browser.new_page();bad.set_content('<h1>Not a chat</h1>')
        try:ui.attach_chat(bad)
        except Exception:pass
        else:raise AssertionError('Missing chat must fail')
        bad.close()
        try:ui.attach_chat(bad)
        except ValueError:pass
        else:raise AssertionError('Closed chat must fail')
        browser.close()
    sources=['intent_browser/human_handover.py','intent_browser/human_handover_ui.py',__file__]
    result={'passed':True,'model_calls':0,'attachment':attached,'owner_thread_blocked_during_human_controls':True,
      'scope':'original BrowserGym chat markup/callback; CDP launch for independent human. Shared runner delivery remains separate.',
      'chat_user_messages':1,'controls_added_chat_messages':0,'transitions':len(c.drain()),
      'source_sha256':{s:hashlib.sha256(Path(s).read_bytes()).hexdigest() for s in sources}}
    (a.output/'report.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
