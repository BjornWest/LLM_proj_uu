"""Read-only loopback authoring server; never register as a policy storefront."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .catalog import catalog
from .generator import MEMORY_MODES, QUERY_PRESETS, generate
from .semantics import review_catalog
from .clarification import answer_clarification


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.respond(200, Path(__file__).with_name("preview.html").read_bytes(), "text/html; charset=utf-8")
            elif parsed.path == "/api/catalog":
                self.respond_json(200, {"families": catalog(), "queries": list(QUERY_PRESETS), "memories": MEMORY_MODES, "semantic_review": review_catalog()})
            elif parsed.path in ("/api/generate", "/api/clarify"):
                params = parse_qs(parsed.query, keep_blank_values=True)
                allowed = {"seed", "family", "query", "memory", "requirements", "target", "prose_seed", "budget_sek", "hidden"}
                if parsed.path == "/api/clarify":
                    allowed |= {"line_id", "field"}
                if set(params) - allowed or any(len(v) != 1 for v in params.values()):
                    raise ValueError("Unknown or duplicate parameter")
                kwargs = {k: v[0] for k, v in params.items() if v[0] != ""}
                for k in ("seed", "requirements", "prose_seed", "budget_sek"):
                    if k in kwargs:
                        kwargs[k] = int(kwargs[k])
                if parsed.path == "/api/clarify":
                    line_id, field = kwargs.pop("line_id", None), kwargs.pop("field", None)
                    self.respond_json(200, answer_clarification(generate(**kwargs), line_id, field))
                else:
                    self.respond_json(200, generate(**kwargs))
            else:
                self.respond_json(404, {"error": "Not found"})
        except (ValueError, KeyError) as e:
            self.respond_json(400, {"error": str(e)})

    def respond_json(self, code, data):
        self.respond(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def respond(self, code, data, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)


def serve(port=8876):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Shopping intent authoring: http://localhost:{server.server_port}/", flush=True)
    server.serve_forever()
