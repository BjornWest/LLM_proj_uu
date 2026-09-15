"""Offline delivery guards; no running Codex session receives these tests."""
import asyncio
import importlib.util
import json
import types
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("agent_coordination", Path(__file__).resolve().parents[1]/"scripts/agent_coordination.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class Connection:
    def __init__(self, status="active", turn="inProgress", reject=False):
        self.status, self.turn, self.reject = status, turn, reject
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        row = self.sent[-1]
        method = row["method"]
        result = {}
        if method == "thread/read":
            result = {"thread": {"id": "recipient", "status": {"type": self.status},
                                  "canAcceptDirectInput": self.status != "notLoaded"}}
        elif method == "thread/turns/list":
            result = {"data": [{"id": "active-turn", "status": self.turn}]}
        elif method == "turn/steer":
            if self.reject:
                return json.dumps({"id": row["id"], "error": {"message": "active turn changed"}})
            result = {"turnId": "active-turn"}
        return json.dumps({"id": row["id"], "result": result})


class CoordinationTests(unittest.TestCase):
    def run_client(self, connection, *extra):
        websocket = types.SimpleNamespace(unix_connect=lambda *a, **k: connection)
        argv = ["client", "steer", "--thread", "recipient", "--message", "Owner [HOLD-1]: hold the shared file.", *extra]
        with patch.dict("sys.modules", {"websockets": websocket}), patch("sys.argv", argv), patch("builtins.print"):
            asyncio.run(client.main())

    def test_only_active_recipient_gets_one_guarded_message(self):
        connection = Connection()
        self.run_client(connection)
        sends = [r for r in connection.sent if r["method"] == "turn/steer"]
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["params"]["expectedTurnId"], "active-turn")
        self.assertTrue(sends[0]["params"]["clientUserMessageId"])
        self.assertEqual(sends[0]["params"]["threadId"], "recipient")

    def test_idle_unreachable_or_terminal_turn_never_sends(self):
        for state, turn in [("idle", "completed"), ("notLoaded", "inProgress"), ("active", "completed")]:
            with self.subTest(state=state, turn=turn):
                connection = Connection(state, turn)
                with self.assertRaises(RuntimeError):
                    self.run_client(connection)
                self.assertFalse(any(r["method"] == "turn/steer" for r in connection.sent))

    def test_expected_turn_mismatch_never_sends(self):
        connection = Connection()
        with self.assertRaises(RuntimeError):
            self.run_client(connection, "--expected-turn", "old-turn")
        self.assertFalse(any(r["method"] == "turn/steer" for r in connection.sent))

    def test_server_rejection_does_not_retry_resume_or_queue(self):
        connection = Connection(reject=True)
        with self.assertRaises(RuntimeError):
            self.run_client(connection)
        methods = [r["method"] for r in connection.sent]
        self.assertEqual(methods.count("turn/steer"), 1)
        self.assertFalse(any(m.startswith("thread/queue") or m == "thread/resume" for m in methods))


if __name__ == "__main__":
    unittest.main()
