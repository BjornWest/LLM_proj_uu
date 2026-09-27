"""Bounded local browser acceptance. No model calls; isolated contexts and traces."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys


CASES = [
    ("pet-hybrid", {"family": "dog_food", "memory": "mixed", "requirements": "5", "seed": "7"}),
    ("cheapest-profile", {"family": "laptops", "memory": "profile", "seed": "2"}),
    ("no-memory", {"family": "books", "memory": "none", "seed": "3"}),
    ("fastest-budget", {"family": "phones", "query": "fastest", "budget_sek": "1000"}),
    ("basket", {"family": "drills", "query": "basket"}),
    ("split", {"family": "cat_food", "query": "split_basket"}),
    ("average", {"family": "foundation", "query": "average", "memory": "episodic"}),
    ("override", {"family": "footwear", "memory": "override", "requirements": "5", "seed": "13"}),
    ("sampled-query", {"family": "random", "query": "random", "memory": "auto"}),
    ("hidden-fit", {"family": "footwear", "hidden": "blocker", "memory": "mixed", "requirements": "5"}),
    ("cookware-logic", {"family": "cookware", "hidden": "none", "memory": "mixed", "requirements": "6"}),
]


async def run(url, output):
    from playwright.async_api import async_playwright
    semaphore = asyncio.Semaphore(2)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)

        async def case(name, controls):
            async with semaphore:
                directory = output / name
                directory.mkdir()
                context = await browser.new_context(viewport={"width": 1450, "height": 1050}, accept_downloads=True)
                await context.tracing.start(screenshots=True, snapshots=True, sources=True)
                page = await context.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                try:
                    response = await page.goto(url)
                    assert response.status == 200
                    await page.wait_for_function("document.querySelector('#message').textContent.length > 0")
                    for key, value in controls.items():
                        control = page.locator(f"[name='{key}']")
                        if await control.evaluate("e => e.tagName") == "SELECT":
                            await control.select_option(value)
                        else:
                            await control.fill(value)
                    async with page.expect_response(lambda r: "/api/generate?" in r.url) as pending:
                        await page.get_by_role("button", name="Generate", exact=True).click()
                    response = await pending.value
                    bundle = await response.json()
                    assert response.status == 200, bundle
                    await page.wait_for_function("expected => document.querySelector('#message').textContent === expected", arg=bundle["public"]["user_message"])
                    assert await page.locator("#error").inner_text() == ""
                    assert not errors, errors
                    assert "\n" not in bundle["public"]["user_message"]
                    assert await page.locator("#message .stage").count() == len(bundle["authoring"]["message_segments"])
                    if name == "no-memory":
                        assert await page.locator("#memories").inner_text() == "No relevant memories generated."
                    if name == "fastest-budget":
                        assert bundle["resolved_task"]["constraints"]["budget_minor"] == 100000
                        assert "1000 SEK" in await page.locator("#message").inner_text()
                    if name in ("basket", "split"):
                        assert len(bundle["resolved_task"]["lines"]) == 3
                    if name == "override":
                        assert await page.locator("#message .override").count() > 0
                    if name == "pet-hybrid":
                        assert bundle["public"]["memories"]["profile"] and bundle["public"]["memories"]["episodes"]
                    if name == "hidden-fit":
                        hidden = bundle["hidden_user_specifications"][0]
                        assert await page.locator(".clarification-reply").inner_text() == ""
                        async with page.expect_response(lambda r: "/api/clarify?" in r.url) as answer_info:
                            await page.locator(".clarify").click()
                        answer = await (await answer_info.value).json()
                        assert answer == {"matched": True, "reply": hidden["reply"]}
                        await page.wait_for_function("text => document.querySelector('.clarification-reply').textContent === text", arg=hidden["reply"])
                        assert hidden["predicate"]["field"] == "size_eu"
                    for id, expected in (("download-public", bundle["public"]), ("download", bundle)):
                        async with page.expect_download() as download_info:
                            await page.locator("#" + id).click()
                        download = await download_info.value
                        path = directory / (id + ".json")
                        await download.save_as(path)
                        assert json.loads(path.read_text()) == expected
                    if name == "sampled-query":
                        old_seed = bundle["seed"]
                        async with page.expect_response(lambda r: "/api/generate?" in r.url) as pending:
                            await page.get_by_role("button", name="New random task").click()
                        random_bundle = await (await pending.value).json()
                        assert random_bundle["seed"] != old_seed
                    await page.screenshot(path=str(directory / "preview.png"), full_page=True)
                    (directory / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n")
                    return {"case": name, "passed": True, "page_errors": errors}
                except Exception as e:
                    return {"case": name, "passed": False, "error": str(e), "page_errors": errors}
                finally:
                    await context.tracing.stop(path=str(directory / "trace.zip"))
                    await context.close()

        results = await asyncio.gather(*(case(*c) for c in CASES))
        await browser.close()
    (output / "summary.json").write_text(json.dumps({"url": url, "workers": 2, "cases": results}, indent=2) + "\n")
    print(json.dumps(results))
    return all(r["passed"] for r in results)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    libraries = Path(__file__).resolve().parents[2] / ".local/system-libs/usr/lib/x86_64-linux-gnu"
    if libraries.is_dir():
        os.environ["LD_LIBRARY_PATH"] = str(libraries) + ":" + os.environ.get("LD_LIBRARY_PATH", "")
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "server.log").open("w") as log:
        server = subprocess.Popen([sys.executable, "-m", "environments.shopping_intent", "serve", "--port", "0"],
                                  stdout=subprocess.PIPE, stderr=log, text=True)
        try:
            line = server.stdout.readline().strip()
            if not line.startswith("Shopping intent authoring: "):
                raise RuntimeError("Preview server failed to start: " + line)
            url = line.split(": ", 1)[1]
            ok = asyncio.run(run(url, args.output))
        finally:
            server.terminate()
            server.wait(timeout=10)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
