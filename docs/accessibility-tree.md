# The accessibility tree: what our agent sees

**Our research agent reads a structured text description of the webpage.** Understanding that description helps us judge what information the model had when it chose an action.

## What is an accessibility tree?

A browser keeps a representation of the webpage's elements called the **DOM** (Document Object Model). From it, the browser builds an accessibility tree for assistive technologies such as screen readers. It describes elements by their meaning: a button's name, a field's value, or whether a checkbox is checked. It is called a *tree* because elements can contain other elements—for example, a form contains fields and buttons. [MDN's explanation](https://developer.mozilla.org/en-US/docs/Glossary/Accessibility_tree).

BrowserGym makes this information available to our harness, which turns it into text for the model. You may see it abbreviated as **AX tree** in our code and traces.

## A small example

Imagine a checkout page with an optional warranty. A simplified BrowserGym-style observation might look like this:

```text
RootWebArea 'Checkout'
    heading 'Your order'
    StaticText 'Laptop: $629.99'
    [42] checkbox 'Add warranty for $31.50', checked='true'
    [43] button 'Place order'
```

| Part | Meaning |
|---|---|
| `checkbox` / `button` | The element's **role**: what kind of control it is. |
| `'Add warranty for $31.50'` | Its **accessible name**: the label exposed to accessibility tools. |
| `checked='true'` | Its current reported **state**. |
| `[42]` | A BrowserGym element ID that our agent can use to target the control. |
| Indentation | The parent/child structure of the page description. |

Given “Buy the laptop without extras,” the model could propose `uncheck('42')`. Our action parser checks the call, then BrowserGym uses **[Playwright](https://playwright.dev/)**, a browser automation library, to perform the interaction in Chromium. The harness captures another observation so the model can inspect the result.

This is an illustrative example, not a recorded run. Element IDs come from the current page observation; they are not screen coordinates or permanent identifiers to copy between tasks.

## What we send to the model

In the current research harness, each decision includes:

- The user's goal, current URL and latest action error.
- The accessibility tree as text, capped at **16,000 characters**. Longer trees end with a truncation notice.
- The **four most recent actions**, plus the latest search result when optional search is enabled.

The code assembling this input is in [`runner.py`](../intent_browser/runner.py). Screenshots are saved for people to inspect, but this model configuration does not receive them. Task-checker records and expected answers stay outside its input.

## Why this matters for our experiments

**Text and appearance can tell different stories.** A “Best value” label can reach our model as text; a gold border or oversized button does not reach it as an image. An accessible image name may appear, but the picture's pixels are absent. Our text-only runs therefore cannot establish how the agent responds to a purely visual trick.

**The description can be incomplete or misleading.** Poorly labelled controls, missing state information and our length limit can leave the model without useful context. Page content also comes from the website: a message urging the agent to buy an extra does not grant permission from the user.

**An observation captures one moment.** The page can change afterward. When reviewing a mistake, inspect the exact input for that decision, rather than assuming a later screenshot shows what the model knew.

## How to review a run

In the trace viewer, select a step and compare its model input, proposed action and next observation. Ask:

1. Was the relevant control, price or warning actually in the input?
2. Did the action respect the user's goal?
3. What changed, and does the separate task checker confirm the outcome?

The saved `steps.jsonl` links each decision to its observation files and retains its messages. Start with the [group guide's real shopping trace](../data/curation/GROUP_MEETING_HANDOUT.md#a-short-real-trace-to-show-the-group) for a concrete example.

[Back to the project overview](../README.md)
