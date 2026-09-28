# Browser-assistant access: first policy survey

Checked 27 September 2026. Scope: user-directed shopping research, saved evaluation traces and possible future training. This is a reading of published policies, not a determination of their legal enforceability or applicable statutory exceptions. No permission requests or new agent trials were made for this survey.

**Main finding:** policies vary, but several now explicitly address AI agents rather than only bulk crawlers. No reviewed source establishes a general hobby-project exemption. A missing restriction is not affirmative permission.

## Comparison sites

| Site / scope | Published position and practical interpretation | Robots observation |
|---|---|---|
| Prisjakt, Sweden | Terms restrict automated collection or analysis of digital content, including AI use, with a limited crawling allowance governed by robots.txt. One-off personal assistance is not expressly exempted. [Terms](https://www.prisjakt.nu/information/anvandarvillkor) | Wildcard exclusions include `/search?*`, `/go-to-shop` and `/redirect.php`. Ordinary product URLs are not blanket-excluded. That distinction does not establish permission for arbitrary automated analysis. [Robots](https://www.prisjakt.nu/robots.txt) |
| PriceRunner, Sweden | Current terms could not be reliably extracted: the attempted terms URL returned a JavaScript shell. Permission remains unresolved. | Search-query routes, results, store redirects and several filtering/API routes are excluded. Ordinary product pages are not blanket-excluded. [Robots](https://www.pricerunner.se/robots.txt) |
| Idealo, UK site | Automated reading of its databases/websites, such as scraping, requires permission. Individual private comparison is permitted, but that does not cancel the automation restriction. [Terms](https://www.idealo.co.uk/legal/terms-conditions) | Retrieval returned 403; rules were not established. |

## Retailers and marketplaces

| Site / scope | Published position and practical interpretation | Evidence limitation |
|---|---|---|
| eBay.com | Current agreement expressly includes buy-for-me agents and LLM-driven bots in automated access requiring prior express permission. The clause covers access for any purpose; adding human purchase approval does not by itself remove it. [Agreement, section 3](https://www.ebay.com/help/policies/member-behavior-policies/user-agreement?id=4259) | Agreement says effective 28 June 2026 for existing users. Other country-site agreements need their own review. |
| Amazon.se | Robots explicitly excludes named shopping/user agents, including GoogleAgent-Shopping, GoogleAgent-Mariner, ChatGPT-User and Claude-User. This shows restrictions can extend beyond training crawlers. [Robots](https://www.amazon.se/robots.txt) | Current retail terms retrieval failed. Named groups are not automatically the applicable group for our custom agent; this is not a complete contractual assessment. Historical PDFs and seller-portal terms were not substituted. |
| Elgiganten.se | Reviewed purchase terms did not establish an explicit browser-agent policy. **Unresolved**, not approved. [Purchase terms](https://www.elgiganten.se/kundtjanst/kopvillkor-elgiganten-se) | Purchase terms may not exhaust website-use rules. Robots retrieval returned 429; no repeated requests were made. |
| POWER.se | Current purchase-terms URL returned a script shell, so automation permission remains unresolved. | Robots excludes search, checkout, account and order routes, among others. [Robots](https://www.power.se/robots.txt) |
| Coolshop.se | No explicit automation clause identified in the reviewed purchase terms. **Unresolved**, not approved. [Terms](https://www.coolshop.se/pages/document/terms-COOLSE/) | Robots retrieval returned 403. Purchase terms alone are incomplete evidence of website-access permission. |
| StockX | Current terms could not be verified in this survey. [Current terms endpoint](https://stockx.com/terms) | An older official 2021 announcement contained automated-access restrictions, but it was not treated as the current global agreement. Robots was also unavailable. |

## Merchant and product reviews

| Site | Published position and practical interpretation | Robots / cooperation route |
|---|---|---|
| Trustpilot | Its March 2026 enforcement policy explicitly lists AI agents accessing/collecting/extracting data as an example of unauthorized scraping. It separately restricts training/development use. This is particularly hard to read as only a bulk-crawler rule. [Policy](https://uk.corporate.trustpilot.com/legal/for-everyone/action-we-take/mar-2026) | Important qualification: robots excludes unknown bots site-wide, but explicitly gives ChatGPT-User and OAI-SearchBot narrower path restrictions. Ordinary `/review/<merchant>` pages are not excluded for those named agents; search, `/reviews/` and several filtered routes are. This is not a blanket ChatGPT block or permission transferable to our agent. [Robots](https://www.trustpilot.com/robots.txt) |
| Tom’s Hardware / Future | Future’s terms broadly restrict automated access and text/data mining, expressly including AI development, training, fine-tuning and validation, subject to non-excludable legal exceptions. [UK terms](https://futureplc.com/terms-and-conditions-uk/) | The [terms selector](https://futureplc.com/terms-conditions/) directs countries outside its specified regional cases to UK terms. Licensing is available through the terms’ contact route. Robots also excludes particular routes and named bots. |
| RTINGS | Terms prohibit screen/database scraping and systematic collection. There is also a personal-use provision; it is not an explicit authorization for browser assistants. [Terms](https://www.rtings.com/company/terms-of-use) | Robots excludes only a few paths, including user reviews and admin. This is a useful example of permissive route rules coexisting with restrictive terms. [Robots](https://www.rtings.com/robots.txt) |
| RunRepeat | No explicit browser-agent permission or prohibition was found in the reviewed legal disclaimer. **Unresolved** for interactive automation. [Disclaimer](https://runrepeat.com/legal-disclaimer) | Robots excludes search, redirects and many filter queries. [Robots](https://runrepeat.com/robots.txt) Separately, RunRepeat advertises lab/fit/editorial data through an API and bulk export, with pricing available on inquiry. That is a concrete cooperation route, not permission to automate its UI. [Data access](https://data.runrepeat.com/) |

## What this means for our project

There are four distinct activities to assess: automated browsing, retaining screenshots/AX/network traces, using those records for evaluation, and using them for training. Permission for one should not be presumed to cover the others. Our existing detailed trace retention means these experiments are not entirely ephemeral, even when the shopping answer is only for one person.

Opening a direct product URL instead of clicking an affiliate redirect can avoid a particular excluded route, but it does not resolve broader restrictions on automated access or analysis. Likewise, passing a challenge is technical access, not evidence of permission. Robots rules are crawler instructions, not access authorization; the protocol itself makes that distinction. [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html)

Traffic is not the only stated concern. Trustpilot describes data integrity and misrepresentation; RTINGS discusses the economics and attribution/context of AI reuse. These are their stated concerns, not a claim that every site has the same motives. [Trustpilot policy](https://uk.corporate.trustpilot.com/legal/for-everyone/action-we-take/mar-2026), [RTINGS membership explanation](https://www.rtings.com/company/revamping-our-membership-program)

For future partnerships, describe the actual small-scale browser-assistant workflow and ask separately about trace retention, evaluation and training. An API agreement might provide useful facts while still leaving browser-UI testing outside its scope. RunRepeat is an unusually concrete lead because its data-access offering already covers much of the footwear information we need.

Synthetic-world development can continue independently. We can model shopping problems and interaction patterns using our own generated content without relying on continued access to any particular live platform. This survey does not assess rights to copy site assets, branding or review text.

## Method and unresolved coverage

Primary official terms/policy pages were reviewed through web research; robots files were retrieved directly where possible. Retrieval failures, script shells and old documents were not interpreted as current permission. “Not found” describes this bounded search, not proof that no additional policy exists. No site in this survey was positively cleared for our complete browser-evaluation-and-training workflow.

Local retrieval metadata and exact available robots bodies are retained under `.local/browser-site-policy-survey-v1/`; the earlier Prisjakt robots capture is under `.local/prisjakt-robots-review-v1/`. These are dated snapshots, not runtime allowlists. No model user-agent identity was impersonated. Recheck before relying on a policy because documents and robots rules change.

Sneakers4U was not classified because its intended exact domain was not established. Country-specific variants, logged-in services, API licenses and enforceability under Swedish/EU law remain outside this initial survey.
