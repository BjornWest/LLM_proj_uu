"""Sparse Codex coordination; no automatic resume, queue fallback, or retries.

Use workstation python3 (websockets installed), not the BrowserGym virtualenv.
See docs/agents/coordination.md. Acceptance is not a read acknowledgment.
"""
import argparse, asyncio, json, uuid

SOCKET = "/home/bjorn/.codex/app-server-control/app-server-control.sock"

async def main():
    import websockets
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["status", "steer"])
    parser.add_argument("--thread")
    parser.add_argument("--message")
    parser.add_argument("--expected-turn")
    args = parser.parse_args()
    async with websockets.unix_connect(SOCKET, uri="ws://localhost/rpc", compression=None,
                                       max_size=32*1024*1024, open_timeout=5) as ws:
        sequence = 0
        async def call(method, params):
            nonlocal sequence
            sequence += 1
            await ws.send(json.dumps({"id": sequence, "method": method, "params": params}))
            async with asyncio.timeout(15):
                while True:
                    row = json.loads(await ws.recv())
                    if row.get("id") == sequence:
                        if "error" in row:
                            raise RuntimeError(json.dumps(row["error"]))
                        return row["result"]
        await call("initialize", {"clientInfo": {"name": "coordination_probe", "version": "1"},
                                  "capabilities": {"experimentalApi": True}})
        await ws.send(json.dumps({"method": "initialized"}))
        if not args.thread:
            if args.command != "status": parser.error("--thread is required")
            result = await call("thread/list", {"cwd": "/home/bjorn/code/LLM_proj_uu", "limit": 20,
                                                "sortKey": "updated_at", "useStateDbOnly": True})
            for thread in result["data"]:
                print(json.dumps({k: thread.get(k) for k in ["id", "name", "status", "canAcceptDirectInput"]}))
            return
        thread = (await call("thread/read", {"threadId": args.thread, "includeTurns": False}))["thread"]
        summary = {k: thread.get(k) for k in ["id", "name", "status", "canAcceptDirectInput"]}
        if args.command == "status":
            print(json.dumps(summary))
            return
        if not args.message or len(args.message.split()) > 80:
            parser.error("--message must contain 1–80 words")
        if thread["status"]["type"] != "active" or not thread.get("canAcceptDirectInput"):
            raise RuntimeError("Not an active reachable thread: " + json.dumps(summary))
        turns = await call("thread/turns/list", {"threadId": args.thread, "limit": 1, "itemsView": "summary"})
        if not turns["data"] or turns["data"][0]["status"] != "inProgress":
            raise RuntimeError("Current active turn unavailable; no message sent")
        active = turns["data"][0]["id"]
        if args.expected_turn and args.expected_turn != active:
            raise RuntimeError("Active turn changed; no message sent")
        message_id = str(uuid.uuid4())
        result = await call("turn/steer", {"threadId": args.thread, "expectedTurnId": active,
                                           "clientUserMessageId": message_id,
                                           "input": [{"type": "text", "text": args.message, "text_elements": []}]})
        print(json.dumps({"accepted": result, "message_id": message_id, "expected_turn_id": active,
                          "read_acknowledged": False}))

if __name__ == "__main__":
    asyncio.run(main())
