"""Privileged snapshot of existing draft controls; never projected to policy."""
def fields(page):
 result={}
 for key,selector in [('message_draft','#new-message-input'),('alert_email','input[placeholder="your.email@example.com"]')]:
  node=page.locator(selector);result[key]=node.input_value() if node.count() else None
 node=page.locator('.ant-select-selection-item');result['alert_frequency']=node.first.inner_text() if '/news/alerts' in page.url and node.count() else None
 return result
