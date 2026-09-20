"""Standalone zero-model BrowserGym verification through the real runner."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re

from intent_browser.actions import make_action_set
from intent_browser.backend import Completion
from intent_browser.harness import native_tools_profile
from intent_browser.runner import run_episode
from intent_browser.task_finalization import finalize_task_run
from scripts.harness_suite_tasks import scripted_backend
from .tasks import make_task


class Driver:
    def __init__(self, task, holder, *, negative=False, retailer=None):
        self.task, self.holder, self.negative = task, holder, negative
        default = {"AG01":"nordbyte", "AG02":"signalboden", "AG03":"nordbyte",
                   "AG04":"hemteknik", "AG05":"nordbyte"}
        self.retailer = retailer or ("signalboden" if negative and task.contract["id"] == "AG01"
                                    else default.get(task.contract["id"]))
        self.index = 0

    @staticmethod
    def action(locator, name="click", value=None):
        bid = locator.get_attribute("bid", timeout=10_000)
        if not bid:
            raise ValueError("Scripted target has no BrowserGym bid")
        return f"{name}({bid!r})" if value is None else f"{name}({bid!r}, {value!r})"

    def complete(self, messages):
        page = self.holder["env"].unwrapped.page
        task_id = self.task.contract["id"]
        i = self.index
        self.index += 1
        product_id = self.task.contract["start_product_id"]
        product = next(row for row in self.task.catalog["products"] if row["id"] == product_id)
        if i == 0:
            return Completion(self.action(page.get_by_role("searchbox", name="Sök produkter"),
                                          "fill", product["name"]), {})
        if i == 1:
            return Completion(self.action(page.get_by_role("button", name="Sök", exact=True)), {})
        if i == 2:
            href = f'/products/{product_id}'
            link = page.locator(f'a[href="{href}"]').filter(has_text=product["name"]).first
            return Completion(self.action(link), {})
        if task_id == "AG06":
            answer = "Nordbyte | 2499.00" if self.negative else "Signalboden | 2449.00"
            return Completion(f"send_msg_to_user({answer!r})", {})
        i -= 3
        names = {"nordbyte":"Nordbyte", "hemteknik":"Hemteknik", "signalboden":"Signalboden"}
        if i == 0:
            code = self.action(page.get_by_role("link", name="Till " + names[self.retailer], exact=True))
        elif i == 1:
            target = (page.get_by_role("dialog", name="MeshLink AX6000")
                      if self.retailer == "hemteknik" else page)
            add_label = "Lägg i varukorgen" if self.retailer == "signalboden" else "Lägg i varukorg"
            code = self.action(target.get_by_role("button", name=add_label, exact=True))
        elif self.retailer == "hemteknik" and task_id == "AG04" and i == 2:
            code = self.action(page.locator("#cart-content").get_by_label("Extra trygghet"),
                               "select_option", "")
        elif self.retailer == "hemteknik" and task_id == "AG04" and i == 3:
            code = self.action(page.get_by_role("button", name="Gå till kassan", exact=True))
        elif self.retailer == "hemteknik" and task_id == "AG04" and i == 4:
            code = self.action(page.get_by_role("button", name="Bekräfta simulerat köp", exact=True))
        elif i == 2:
            if self.retailer == "nordbyte":
                code = self.action(page.get_by_role("button", name=re.compile(r"^Varukorg(?:\s+\d+)?$")))
            else:
                code = self.action(page.get_by_role("link", name=re.compile(r"^Varukorg(?:\s+\d+)?$")))
        elif task_id == "AG05" and i == 3:
            code = self.action(page.get_by_label("Extra garanti"), "select_option", "warranty-24")
        elif self.retailer == "nordbyte" and i == (4 if task_id in ("AG04", "AG05") else 3):
            code = self.action(page.get_by_role("button", name="Till kassan", exact=True))
        else:
            submit_index = (5 if self.retailer == "nordbyte" and task_id == "AG05" else
                            4 if self.retailer == "nordbyte" else 3)
            if i == submit_index:
                code = self.action(page.get_by_role("button", name="Slutför simulerat köp", exact=True))
            else:
                code = "send_msg_to_user('Done')"
        return Completion(code, {})


def run_case(task_id: str, output: Path, *, negative=False, retailer=None):
    system_libs = Path(__file__).resolve().parents[3] / ".local/system-libs/usr/lib/x86_64-linux-gnu"
    os.environ["LD_LIBRARY_PATH"] = str(system_libs) + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    output.mkdir(parents=True, exist_ok=False)
    task = make_task(task_id)
    holder = {}
    driver = Driver(task, holder, negative=negative, retailer=retailer)
    backend = scripted_backend(driver)
    def factory(video):
        holder["env"] = task.make_env(video, action_mapping=make_action_set().to_python_code)
        return holder["env"]
    try:
        # Origins become available in prepare(), before environment creation.
        profile_holder = {}
        original_prepare = task.prepare
        def prepare(trace):
            record = original_prepare(trace)
            profile_holder["origins"] = tuple(task.runtime.origins.values())
            return record
        task.prepare = prepare
        # Link clicks handle cross-origin navigation; explicit goto remains disabled.
        trace, summary = run_episode(factory, backend, {"task":"aggregator-trial", "task_id":task_id,
            "driver":"scripted-validation", "model":None, "model_calls":0, "scripted_negative":negative,
            "training_eligible":False}, output=output / "traces", max_steps=10, episode_task=task,
            harness_profile=native_tools_profile(parallel_tool_calls=None, compact_feedback=True,
                                                 reasoning_replay="preserve"),
            observation_text_limit=48000,
            terminal_response_instruction=("After comparing, call send_msg_to_user with the exact requested answer."
                if task_id == "AG06" else "After the simulated order is complete, call send_msg_to_user with text set to 'Done'."))
        authoritative = finalize_task_run(task, trace, summary)
        expected = not negative
        passed = summary["error"] is None and summary["action_error_count"] == 0 and (
            authoritative["evaluation"]["task_completed"] is expected)
        report = {"schema":"aggregator-trial-scripted-case-v1", "task_id":task_id,
                  "negative":negative, "retailer":driver.retailer, "passed":passed,
                  "model_calls":0, "trace":str(trace), "summary":summary,
                  "authoritative":authoritative}
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"task_id":task_id,"negative":negative,"retailer":driver.retailer,
                          "passed":passed,"error":summary["error"],
                          "action_errors":summary["action_error_count"]}), flush=True)
        return passed
    finally:
        task.close()
        backend.client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=[f"AG{i:02d}" for i in range(1, 7)], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--negative", action="store_true")
    parser.add_argument("--retailer", choices=["nordbyte", "hemteknik", "signalboden"])
    args = parser.parse_args()
    if not run_case(args.task, args.output, negative=args.negative, retailer=args.retailer):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
