"""Portable multi-origin HTTP runtime for the original aggregator trial.

The public HTTP surface contains ordinary shop APIs only. Grading reads the
in-process TrialState snapshot; no reset, answer, or grading route exists.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.parse import parse_qs, unquote, urlsplit


ROOT = Path(__file__).resolve().parent
RETAILER_IDS = ("nordbyte", "hemteknik", "signalboden")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


class TrialState:
    """Fresh per-run state shared by four isolated listening origins."""

    def __init__(self, catalog_path: Path | None = None):
        self.catalog = json.loads((catalog_path or ROOT / "catalog.json").read_text())
        self.products = {row["id"]: row for row in self.catalog["products"]}
        self.retailers = {row["id"]: row for row in self.catalog["retailers"]}
        self.offers = {}
        for row in self.catalog["offers"]:
            row = deepcopy(row)
            row["offer_id"] = f'{row["retailer"]}:{row["product_id"]}'
            self.offers[row["offer_id"]] = row
        homepage = self.catalog.get("homepage", {})
        homepage_ids = homepage.get("product_ids")
        if (not isinstance(homepage_ids, list) or not homepage_ids
                or len(homepage_ids) != len(set(homepage_ids))
                or any(product_id not in self.products for product_id in homepage_ids)):
            raise ValueError("Catalog homepage.product_ids must be unique known products")
        self.carts: dict[tuple[str, str], dict] = {}
        self._orders: list[dict] = []
        self._events: list[dict] = []
        self._lock = threading.RLock()

    def public_offer(self, offer: dict) -> dict:
        product = self.products[offer["product_id"]]
        return {"offer_id": offer["offer_id"], **deepcopy(product), "product_id": product["id"],
                "unit_price_ore": offer["unit_price_ore"], "shipping_ore": offer["shipping_ore"],
                "stock": offer["stock"], "delivery": offer["delivery"],
                "warranties": deepcopy(offer.get("warranties", [])), "image": "/assets/product.svg"}

    def catalog_for(self, retailer: str, query: dict[str, list[str]]) -> dict:
        q = query.get("q", [""])[0].strip().casefold()
        category = query.get("category", [""])[0].strip().casefold()
        product_id = query.get("product_id", [""])[0]
        rows = []
        for offer in self.offers.values():
            if offer["retailer"] != retailer:
                continue
            product = self.products[offer["product_id"]]
            haystack = " ".join(str(product.get(k, "")) for k in
                                ("name", "brand", "model", "variant", "capacity", "category", "description")).casefold()
            if q and q not in haystack:
                continue
            if category and product["category"].casefold() != category:
                continue
            if product_id and product["id"] != product_id:
                continue
            rows.append(self.public_offer(offer))
        return {"categories": sorted({p["category"] for p in self.products.values()}), "offers": rows}

    def _cart(self, session: str, retailer: str) -> dict:
        return self.carts.setdefault((session, retailer), {"items": [], "extras": []})

    def cart_view(self, session: str, retailer: str) -> dict:
        with self._lock:
            cart = deepcopy(self._cart(session, retailer))
            items = []
            for line in cart["items"]:
                offer = self.offers[line["offer_id"]]
                product = self.products[offer["product_id"]]
                items.append({"line_id": line["line_id"], "offer_id": offer["offer_id"],
                              "product_id": product["id"], "name": product["name"], "model": product["model"],
                              "variant": product["variant"], "capacity": product["capacity"],
                              "quantity": line["quantity"], "unit_price_ore": offer["unit_price_ore"]})
            shipping = max((self.offers[row["offer_id"]]["shipping_ore"] for row in cart["items"]), default=0)
            subtotal = sum(row["unit_price_ore"] * row["quantity"] for row in items)
            extras = deepcopy(cart["extras"])
            extras_total = sum(row["price_ore"] for row in extras)
            return {"items": items, "extras": extras, "shipping_ore": shipping,
                    "subtotal_ore": subtotal, "extras_ore": extras_total,
                    "delivered_ore": subtotal + shipping + extras_total}

    def add_item(self, session: str, retailer: str, data: dict) -> dict:
        offer_id, quantity = data.get("offer_id"), data.get("quantity")
        offer = self.offers.get(offer_id)
        if not offer or offer["retailer"] != retailer:
            raise ApiError(404, "unknown_offer", "Erbjudandet finns inte i denna butik")
        if type(quantity) is not int or quantity <= 0:
            raise ApiError(400, "invalid_quantity", "Antalet måste vara ett positivt heltal")
        if offer["stock"] == "out_of_stock":
            raise ApiError(409, "unavailable", "Varan är inte i lager")
        with self._lock:
            cart = self._cart(session, retailer)
            existing = next((row for row in cart["items"] if row["offer_id"] == offer_id), None)
            if existing:
                existing["quantity"] += quantity
            else:
                cart["items"].append({"line_id": secrets.token_hex(6), "offer_id": offer_id, "quantity": quantity})
            if offer.get("preselect_warranty") and not any(x["offer_id"] == offer_id for x in cart["extras"]):
                self._set_warranty(cart, offer, offer["preselect_warranty"])
            self._events.append({"kind": "cart_add", "session": session, "retailer": retailer,
                                 "offer_id": offer_id, "quantity": quantity})
        return self.cart_view(session, retailer)

    def update_item(self, session: str, retailer: str, line_id: str, quantity: int) -> dict:
        if type(quantity) is not int or quantity < 0:
            raise ApiError(400, "invalid_quantity", "Antalet måste vara noll eller ett positivt heltal")
        with self._lock:
            cart = self._cart(session, retailer)
            line = next((row for row in cart["items"] if row["line_id"] == line_id), None)
            if not line:
                raise ApiError(404, "unknown_line", "Varukorgsraden finns inte")
            if quantity == 0:
                cart["items"].remove(line)
                cart["extras"] = [x for x in cart["extras"] if x["offer_id"] != line["offer_id"]]
            else:
                line["quantity"] = quantity
            self._events.append({"kind": "cart_update", "session": session, "retailer": retailer,
                                 "line_id": line_id, "quantity": quantity})
        return self.cart_view(session, retailer)

    def remove_item(self, session: str, retailer: str, line_id: str) -> dict:
        return self.update_item(session, retailer, line_id, 0)

    @staticmethod
    def _set_warranty(cart: dict, offer: dict, warranty_id: str | None):
        warranty = None
        if warranty_id is not None:
            warranty = next((x for x in offer.get("warranties", []) if x["id"] == warranty_id), None)
            if warranty is None:
                raise ApiError(400, "unknown_warranty", "Garantin finns inte för denna vara")
        # Rejected replacements must preserve the prior selection.
        cart["extras"] = [x for x in cart["extras"] if x["offer_id"] != offer["offer_id"]]
        if warranty is None:
            return
        cart["extras"].append({"id": warranty["id"], "kind": "warranty", "name": warranty["name"],
                               "offer_id": offer["offer_id"], "price_ore": warranty["price_ore"]})

    def set_warranty(self, session: str, retailer: str, data: dict) -> dict:
        offer = self.offers.get(data.get("offer_id"))
        if not offer or offer["retailer"] != retailer:
            raise ApiError(404, "unknown_offer", "Erbjudandet finns inte i denna butik")
        with self._lock:
            cart = self._cart(session, retailer)
            if not any(x["offer_id"] == offer["offer_id"] for x in cart["items"]):
                raise ApiError(409, "offer_not_in_cart", "Lägg varan i varukorgen först")
            self._set_warranty(cart, offer, data.get("warranty_id"))
            self._events.append({"kind": "warranty_set", "session": session, "retailer": retailer,
                                 "offer_id": offer["offer_id"], "warranty_id": data.get("warranty_id")})
        return self.cart_view(session, retailer)

    def checkout(self, session: str, retailer: str, data: dict) -> dict:
        customer = data.get("customer")
        required = ("name", "email", "address", "postal_code", "city")
        if not isinstance(customer, dict) or any(not str(customer.get(k, "")).strip() for k in required):
            raise ApiError(400, "missing_customer", "Fyll i alla kunduppgifter")
        with self._lock:
            cart = self.cart_view(session, retailer)
            if not cart["items"]:
                raise ApiError(409, "empty_cart", "Varukorgen är tom")
            if any(self.offers[x["offer_id"]]["stock"] == "out_of_stock" for x in cart["items"]):
                raise ApiError(409, "unavailable", "En vara är inte längre i lager")
            receipt = {"order_id": "SIM-" + secrets.token_hex(4).upper(), "retailer": retailer,
                       "customer": {k: str(customer[k]).strip() for k in required}, **cart,
                       "notice": "Simulerat köp — ingen betalning har genomförts"}
            stored = deepcopy(receipt)
            stored["_session"] = session
            self._orders.append(stored)
            self._events.append({"kind": "checkout", "session": session, "retailer": retailer,
                                 "order_id": receipt["order_id"]})
            self.carts[(session, retailer)] = {"items": [], "extras": []}
            return deepcopy(receipt)

    def order_history(self, session: str, retailer: str) -> dict:
        with self._lock:
            rows = []
            for order in self._orders:
                if order["retailer"] == retailer and order["_session"] == session:
                    row = deepcopy(order)
                    row.pop("_session", None)
                    rows.append(row)
            return {"orders": rows}

    def private_snapshot(self) -> dict:
        with self._lock:
            return {"orders": deepcopy(self._orders), "carts": {f"{k[0]}:{k[1]}": self.cart_view(*k)
                    for k in list(self.carts)}, "events": deepcopy(self._events)}


class Runtime:
    def __init__(self, state: TrialState | None = None, *, ports: dict[str, int] | None = None):
        self.state = state or TrialState()
        self.servers: dict[str, ThreadingHTTPServer] = {}
        self.threads: list[threading.Thread] = []
        try:
            for site in ("aggregator", *RETAILER_IDS):
                handler = self._handler(site)
                server = ThreadingHTTPServer(("127.0.0.1", (ports or {}).get(site, 0)), handler)
                self.servers[site] = server
        except Exception:
            for server in self.servers.values():
                server.server_close()
            raise
        self.origins = {site: f"http://127.0.0.1:{server.server_port}" for site, server in self.servers.items()}
        for server in self.servers.values():
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)

    def _handler(self, site):
        runtime = self
        class Handler(RequestHandler):
            site_id = site
            trial = runtime
        return Handler

    def close(self):
        for server in self.servers.values():
            server.shutdown()
        for server in self.servers.values():
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)


class RequestHandler(BaseHTTPRequestHandler):
    site_id: str
    trial: Runtime
    server_version = "AggregatorTrial/1"

    def log_message(self, format, *args):
        return

    def _session(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        value = cookie.get("AGGTRIAL")
        if value and value.value:
            return value.value, False
        return secrets.token_urlsafe(18), True

    def _json(self, status, body, *, session=None):
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if session:
            self.send_header("Set-Cookie", f"AGGTRIAL={session}; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 100_000:
                raise ValueError
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            raise ApiError(400, "invalid_json", "Ogiltig JSON")

    def _dispatch(self, method):
        parsed = urlsplit(self.path)
        path, query = unquote(parsed.path), parse_qs(parsed.query)
        session, fresh = self._session()
        state = self.trial.state
        if method == "GET" and path == "/assets/product.svg":
            return self._static("/product.svg", ROOT / "assets")
        if self.site_id == "aggregator":
            if method == "GET" and path == "/api/config":
                offers = []
                for offer in state.offers.values():
                    row = state.public_offer(offer)
                    row.update({"retailer": offer["retailer"], "retailer_name": state.retailers[offer["retailer"]]["name"],
                                "retailer_rating": state.retailers[offer["retailer"]]["rating"],
                                "quote_ore": offer["quote_ore"], "quote_note": offer.get("quote_note"),
                                "retailer_url": self.trial.origins[offer["retailer"]] + "/?product_id=" + offer["product_id"]})
                    offers.append(row)
                return self._json(200, {"products": list(state.products.values()), "offers": offers,
                    "retailers": list(state.retailers.values()), "participating_retailers": list(RETAILER_IDS),
                    "homepage": deepcopy(state.catalog["homepage"]),
                    "unavailable_directory_examples": ["Budgethörnan", "KlickTeknik"]}, session=session if fresh else None)
            if method == "GET" and path.startswith("/products/"):
                product_id = path.removeprefix("/products/")
                if not product_id or "/" in product_id or product_id not in state.products:
                    self.send_error(HTTPStatus.NOT_FOUND, "Produkten finns inte")
                    return
                return self._static("/index.html", ROOT / "aggregator")
            return self._static(path, ROOT / "aggregator")
        retailer = self.site_id
        if path == "/api/store" and method == "GET":
            return self._json(200, {**state.retailers[retailer], "currency": "SEK",
                "checkout_notice": "Simulated purchase — no payment is taken"}, session=session if fresh else None)
        if path == "/api/catalog" and method == "GET":
            return self._json(200, state.catalog_for(retailer, query), session=session if fresh else None)
        if path.startswith("/api/offers/") and method == "GET":
            offer = state.offers.get(path.removeprefix("/api/offers/"))
            if not offer or offer["retailer"] != retailer:
                raise ApiError(404, "unknown_offer", "Erbjudandet finns inte")
            return self._json(200, state.public_offer(offer), session=session if fresh else None)
        if path == "/api/cart" and method == "GET":
            return self._json(200, state.cart_view(session, retailer), session=session if fresh else None)
        if path == "/api/orders" and method == "GET":
            return self._json(200, state.order_history(session, retailer), session=session if fresh else None)
        if path == "/api/cart/items" and method == "POST":
            return self._json(200, state.add_item(session, retailer, self._body()), session=session if fresh else None)
        if path.startswith("/api/cart/items/") and method in ("PATCH", "DELETE"):
            line_id = path.removeprefix("/api/cart/items/")
            value = state.remove_item(session, retailer, line_id) if method == "DELETE" else state.update_item(
                session, retailer, line_id, self._body().get("quantity"))
            return self._json(200, value, session=session if fresh else None)
        if path == "/api/cart/warranty" and method == "PUT":
            return self._json(200, state.set_warranty(session, retailer, self._body()), session=session if fresh else None)
        if path == "/api/checkout" and method == "POST":
            return self._json(201, state.checkout(session, retailer, self._body()), session=session if fresh else None)
        if path.startswith("/api/"):
            raise ApiError(404, "not_found", "Sidan finns inte")
        return self._static(path, ROOT / "retailers" / retailer)

    def _static(self, path: str, root: Path):
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (root / relative).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mime = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}.get(target.suffix, "application/octet-stream")
        raw = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _safe(self, method):
        try:
            self._dispatch(method)
        except ApiError as error:
            self._json(error.status, {"error": error.code, "message": error.message})
        except BrokenPipeError:
            pass

    def do_GET(self): self._safe("GET")
    def do_POST(self): self._safe("POST")
    def do_PATCH(self): self._safe("PATCH")
    def do_PUT(self): self._safe("PUT")
    def do_DELETE(self): self._safe("DELETE")
