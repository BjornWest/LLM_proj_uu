"""Authoring boundaries: strict settings and no sampling-policy changes."""
import json,subprocess
from pathlib import Path
import pytest
from environments.website_drafts.variation_settings import CONTROLS,validate


def test_browser_and_runtime_share_allowed_explicit_settings():
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run(['node','--input-type=module','-e',"import {variationControls} from './environments/website_drafts/variations.js'; console.log(JSON.stringify(variationControls))"],cwd=root,capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)==CONTROLS


@pytest.mark.parametrize('value',[None,[],{'site':None},{'site':{'selectors':None}},{'cards':{'detail':'unknown'}},{'unknown':{}},{'site':{'unsafe':'buttons'}}])
def test_malformed_settings_reject(value):
    with pytest.raises(ValueError):validate(value)


def test_validation_preserves_caller_isolation():
    original={'site':{'selectors':'buttons'},'product':{'facts':'table'}}
    result=validate(original);result['site']['selectors']='radio';assert original['site']['selectors']=='buttons'
