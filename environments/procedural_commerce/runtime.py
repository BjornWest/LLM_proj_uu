"""Four-origin loopback HTTP runtime for procedural commerce worlds.

The HTTP surface is deliberately ordinary storefront HTML.  The generated world,
session journal, task constraints, and evaluator remain available only to trusted
in-process callers.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import signal
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, unquote, urlsplit

from .engine import CommerceSession, CommerceValidationError, quote
from . import product_controls as pc
from .generator import aggregator_view, generate_world, retailer_view, world_sha256
from .renderers import render_page
from .presentation import resolve_presentations, SHOWCASE, SHOWCASE_OPTIONS
from .checkout_config import resolve_checkout_flows, CHECKOUT_SHOWCASE


_MAX_BODY_BYTES = 16_384
_MAX_QUERY_BYTES = 8_192
_LAYOUT_VARIANTS = frozenset({"compact", "expanded"})
_PRODUCT_PATH = re.compile(r"/products/([^/]+)\Z")
_DETAILS_PATH = re.compile(r"/products/([^/]+)/details\Z")
_RECEIPT_PATH = re.compile(r"/receipt/([^/]+)\Z")
_PUBLIC_ERRORS = {
    "selection_changed": "Options changed. Review the updated offer before adding it.",
    "invalid_cart": "The cart request could not be completed.",
    "cart_line_limit": (
        "Your cart already has one product line. Remove it before selecting another product."
    ),
    "empty_cart": "Your cart is empty.",
    "ineligible_quote": "This selection is not currently available for checkout.",
    "checkout_failed": "Checkout could not be completed.",
}


@dataclass(frozen=True)
class _HTTPError(Exception):
    status: int
    message: str


class _LoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _strict_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _validate_world(world: object) -> tuple[str, ...]:
    if not isinstance(world, dict):
        raise TypeError("world must be a dict")
    retailers = world.get("retailers")
    if not isinstance(retailers, list) or len(retailers) != 3:
        raise ValueError("world must contain exactly three retailers")
    retailer_ids: list[str] = []
    for retailer in retailers:
        if not isinstance(retailer, dict) or not isinstance(
            retailer.get("retailer_id"), str
        ):
            raise ValueError("world retailer IDs must be strings")
        retailer_ids.append(retailer["retailer_id"])
    if len(set(retailer_ids)) != len(retailer_ids) or "aggregator" in retailer_ids:
        raise ValueError("world retailer IDs must be unique and cannot be aggregator")
    return tuple(retailer_ids)


def _variant_for(world: dict[str, Any], site: str) -> str:
    material = f"{world.get('seed', '')}\0{site}\0layout-v1".encode("utf-8")
    return ("compact", "expanded")[hashlib.sha256(material).digest()[0] & 1]


def _parse_options(
    supplied: Mapping[str, Any] | None,
    sites: tuple[str, ...],
    *,
    name: str,
    validator: Any,
    default: Any,
) -> dict[str, Any]:
    if supplied is None:
        supplied = {}
    supplied = _strict_mapping(supplied, name)
    unknown = set(supplied) - set(sites)
    if unknown:
        raise ValueError(f"unknown {name} sites: {sorted(unknown)}")
    result: dict[str, Any] = {}
    for site in sites:
        value = supplied[site] if site in supplied else default(site)
        result[site] = validator(value, site)
    return result


def _port(value: object, site: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"port for {site} must be an integer")
    if not 0 <= value <= 65_535:
        raise ValueError(f"port for {site} must be between 0 and 65535")
    return value


def _layout(value: object, site: str) -> str:
    if not isinstance(value, str) or value not in _LAYOUT_VARIANTS:
        raise ValueError(f"layout variant for {site} must be compact or expanded")
    return value


class Runtime:
    """Serve one isolated commerce session over four loopback HTTP origins."""

    def __init__(
        self,
        world: dict[str, Any],
        layout_variants: Mapping[str, str] | None = None,
        ports: Mapping[str, int] | None = None,
        *, retailer_designs: Mapping[str, str] | None = None,
        presentation_options: Mapping[str, dict] | None = None,
        checkout_flows: Mapping[str, str] | str | None = None,
        checkout_profile: Mapping[str, str] | None = None,
        checkout_shells: Mapping[str, str] | None = None,
        cart_navigation=None,
        cart_addition=None,
        product_groups=None,
        product_control_styles=None,
    ):
        self._world = copy.deepcopy(world)
        self.retailer_ids = _validate_world(self._world)
        self._sites = ("aggregator", *self.retailer_ids)
        self.retailer_designs, self.presentation_options = resolve_presentations(world.get("seed"),self.retailer_ids,retailer_designs,presentation_options)
        self.product_groups = pc.validate_groups(product_groups, self._world)
        self.product_control_styles = copy.deepcopy(product_control_styles or {})
        fields = {a['field'] for g in self.product_groups for a in g['axes']}
        if set(self.product_control_styles) - set(self.retailer_ids):
            raise ValueError('Unknown product-control retailer')
        for styles in self.product_control_styles.values():
            if not isinstance(styles, dict) or set(styles) - fields or any(v not in ('select', 'radio') for v in styles.values()):
                raise ValueError('Unsupported product control')
        if self.product_groups and 'legacy-catalog' in self.retailer_designs.values():
            raise ValueError('Product groups require an AX retailer design on all retailers')
        self.layout_variants = _parse_options(
            layout_variants,
            self._sites,
            name="layout_variants",
            validator=_layout,
            default=lambda site: _variant_for(self._world, site),
        )
        resolved_ports = _parse_options(
            ports,
            self._sites,
            name="ports",
            validator=_port,
            default=lambda _site: 0,
        )
        nonzero_ports = [value for value in resolved_ports.values() if value]
        if len(nonzero_ports) != len(set(nonzero_ports)):
            raise ValueError("nonzero ports must be unique")

        self.session = CommerceSession(self._world)
        self.checkout_flows = resolve_checkout_flows(world.get("seed"),self.retailer_ids,checkout_flows)
        if checkout_shells is not None and (not isinstance(checkout_shells,Mapping) or set(checkout_shells)-set(self.retailer_ids)):
            raise ValueError("Unknown checkout shell retailer")
        self.checkout_shells={site:(checkout_shells or {}).get(site,"branded") for site in self.retailer_ids}
        if any(value not in ("branded","storefront") for value in self.checkout_shells.values()):
            raise ValueError("Unknown checkout shell")
        if any(self.checkout_flows[site]=="legacy" and shell!="branded" for site,shell in self.checkout_shells.items()):
            raise ValueError("Storefront checkout shell requires a nonlegacy flow")
        from .cart_interaction import resolve as resolve_cart_navigation
        self.cart_navigation=resolve_cart_navigation(world.get("seed"),self.retailer_ids,cart_navigation)
        from .cart_interaction import resolve_addition
        self.cart_addition=resolve_addition(world.get("seed"),self.retailer_ids,cart_addition)
        self.checkout_controllers = {}
        self.checkout_profile = copy.deepcopy(dict(checkout_profile)) if checkout_profile is not None else None
        if any(mode!="legacy" for mode in self.checkout_flows.values()):
            from .checkout import CheckoutFlow, DEMO_PROFILE
            if self.checkout_profile is None:self.checkout_profile=copy.deepcopy(DEMO_PROFILE)
            self.checkout_controllers = {site:CheckoutFlow(self.session,site,mode,self.checkout_profile,document_renderer=self._checkout_document_renderer(site))
                                         for site,mode in self.checkout_flows.items() if mode!="legacy"}
        self._state_lock = threading.RLock()
        self._close_lock = threading.Lock()
        self._closed = False
        self.servers: dict[str, _LoopbackHTTPServer] = {}
        self.threads: list[threading.Thread] = []
        try:
            for site in self._sites:
                server = _LoopbackHTTPServer(
                    ("127.0.0.1", resolved_ports[site]), self._handler(site)
                )
                self.servers[site] = server
        except Exception:
            for server in self.servers.values():
                server.server_close()
            raise

        origins = {
            site: f"http://127.0.0.1:{server.server_port}"
            for site, server in self.servers.items()
        }
        # Keep a private immutable map for rendering so mutation of the convenient
        # public copy cannot turn a local link into an external one.
        self.origins = dict(origins)
        self._safe_origins = MappingProxyType(dict(origins))
        for site, server in self.servers.items():
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.05},
                name=f"procedural-commerce-{site}",
                daemon=True,
            )
            thread.start()
            self.threads.append(thread)

    def _handler(self, site: str) -> type["RequestHandler"]:
        runtime = self

        class SiteHandler(RequestHandler):
            site_id = site
            commerce_runtime = runtime

        return SiteHandler

    def _checkout_document_renderer(self, site):
        if self.checkout_shells[site] == "branded":
            return None
        from .checkout_shell import render_in_storefront
        def render(catalog, title, body):
            return render_in_storefront(site,dict(self._safe_origins),catalog,self.retailer_designs[site],self.presentation_options[site],title,body)
        return render

    def snapshot(self) -> dict[str, Any]:
        """Return a detached private session snapshot for the trusted harness."""

        with self._state_lock:
            state=self.session.snapshot()
            if self.checkout_controllers:
                state["checkout_flows"]={site:controller.snapshot() for site,controller in self.checkout_controllers.items()}
            return state

    def close(self) -> None:
        """Stop all four servers.  Repeated calls are harmless."""

        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            for server in self.servers.values():
                server.shutdown()
            for server in self.servers.values():
                server.server_close()
            for thread in self.threads:
                thread.join(timeout=2)

    def __enter__(self) -> "Runtime":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _catalog_locked(self, site: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        if site == "aggregator":
            return aggregator_view(self._world)
        catalog = retailer_view(self._world, site)
        if self.cart_navigation[site]!="redirect":
            catalog["cart_quantity"]=(snapshot["carts"].get(site) or {}).get("quantity",0)
            catalog["cart_navigation"]=self.cart_navigation[site]
        if self.product_groups:
            catalog["product_groups"] = copy.deepcopy(self.product_groups)
            catalog["product_control_styles"] = copy.deepcopy(self.product_control_styles.get(site, {}))
        stock = snapshot["stock_by_offer"]
        for offer in catalog["offers"]:
            offer["stock_quantity"] = stock[offer["offer_id"]]
        return catalog

    def _orders_for(self, site: str, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        if site == "aggregator":
            return []
        receipts: list[dict[str, Any]] = []
        for order in snapshot["orders"]:
            quoted = order.get("quote")
            if not isinstance(quoted, dict) or quoted.get("retailer_id") != site:
                continue
            # Receipts keep the authoritative nested quote and also expose its fields
            # at top level for renderers that treat an order as a flat receipt row.
            receipts.append(copy.deepcopy({**order, **quoted}))
        return receipts

    def _current_quote_locked(
        self,
        site: str,
        offer_id: str,
        quantity: int,
        destination: str,
        method: str,
        extra: bool,
    ) -> dict[str, Any]:
        offer = self._offer(offer_id)
        if offer["retailer_id"] != site:
            raise _HTTPError(HTTPStatus.NOT_FOUND, "Page not found")
        snapshot = self.session.snapshot()
        current_world = copy.deepcopy(self._world)
        for row in current_world["offers"]:
            if row["offer_id"] == offer_id:
                row["stock_quantity"] = snapshot["stock_by_offer"][offer_id]
                break
        return quote(
            current_world,
            offer_id,
            quantity=quantity,
            destination=destination,
            method=method,
            extra=extra,
        )

    def _offer(self, offer_id: str) -> dict[str, Any]:
        matches = [row for row in self._world["offers"] if row.get("offer_id") == offer_id]
        if len(matches) != 1:
            raise _HTTPError(HTTPStatus.NOT_FOUND, "Page not found")
        return matches[0]


class RequestHandler(BaseHTTPRequestHandler):
    """Request router bound to one site by :class:`Runtime`."""

    site_id: str
    commerce_runtime: Runtime
    server_version = "ProceduralCommerce/1"
    sys_version = ""

    def log_message(self, _format: str, *_args: object) -> None:
        return

    @staticmethod
    def _route_kind(site: str, path: str) -> str | None:
        if path in {"/", "/search"} or _PRODUCT_PATH.fullmatch(path):
            return "page"
        if site != "aggregator" and path in {
            "/policy",
            "/quote",
            "/cart",
            "/checkout",
        }:
            return "page"
        if site != "aggregator" and (_RECEIPT_PATH.fullmatch(path) or _DETAILS_PATH.fullmatch(path)):
            return "page"
        if site != "aggregator" and path in {
            "/cart/set",
            "/cart/update",
            "/cart/remove",
        }:
            return "action"
        return None

    def _parsed_target(self) -> tuple[str, str]:
        if len(self.path.encode("utf-8", "surrogatepass")) > _MAX_QUERY_BYTES:
            raise _HTTPError(HTTPStatus.REQUEST_URI_TOO_LONG, "Request URI too long")
        parsed = urlsplit(self.path)
        if parsed.scheme or parsed.netloc or parsed.fragment:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid request target")
        try:
            path = unquote(parsed.path, encoding="utf-8", errors="strict")
        except UnicodeError as exc:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid request target") from exc
        if not path.startswith("/") or "\x00" in path or "\\" in path:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid request target")
        return path, parsed.query

    @staticmethod
    def _parameters(
        encoded: str,
        *,
        allowed: set[str],
        required: set[str] = frozenset(),
    ) -> dict[str, str]:
        try:
            pairs = parse_qsl(
                encoded,
                keep_blank_values=True,
                strict_parsing=True,
                encoding="utf-8",
                errors="strict",
                max_num_fields=24,
            )
        except (UnicodeError, ValueError) as exc:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid request parameters") from exc
        result: dict[str, str] = {}
        for key, value in pairs:
            if key not in allowed or key in result or len(value) > 512:
                raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid request parameters")
            result[key] = value
        if required - set(result):
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid request parameters")
        return result

    def _form(self, allowed: set[str] | None = None) -> dict[str, str]:
        if self.headers.get("Transfer-Encoding") is not None:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid request body")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            length = 0
        else:
            try:
                length = int(raw_length, 10)
            except ValueError as exc:
                raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid request body") from exc
        if length < 0:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid request body")
        if length > _MAX_BODY_BYTES:
            raise _HTTPError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body too large")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if length and content_type != "application/x-www-form-urlencoded":
            raise _HTTPError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Unsupported request body")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid request body")
        try:
            encoded = raw.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid request body") from exc
        return self._parameters(
            encoded,
            allowed=allowed if allowed is not None else {"offer_id", "quantity", "destination", "method", "extra"},
        )

    @staticmethod
    def _quantity(value: str | None, default: int = 1) -> int:
        if value is None:
            return default
        if not re.fullmatch(r"[1-9][0-9]{0,5}", value):
            raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid quantity")
        return int(value)

    @staticmethod
    def _extra(value: str | None, default: bool | None = False) -> bool | None:
        if value is None:
            return default
        if value == "true":
            return True
        if value == "false":
            return False
        raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid extra selection")

    def _send_html(self, status: int, html: str) -> None:
        raw = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _send_error_page(self, status: int, message: str) -> None:
        safe_messages = {
            HTTPStatus.BAD_REQUEST: "The request was invalid.",
            HTTPStatus.NOT_FOUND: "Page not found.",
            HTTPStatus.METHOD_NOT_ALLOWED: "Method not allowed.",
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE: "The request body was too large.",
            HTTPStatus.REQUEST_URI_TOO_LONG: "The request URI was too long.",
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE: "The request body type is unsupported.",
            HTTPStatus.INTERNAL_SERVER_ERROR: "The page could not be loaded.",
        }
        public = safe_messages.get(status, message if len(message) <= 120 else "Request failed.")
        html = (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{int(status)} {public}</title></head><body>"
            f"<main><h1>{public}</h1></main></body></html>"
        )
        self._send_html(status, html)

    def _redirect(self, path: str, notice: str | None = None) -> None:
        if not path.startswith("/") or path.startswith("//"):
            raise RuntimeError("redirects must remain on the current origin")
        location = path
        if notice is not None:
            location += "?" + urlencode({"notice": notice})
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _get(self, path: str, encoded_query: str) -> None:
        runtime = self.commerce_runtime
        if path == "/search":
            query = self._parameters(
                encoded_query, allowed={"q", "category", "page"}
            )
            if "page" in query and not re.fullmatch(r"[1-9][0-9]{0,5}", query["page"]):
                raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid page")
        elif path == "/quote":
            query = self._parameters(
                encoded_query,
                allowed={"offer_id", "quantity", "destination", "method", "extra"},
                required={"offer_id"},
            )
        elif _PRODUCT_PATH.fullmatch(path) and self.site_id != 'aggregator' and pc.group_for(runtime.product_groups, _PRODUCT_PATH.fullmatch(path).group(1)):
            group = pc.group_for(runtime.product_groups, _PRODUCT_PATH.fullmatch(path).group(1))
            query = self._parameters(encoded_query, allowed={'notice', 'offer_id', 'quantity', 'destination', 'method', 'extra'} | {'option_' + a['field'] for a in group['axes']})
            if 'notice' in query and query['notice'] not in _PUBLIC_ERRORS:
                raise _HTTPError(HTTPStatus.BAD_REQUEST, 'Invalid notice')
            try:
                pc.resolve(group, _PRODUCT_PATH.fullmatch(path).group(1),
                           {k[7:]: v for k,v in query.items() if k.startswith('option_')} if any(k.startswith('option_') for k in query) else None)
            except ValueError as exc:
                raise _HTTPError(HTTPStatus.BAD_REQUEST, 'Invalid selection') from exc
        elif path in {"/cart", "/checkout"} or _PRODUCT_PATH.fullmatch(path):
            query = self._parameters(encoded_query, allowed={"notice"})
            if "notice" in query and query["notice"] not in _PUBLIC_ERRORS:
                raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid notice")
        else:
            query = self._parameters(encoded_query, allowed=set())

        if path == "/cart" and self.site_id in runtime.checkout_controllers:
            from .checkout_pages import render_cart
            with runtime._state_lock:
                catalog=runtime._catalog_locked(self.site_id,runtime.session.snapshot())
                html=render_cart(runtime.checkout_controllers[self.site_id],catalog,_PUBLIC_ERRORS.get(query.get("notice","")))
            self._send_html(HTTPStatus.OK,html)
            return

        product_match = _PRODUCT_PATH.fullmatch(path) or _DETAILS_PATH.fullmatch(path)
        receipt_match = _RECEIPT_PATH.fullmatch(path)
        if product_match:
            product_id = product_match.group(1)
            if not any(row.get("product_id") == product_id for row in runtime._world["products"]):
                raise _HTTPError(HTTPStatus.NOT_FOUND, "Page not found")

        with runtime._state_lock:
            snapshot = runtime.session.snapshot()
            catalog = runtime._catalog_locked(self.site_id, snapshot)
            cart = None if self.site_id == "aggregator" else snapshot["carts"][self.site_id]
            orders = runtime._orders_for(self.site_id, snapshot)
            quoted = None
            if path == "/quote":
                try:
                    quoted = runtime._current_quote_locked(
                        self.site_id,
                        query["offer_id"],
                        self._quantity(query.get("quantity")),
                        query.get("destination", "SE"),
                        query.get("method", "standard"),
                        bool(self._extra(query.get("extra"), False)),
                    )
                except CommerceValidationError as exc:
                    raise _HTTPError(HTTPStatus.BAD_REQUEST, "Invalid quote request") from exc
            if receipt_match:
                order_id = receipt_match.group(1)
                if not any(order.get("order_id") == order_id for order in orders):
                    raise _HTTPError(HTTPStatus.NOT_FOUND, "Page not found")
            context = {
                "catalog": catalog,
                "cart": copy.deepcopy(cart),
                "orders": orders,
                "quote": copy.deepcopy(quoted),
                "error": _PUBLIC_ERRORS.get(query.get("notice", "")),
                "layout_variant": runtime.layout_variants[self.site_id],
                "retailer_design": runtime.retailer_designs.get(self.site_id,"legacy-catalog"),
                "presentation_options": copy.deepcopy(runtime.presentation_options.get(self.site_id,{})),
                "fulfillment": (runtime.checkout_controllers[self.site_id].snapshot().get("committed_profiles",{}).get(receipt_match.group(1))
                                if receipt_match and self.site_id in runtime.checkout_controllers else None),
            }

        html = render_page(
            self.site_id,
            path,
            query,
            context,
            dict(runtime._safe_origins),
        )
        if not isinstance(html, str):
            raise RuntimeError("renderer must return an HTML string")
        self._send_html(HTTPStatus.OK, html)

    def _post(self, path: str, encoded_query: str) -> None:
        self._parameters(encoded_query, allowed=set())
        runtime = self.commerce_runtime
        option_fields = {'option_' + a['field'] for g in runtime.product_groups for a in g['axes']}
        form = self._form(allowed={'offer_id', 'quantity', 'destination', 'method', 'extra'} | (option_fields if path == '/cart/set' else set()))
        action: str
        payload: dict[str, Any]
        success_path = "/cart"
        if path == "/cart/set":
            if "offer_id" not in form:
                self._redirect("/cart", "invalid_cart")
                return
            if set(form) - ({"offer_id", "quantity", "destination", "method", "extra"} | option_fields):
                self._redirect("/cart", "invalid_cart")
                return
            try:
                offer = runtime._offer(form["offer_id"])
            except _HTTPError:
                self._redirect("/cart", "invalid_cart")
                return
            if offer["retailer_id"] != self.site_id:
                self._redirect("/cart", "invalid_cart")
                return
            group = pc.group_for(runtime.product_groups, offer['product_id'])
            if group:
                try:
                    chosen = pc.resolve(group, offer['product_id'], {k[7:]:v for k,v in form.items() if k.startswith('option_')})
                except ValueError as exc:
                    raise _HTTPError(HTTPStatus.BAD_REQUEST, 'Invalid selection') from exc
                if chosen['product_id'] != offer['product_id']:
                    fields = {'option_' + k:v for k,v in chosen['selection'].items()}
                    fields['notice'] = 'selection_changed'
                    self._redirect('/products/' + offer['product_id'] + '?' + urlencode(fields))
                    return
            elif any(k.startswith('option_') for k in form):
                raise _HTTPError(HTTPStatus.BAD_REQUEST, 'Unexpected selection')
            payload = {
                "offer_id": form["offer_id"],
                "quantity": self._quantity(form.get("quantity")),
                "destination": form.get("destination", "SE"),
                "method": form.get("method", "standard"),
                # The rendered checkbox already reflects public preselection. Native
                # forms omit it only when the user submits an unchecked control.
                "extra": self._extra(form.get("extra"), False),
            }
            action = "cart.add" if runtime.cart_addition[self.site_id]=="increment" else "cart.set"
            if runtime.cart_navigation[self.site_id]!="redirect":
                success_path=f"/products/{offer['product_id']}"
        elif path == "/cart/update":
            if not form or set(form) - {"quantity", "destination", "method", "extra"}:
                self._redirect("/cart", "invalid_cart")
                return
            payload = {"retailer_id": self.site_id}
            if "quantity" in form:
                payload["quantity"] = self._quantity(form["quantity"])
            if "destination" in form:
                payload["destination"] = form["destination"]
            if "method" in form:
                payload["method"] = form["method"]
            # Native HTML omits an unchecked checkbox.  On update, absence is an
            # explicit deselection rather than the engine API's "preserve" behavior.
            payload["extra"] = self._extra(form.get("extra"), False)
            action = "cart.update"
        elif path == "/cart/remove":
            if form:
                self._redirect("/cart", "invalid_cart")
                return
            payload = {"retailer_id": self.site_id}
            action = "cart.remove"
        else:
            if form:
                self._redirect("/cart", "checkout_failed")
                return
            payload = {"retailer_id": self.site_id}
            action = "checkout"
            success_path = "/cart"

        with runtime._state_lock:
            if path == '/cart/set' and pc.group_for(runtime.product_groups, offer['product_id']):
                snapshot = runtime.session.snapshot()
                current = snapshot['carts'][self.site_id]
                total = payload['quantity'] + (current['quantity'] if action == 'cart.add' and current and current['offer_id'] == offer['offer_id'] else 0)
                if total > snapshot['stock_by_offer'][offer['offer_id']]:
                    self._redirect('/products/' + offer['product_id'], 'ineligible_quote')
                    return
            result = runtime.session.perform(action, payload)
            if result["ok"] and action in {"cart.add","cart.set","cart.update","cart.remove"} and self.site_id in runtime.checkout_controllers:
                runtime.checkout_controllers[self.site_id].invalidate_cart()
        if not result["ok"]:
            code = result.get("error", {}).get("code")
            notice = (
                "empty_cart"
                if code == "empty_cart"
                else "cart_line_limit"
                if code == "cart_line_limit"
                else "ineligible_quote"
                if code == "ineligible_quote"
                else "checkout_failed"
                if action == "checkout"
                else "invalid_cart"
            )
            self._redirect(success_path, notice)
            return
        if action == "checkout":
            self._redirect(f"/receipt/{result['order']['order_id']}")
        else:
            self._redirect(success_path)

    def _dispatch(self, method: str) -> None:
        path, query = self._parsed_target()
        runtime=self.commerce_runtime
        if self.site_id in runtime.checkout_controllers and (path=="/checkout" or path.startswith("/checkout/")):
            from .checkout import CHECKOUT_FIELDS,CHECKOUT_GET_PATHS,CHECKOUT_POST_PATHS
            if path not in set(CHECKOUT_GET_PATHS)|set(CHECKOUT_POST_PATHS):raise _HTTPError(HTTPStatus.NOT_FOUND,"Page not found")
            self._parameters(query,allowed=set())
            if method=="GET" and path in CHECKOUT_GET_PATHS:
                with runtime._state_lock:
                    catalog=runtime._catalog_locked(self.site_id,runtime.session.snapshot())
                    status,body=runtime.checkout_controllers[self.site_id].render(path,catalog,dict(runtime._safe_origins))
                self._send_html(status,body)
            elif method=="POST" and path in CHECKOUT_POST_PATHS:
                form=self._form(allowed=set(CHECKOUT_FIELDS))
                with runtime._state_lock:destination=runtime.checkout_controllers[self.site_id].submit(path,form)
                self._redirect(destination)
            else:raise _HTTPError(HTTPStatus.METHOD_NOT_ALLOWED,"Method not allowed")
            return
        route_kind = self._route_kind(self.site_id, path)
        if route_kind is None:
            raise _HTTPError(HTTPStatus.NOT_FOUND, "Page not found")
        allowed_methods = (
            {"GET", "POST"}
            if path == "/checkout"
            else {"POST"}
            if route_kind == "action"
            else {"GET"}
        )
        if method not in allowed_methods:
            raise _HTTPError(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")
        if method == "GET":
            self._get(path, query)
        else:
            self._post(path, query)

    def _safe_dispatch(self, method: str) -> None:
        try:
            self._dispatch(method)
        except _HTTPError as exc:
            self._send_error_page(exc.status, exc.message)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._send_error_page(HTTPStatus.INTERNAL_SERVER_ERROR, "Request failed")

    def do_GET(self) -> None:
        self._safe_dispatch("GET")

    def do_POST(self) -> None:
        self._safe_dispatch("POST")

    def do_HEAD(self) -> None:
        self._safe_dispatch("HEAD")

    def do_PUT(self) -> None:
        self._safe_dispatch("PUT")

    def do_PATCH(self) -> None:
        self._safe_dispatch("PATCH")

    def do_DELETE(self) -> None:
        self._safe_dispatch("DELETE")

    def do_OPTIONS(self) -> None:
        self._safe_dispatch("OPTIONS")


def _write_manifest(directory: Path, runtime: Runtime, seed: int, scale: str) -> Path:
    """Create a private, unserved manifest directory for a preview process."""

    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    manifest_path = directory / "manifest.json"
    manifest = {
        "schema_version": "procedural-commerce-runtime-v1",
        "seed": seed,
        "scale": scale,
        "world_sha256": world_sha256(runtime._world),
        "origins": runtime.origins,
        "retailer_designs": runtime.retailer_designs,
        "presentation_options": runtime.presentation_options,
        "checkout_flows": runtime.checkout_flows,
        "checkout_shells": runtime.checkout_shells,
        "cart_navigation": runtime.cart_navigation,
        "cart_addition": runtime.cart_addition,
        "pid": os.getpid(),
    }
    descriptor = os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(manifest, output, ensure_ascii=False, sort_keys=True, indent=2)
        output.write("\n")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve a procedural commerce preview")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--scale", choices=("small", "large"), default="small")
    parser.add_argument("--design-set", choices=("legacy", "ax-v2"), default="legacy")
    parser.add_argument("--presentation-profile", choices=("seeded", "showcase"), default="seeded")
    parser.add_argument("--checkout-set",choices=("legacy","mixed","sampled"),default="legacy")
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="fixed aggregator port; retailer ports remain dynamically allocated",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="new private directory in which to create manifest.json",
    )
    parser.add_argument("--checkout-shell",choices=("branded","storefront"),default="branded")
    parser.add_argument("--cart-navigation",choices=("redirect","inline","menu","mixed","sampled"),default="mixed")
    parser.add_argument("--cart-addition",choices=("set","increment","mixed","sampled"),default="set")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65_535:
        parser.error("--port must be between 0 and 65535")
    if args.output.exists():
        parser.error("--output must name a new directory")

    from .cart_interaction import SHOWCASE as CART_SHOWCASE
    world = generate_world(args.seed, args.scale)
    runtime = Runtime(world, ports={"aggregator": args.port}, retailer_designs=SHOWCASE if args.design_set=="ax-v2" else None, presentation_options=SHOWCASE_OPTIONS if args.presentation_profile=="showcase" else None, checkout_flows=CHECKOUT_SHOWCASE if args.checkout_set=="mixed" else "sampled" if args.checkout_set=="sampled" else None,checkout_shells={site:args.checkout_shell for site in CHECKOUT_SHOWCASE},cart_navigation=CART_SHOWCASE if args.cart_navigation=="mixed" else "sampled" if args.cart_navigation=="sampled" else {site:args.cart_navigation for site in CHECKOUT_SHOWCASE},cart_addition={"nordhem":"increment","vardagslagret":"set","teknikgarden":"set"} if args.cart_addition=="mixed" else "sampled" if args.cart_addition=="sampled" else {site:args.cart_addition for site in CHECKOUT_SHOWCASE})
    try:
        manifest_path = _write_manifest(args.output, runtime, args.seed, args.scale)
    except Exception:
        runtime.close()
        raise

    stopped = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stop)
    print(
        json.dumps(
            {"manifest": str(manifest_path.resolve()), "origins": runtime.origins},
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        stopped.wait()
    finally:
        runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["Runtime", "main"]
