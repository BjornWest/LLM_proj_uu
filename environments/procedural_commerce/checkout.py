"""Server-authoritative checkout flows for procedural commerce retailers.

The controller intentionally owns both checkout state and presentation.  It only
asks :class:`CommerceSession` to change a delivery method or commit an order, so
prices, availability, quote identities, and order identities remain engine data.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
from html import escape
import json
import re
import secrets
from typing import Any, Mapping

from .engine import CommerceSession


CHECKOUT_FIELDS = {
    "full_name",
    "email",
    "phone",
    "address",
    "postal_code",
    "city",
    "method",
    "payment_method",
    "confirm",
    "review_token",
}
CHECKOUT_GET_PATHS = frozenset(
    {
        "/checkout",
        "/checkout/contact",
        "/checkout/address",
        "/checkout/delivery",
        "/checkout/review",
    }
)
CHECKOUT_POST_PATHS = frozenset(
    {
        "/checkout",
        "/checkout/contact",
        "/checkout/address",
        "/checkout/delivery",
        "/checkout/quote",
    }
)
DEMO_PROFILE = {
    "full_name": "Alex Andersson",
    "email": "alex@example.test",
    "phone": "0700000000",
    "address": "Testgatan 12",
    "postal_code": "12345",
    "city": "Stockholm",
}

_MODES = frozenset({"express", "accordion", "wizard"})
_CONTACT = ("full_name", "email", "phone")
_ADDRESS = ("address", "postal_code", "city")
_PROFILE_FIELDS = _CONTACT + _ADDRESS + ("payment_method",)
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+\Z")
_POSTCODE = re.compile(r"[0-9]{3}\s?[0-9]{2}\Z")
_PHONE = re.compile(r"[0-9+() .-]{5,30}\Z")


def _e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _money(value: object) -> str:
    """Format an authoritative minor-unit value without calculating a price."""

    if isinstance(value, bool) or not isinstance(value, int):
        return "Not available"
    sign = "-" if value < 0 else ""
    amount = abs(value)
    return f"{sign}{amount // 100}.{amount % 100:02d} SEK"


def _label(value: object) -> str:
    return str(value or "").replace("_", " ").replace("-", " ").capitalize()


class CheckoutFlow:
    """One retailer's isolated checkout state machine and HTML renderer.

    Callers serialize access with the runtime state lock, as required by the
    module contract.  No state in this class is shared between instances.
    """

    def __init__(
        self,
        session: CommerceSession,
        retailer_id: str,
        mode: str,
        profile: Mapping[str, object] | None = None,
        *, document_renderer=None,
    ):
        if not isinstance(session, CommerceSession):
            raise TypeError("session must be a CommerceSession")
        if not isinstance(retailer_id, str) or not retailer_id:
            raise ValueError("retailer_id must be a non-empty string")
        if mode not in _MODES:
            raise ValueError("checkout mode must be express, accordion, or wizard")
        if profile is not None and not isinstance(profile, Mapping):
            raise TypeError("profile must be a mapping")

        saved = dict(DEMO_PROFILE)
        if profile is not None:
            unknown = set(profile) - set(DEMO_PROFILE)
            if unknown:
                raise ValueError(f"unknown profile fields: {sorted(unknown)}")
            for key, value in profile.items():
                if not isinstance(value, str) or len(value) > 512:
                    raise ValueError(f"profile field {key} must be a string of at most 512 characters")
                saved[key] = value.strip()

        self.document_renderer = document_renderer
        self.session = session
        self.retailer_id = retailer_id
        self.mode = mode
        self._saved_profile = saved
        self._draft: dict[str, str] = {"payment_method": "demo-card"}
        if mode == "express":
            self._draft.update(saved)
        self._errors: dict[str, str] = {}
        self._stages: set[str] = set()
        self._journal: list[dict[str, object]] = []
        self._committed_profiles: dict[str, dict[str, str]] = {}
        self._consumed_tokens: dict[str, str] = {}
        self._generation = 0
        self._secret = secrets.token_bytes(32)

    # ---- private state and validation -------------------------------------------------

    def _record(self, action: str, result: str, **details: object) -> None:
        self._journal.append(
            {
                "sequence": len(self._journal) + 1,
                "action": action,
                "result": result,
                **details,
            }
        )

    def _invalidate(self, reason: str, *, journal: bool = True) -> None:
        self._generation += 1
        if journal:
            self._record("invalidate_review", "ok", reason=reason)

    def invalidate_cart(self) -> None:
        """Invalidate review authority after any external cart mutation.

        This deliberately increments even when a later mutation restores the same
        quote, preventing a change-and-revert from reviving an old review token.
        Contact and address drafts remain available to the user.
        """

        self._invalidate("cart_changed")

    def _cart(self) -> dict[str, Any] | None:
        return self.session.quote_cart(self.retailer_id)

    @staticmethod
    def _clean_form(form: Mapping[str, object] | object) -> dict[str, str] | None:
        if not isinstance(form, Mapping):
            return None
        clean: dict[str, str] = {}
        for key, value in form.items():
            # A list/tuple commonly represents duplicate decoded controls.  Refuse
            # it rather than silently selecting one value.
            if (
                not isinstance(key, str)
                or key not in CHECKOUT_FIELDS
                or not isinstance(value, str)
                or len(value) > 512
            ):
                return None
            clean[key] = value
        return clean

    def _reject_form(self, path: str, message: str = "The checkout request was invalid.") -> str:
        self._errors = {"form": message}
        self._record("submit", "rejected", stage=path, reason="invalid_form")
        return self._redirect_for(path)

    def _require_shape(
        self,
        path: str,
        form: dict[str, str],
        *,
        required: set[str],
        optional: set[str] = frozenset(),
    ) -> bool:
        missing = required - set(form)
        unknown = set(form) - required - optional
        if missing or unknown:
            self._errors = {"form": "Please submit the fields shown on this checkout step."}
            self._record(
                "submit",
                "rejected",
                stage=path,
                reason="missing_or_unknown_fields",
            )
            return False
        return True

    def _save(self, form: dict[str, str], names: tuple[str, ...]) -> bool:
        changed = False
        for name in names:
            if name not in form:
                continue
            value = form[name].strip()
            if self._draft.get(name, "") != value:
                self._draft[name] = value
                changed = True
        if changed:
            self._invalidate("checkout_details_changed", journal=False)
        return changed

    def _validate_contact(self, *, phone_required: bool = False) -> dict[str, str]:
        errors: dict[str, str] = {}
        if not self._draft.get("full_name", "").strip():
            errors["full_name"] = "Enter the recipient's full name."
        email = self._draft.get("email", "").strip()
        if not _EMAIL.fullmatch(email):
            errors["email"] = "Enter a valid email address."
        phone = self._draft.get("phone", "").strip()
        if phone_required and not phone:
            errors["phone"] = "Enter a phone number."
        elif phone and not _PHONE.fullmatch(phone):
            errors["phone"] = "Enter a valid phone number."
        return errors

    def _validate_address(self) -> dict[str, str]:
        errors: dict[str, str] = {}
        if not self._draft.get("address", "").strip():
            errors["address"] = "Enter a street address."
        if not _POSTCODE.fullmatch(self._draft.get("postal_code", "").strip()):
            errors["postal_code"] = "Enter a five-digit Swedish postcode."
        if not self._draft.get("city", "").strip():
            errors["city"] = "Enter a city."
        return errors

    def _validate_payment(self) -> dict[str, str]:
        if self._draft.get("payment_method") not in {"demo-card", "demo-invoice"}:
            return {"payment_method": "Choose a simulated payment method."}
        return {}

    def _replace_errors(self, checked: set[str], errors: dict[str, str]) -> None:
        for key in checked:
            self._errors.pop(key, None)
        self._errors.pop("form", None)
        self._errors.update(errors)

    def _change_method(self, desired: str) -> bool:
        cart = self._cart()
        if cart is None:
            self._errors = {"cart": "Your cart is empty."}
            return False
        if not desired:
            self._errors["method"] = "Choose a delivery method."
            return False
        if desired == cart.get("method"):
            self._errors.pop("method", None)
            return True
        result = self.session.perform(
            "cart.update", {"retailer_id": self.retailer_id, "method": desired}
        )
        if not result.get("ok"):
            self._errors["method"] = "That delivery method is not available."
            self._record("delivery_method", "rejected")
            return False
        self._errors.pop("method", None)
        self._invalidate("delivery_method_changed", journal=False)
        self._record("delivery_method", "updated", method=desired)
        return True

    def _required_profile_errors(self) -> dict[str, str]:
        if self.mode == "express":
            email = self._draft.get("email", "").strip()
            return {} if _EMAIL.fullmatch(email) else {"email": "Enter a valid email address."}
        errors = self._validate_contact(phone_required=self.mode == "wizard")
        if self.mode != "wizard":
            errors.pop("phone", None)
        errors.update(self._validate_address())
        if self.mode == "wizard":
            errors.update(self._validate_payment())
        return errors

    def _binding(self) -> bytes | None:
        cart = self._cart()
        if cart is None:
            return None
        quote = cart.get("quote")
        if not isinstance(quote, dict) or not quote.get("eligible"):
            return None
        if self._required_profile_errors():
            return None
        relevant = {
            key: self._draft.get(key, "")
            for key in _PROFILE_FIELDS
            if key in self._draft
        }
        payload = {
            "retailer_id": self.retailer_id,
            "mode": self.mode,
            "quote_id": cart.get("quote_id"),
            "generation": self._generation,
            "profile": relevant,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    def _review_token(self) -> str:
        binding = self._binding()
        if binding is None:
            return ""
        return hmac.new(self._secret, binding, hashlib.sha256).hexdigest()

    def _token_valid(self, supplied: str) -> bool:
        expected = self._review_token()
        return bool(expected) and hmac.compare_digest(supplied, expected)

    def _profile_for_commit(self) -> dict[str, str]:
        return {key: self._draft.get(key, "") for key in _PROFILE_FIELDS}

    # ---- submissions ------------------------------------------------------------------

    def submit(self, path: str, form: Mapping[str, object]) -> str:
        """Process a checkout POST and return a same-origin relative redirect."""

        if path not in CHECKOUT_POST_PATHS:
            return self._reject_form(path)
        clean = self._clean_form(form)
        if clean is None:
            return self._reject_form(path)

        if self.mode == "wizard":
            return self._submit_wizard(path, clean)
        if self.mode == "accordion":
            return self._submit_accordion(path, clean)
        return self._submit_express(path, clean)

    def _submit_wizard(self, path: str, form: dict[str, str]) -> str:
        if path == "/checkout/contact":
            if not self._require_shape(path, form, required=set(_CONTACT)):
                return "/checkout/contact"
            self._save(form, _CONTACT)
            errors = self._validate_contact(phone_required=True)
            self._replace_errors(set(_CONTACT), errors)
            if errors:
                self._record("contact", "rejected")
                return "/checkout/contact"
            self._stages.add("contact")
            self._record("contact", "saved")
            return "/checkout/address"

        if path == "/checkout/address":
            if "contact" not in self._stages:
                return self._prerequisite_rejection("address", "/checkout/contact")
            if not self._require_shape(path, form, required=set(_ADDRESS)):
                return "/checkout/address"
            self._save(form, _ADDRESS)
            errors = self._validate_address()
            self._replace_errors(set(_ADDRESS), errors)
            if errors:
                self._record("address", "rejected")
                return "/checkout/address"
            self._stages.add("address")
            self._record("address", "saved")
            return "/checkout/delivery"

        if path == "/checkout/delivery":
            if "contact" not in self._stages:
                return self._prerequisite_rejection("delivery", "/checkout/contact")
            if "address" not in self._stages:
                return self._prerequisite_rejection("delivery", "/checkout/address")
            if not self._require_shape(path, form, required={"method", "payment_method"}):
                return "/checkout/delivery"
            self._save(form, ("payment_method",))
            errors = self._validate_payment()
            self._replace_errors({"method", "payment_method"}, errors)
            if errors or not self._change_method(form["method"]):
                self._record("delivery", "rejected")
                return "/checkout/delivery"
            self._stages.add("delivery")
            self._record("delivery", "saved")
            return "/checkout/review"

        if path == "/checkout":
            if not self._require_shape(path, form, required={"confirm", "review_token"}):
                return "/checkout/review"
            if not {"contact", "address", "delivery"}.issubset(self._stages):
                return self._prerequisite_rejection("review", self._wizard_target())
            replay = self._replay_redirect(form)
            if replay is not None:
                return replay
            return self._commit(form)

        return self._reject_form(path)

    def _submit_accordion(self, path: str, form: dict[str, str]) -> str:
        fields = {"full_name", "email", "address", "postal_code", "city", "method"}
        if path == "/checkout/quote":
            if not self._require_shape(
                path,
                form,
                required=fields,
                optional={"phone", "confirm", "review_token"},
            ):
                return "/checkout"
        elif path == "/checkout":
            if not self._require_shape(
                path, form, required=fields | {"confirm", "review_token"}, optional={"phone"}
            ):
                return "/checkout"
        else:
            return self._reject_form(path)

        if path == "/checkout":
            replay = self._replay_redirect(form)
            if replay is not None:
                return replay
        self._save(form, _CONTACT + _ADDRESS)
        errors = self._required_profile_errors()
        self._replace_errors(set(_CONTACT + _ADDRESS) | {"method"}, errors)
        method_ok = self._change_method(form["method"]) if not errors else False
        if errors or not method_ok:
            self._record("one_page_details", "rejected")
            return "/checkout"
        self._record("one_page_details", "saved")
        if path == "/checkout/quote":
            return "/checkout"
        return self._commit(form)

    def _submit_express(self, path: str, form: dict[str, str]) -> str:
        fields = {"email", "method"}
        if path == "/checkout/quote":
            if not self._require_shape(
                path, form, required=fields, optional={"confirm", "review_token"}
            ):
                return "/checkout"
        elif path == "/checkout":
            if not self._require_shape(path, form, required=fields | {"confirm", "review_token"}):
                return "/checkout"
        else:
            return self._reject_form(path)

        if path == "/checkout":
            replay = self._replay_redirect(form)
            if replay is not None:
                return replay
        self._save(form, ("email",))
        errors = self._required_profile_errors()
        self._replace_errors({"email", "method"}, errors)
        method_ok = self._change_method(form["method"]) if not errors else False
        if errors or not method_ok:
            self._record("express_details", "rejected")
            return "/checkout"
        self._record("express_details", "saved")
        if path == "/checkout/quote":
            return "/checkout"
        return self._commit(form)

    def _replay_redirect(self, form: dict[str, str]) -> str | None:
        token = form.get("review_token", "")
        order_id = self._consumed_tokens.get(token)
        if order_id is None:
            return None
        self._record("commit", "replayed", order_id=order_id)
        return f"/receipt/{order_id}"

    def _commit(self, form: dict[str, str]) -> str:
        token = form.get("review_token", "")
        # An exact browser form resubmission after a successful order is idempotent.
        if token in self._consumed_tokens:
            order_id = self._consumed_tokens[token]
            self._record("commit", "replayed", order_id=order_id)
            return f"/receipt/{order_id}"
        if form.get("confirm") != "yes":
            self._errors["confirm"] = "Confirm that you reviewed the order before placing it."
            self._record("commit", "rejected", reason="confirmation_missing")
            return self._review_path()
        self._errors.pop("confirm", None)
        errors = self._required_profile_errors()
        if errors:
            self._errors.update(errors)
            self._record("commit", "rejected", reason="details_invalid")
            return self._review_path()
        if not self._token_valid(token):
            self._errors["review_token"] = (
                "Your order details or delivery price changed. Review the updated order and confirm again."
            )
            self._record("commit", "rejected", reason="review_stale")
            return self._review_path()

        result = self.session.perform("checkout", {"retailer_id": self.retailer_id})
        order = result.get("order")
        if not result.get("ok") or not isinstance(order, dict) or not isinstance(order.get("order_id"), str):
            self._errors["cart"] = "The order could not be placed. Review availability and try again."
            self._invalidate("checkout_failed", journal=False)
            self._record("commit", "rejected", reason="engine_rejected")
            return self._review_path()

        order_id = order["order_id"]
        self._committed_profiles[order_id] = self._profile_for_commit()
        self._consumed_tokens[token] = order_id
        self._errors.clear()
        self._invalidate("order_committed", journal=False)
        self._record("commit", "committed", order_id=order_id)
        return f"/receipt/{order_id}"

    def _prerequisite_rejection(self, stage: str, redirect: str) -> str:
        self._errors = {"form": "Complete the earlier checkout steps first."}
        self._record(stage, "rejected", reason="prerequisite_missing")
        return redirect

    def _review_path(self) -> str:
        return "/checkout/review" if self.mode == "wizard" else "/checkout"

    def _wizard_target(self) -> str:
        if "contact" not in self._stages:
            return "/checkout/contact"
        if "address" not in self._stages:
            return "/checkout/address"
        if "delivery" not in self._stages:
            return "/checkout/delivery"
        return "/checkout/review"

    def _redirect_for(self, path: str) -> str:
        if self.mode == "wizard":
            return path if path in CHECKOUT_GET_PATHS and path != "/checkout" else self._wizard_target()
        return "/checkout"

    # ---- rendering --------------------------------------------------------------------

    def render(
        self,
        path: str,
        catalog: Mapping[str, Any],
        origins: Mapping[str, str],
    ) -> tuple[int, str]:
        """Render an ordinary no-JavaScript checkout page."""

        del origins  # Checkout navigation is deliberately same-origin and relative.
        if path not in CHECKOUT_GET_PATHS:
            return 404, self._document(catalog, "Page not found", "<main><h2>Page not found</h2></main>")
        if self.mode != "wizard" and path != "/checkout":
            return 404, self._document(catalog, "Page not found", "<main><h2>Page not found</h2></main>")

        cart = self._cart()
        if cart is None:
            body = (
                '<main class="checkout empty"><p class="simulation">Simulated checkout</p>'
                "<h2>Your cart is empty</h2><p>Add a product before starting checkout.</p>"
                '<p><a href="/search">Browse products</a></p></main>'
            )
            return 200, self._document(catalog, "Checkout", body)

        if self.mode == "accordion":
            body = self._render_accordion(catalog, cart)
        elif self.mode == "express":
            body = self._render_express(catalog, cart)
        else:
            body = self._render_wizard(path, catalog, cart)
        return 200, self._document(catalog, "Checkout", body)

    def _document(self, catalog: Mapping[str, Any], title: str, body: str) -> str:
        if self.document_renderer is not None:
            return self.document_renderer(catalog, title, body)
        from .checkout_pages import STYLES, surround
        from .cart_interaction import cart_label
        if self.mode == "accordion":
            body = surround(catalog, body, self._cart())
        retailer = catalog.get("retailer") if isinstance(catalog, Mapping) else None
        brand = retailer.get("name") if isinstance(retailer, Mapping) else self.retailer_id.title()
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)} | {_e(brand)}</title>
<style>
:root{{font-family:system-ui,sans-serif;color:#17212b;background:#f4f6f8}}*{{box-sizing:border-box}}body{{margin:0;line-height:1.5}}header,main,footer{{max-width:860px;margin:auto;padding:1rem}}header{{display:flex;align-items:center;justify-content:space-between;background:#fff;border-bottom:3px solid #155e75;max-width:none;padding-inline:max(1rem,calc((100% - 860px)/2))}}nav a{{margin-left:1rem}}a{{color:#075985}}h1,h2,h3{{line-height:1.2}}.simulation{{font-weight:700;color:#9a3412}}.checkout{{padding-bottom:3rem}}.panel,details,.summary-card,.saved-address{{background:#fff;border:1px solid #cbd5e1;border-radius:.45rem;padding:1rem;margin:1rem 0}}details>summary{{font-size:1.15rem;font-weight:700;cursor:pointer}}label,legend{{font-weight:650}}input[type=text],input[type=email],input[type=tel]{{display:block;width:100%;max-width:34rem;padding:.65rem;margin:.25rem 0 .85rem;border:1px solid #64748b;border-radius:.3rem}}fieldset{{border:0;padding:0;margin:1rem 0}}fieldset label{{display:block;font-weight:400;margin:.55rem 0}}button{{background:#155e75;color:#fff;border:0;border-radius:.35rem;padding:.72rem 1rem;font-weight:700;cursor:pointer}}button.secondary{{background:#475569}}.actions{{display:flex;gap:.8rem;align-items:center;flex-wrap:wrap;margin-top:1rem}}.error-summary,.field-error{{color:#991b1b}}.error-summary{{border:2px solid #b91c1c;background:#fef2f2;padding:1rem}}.field-error{{font-weight:650;margin-top:-.65rem}}.progress ol{{display:flex;gap:.4rem;list-style:none;padding:0;flex-wrap:wrap}}.progress li{{background:#e2e8f0;padding:.35rem .65rem;border-radius:1rem}}.progress [aria-current=step]{{background:#155e75;color:#fff}}dl.review{{display:grid;grid-template-columns:max-content 1fr;gap:.35rem 1rem}}dt{{font-weight:700}}dd{{margin:0}}.express{{max-width:680px}}.express-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1rem}}@media(max-width:600px){{.express-grid{{grid-template-columns:1fr}}}}.muted{{color:#475569}}
{STYLES}</style></head><body><header><h1>{_e(brand)}</h1><nav aria-label="Store"><a href="/search">Products</a><a href="/cart">{cart_label(catalog)}</a><a href="/policy">Delivery and returns</a></nav></header>{body}<footer><p>Demo store — no real payment or personal data is required.</p></footer></body></html>"""

    def _error_summary(self) -> str:
        if not self._errors:
            return ""
        items = "".join(f"<li>{_e(message)}</li>" for message in self._errors.values())
        return f'<div class="error-summary" role="alert"><h3>Check your details</h3><ul>{items}</ul></div>'

    def _field_error(self, name: str) -> str:
        message = self._errors.get(name)
        return "" if not message else f'<p class="field-error" id="error-{_e(name)}">{_e(message)}</p>'

    def _input(self, name: str, label: str, input_type: str = "text", *, required: bool = True) -> str:
        described = f' aria-describedby="error-{_e(name)}"' if name in self._errors else ""
        required_attr = " required" if required else ""
        return (
            f'<label for="{_e(name)}">{_e(label)}</label>'
            f'<input id="{_e(name)}" name="{_e(name)}" type="{_e(input_type)}" value="{_e(self._draft.get(name, ""))}"{required_attr}{described}>'
            + self._field_error(name)
        )

    def _method_fields(self, catalog: Mapping[str, Any], selected: str) -> str:
        retailer = catalog.get("retailer") if isinstance(catalog, Mapping) else None
        methods = retailer.get("shipping_methods") if isinstance(retailer, Mapping) else None
        if not isinstance(methods, Mapping):
            methods = {}
        choices: list[str] = []
        for method, details in methods.items():
            if not isinstance(method, str) or not isinstance(details, Mapping):
                continue
            checked = " checked" if method == selected else ""
            choices.append(
                f'<label><input type="radio" name="method" value="{_e(method)}" required{checked}> '
                f'{_e(_label(method))} — {_e(_money(details.get("base_price_minor")))} base price, '
                f'{_e(details.get("transit_days"))} transit day(s)</label>'
            )
        return '<fieldset><legend>Delivery method</legend>' + "".join(choices) + self._field_error("method") + "</fieldset>"

    def _payment_fields(self) -> str:
        current = self._draft.get("payment_method", "demo-card")
        choices = (
            ("demo-card", "Demo card (no card details needed)"),
            ("demo-invoice", "Demo invoice"),
        )
        rows = "".join(
            f'<label><input type="radio" name="payment_method" value="{value}" required'
            f'{" checked" if current == value else ""}> {_e(label)}</label>'
            for value, label in choices
        )
        return '<fieldset><legend>Simulated payment</legend>' + rows + self._field_error("payment_method") + "</fieldset>"

    def _quote_summary(self, catalog: Mapping[str, Any], cart: Mapping[str, Any]) -> str:
        quote = cart.get("quote") if isinstance(cart.get("quote"), Mapping) else {}
        offer_id = cart.get("offer_id")
        offers = catalog.get("offers") if isinstance(catalog, Mapping) else []
        offer = next((row for row in offers if isinstance(row, Mapping) and row.get("offer_id") == offer_id), {})
        product_id = offer.get("product_id") if isinstance(offer, Mapping) else None
        products = catalog.get("products") if isinstance(catalog, Mapping) else []
        product = next((row for row in products if isinstance(row, Mapping) and row.get("product_id") == product_id), {})
        eligible = quote.get("eligible") is True
        warning = "" if eligible else '<p class="field-error">This selection is not currently available to order.</p>'
        return f"""<section class="summary-card" aria-labelledby="order-summary"><h3 id="order-summary">Order summary</h3>
<p><strong>{_e(product.get("name") if isinstance(product, Mapping) else offer_id)}</strong> × {_e(quote.get("quantity"))}</p>
<dl class="review"><dt>Items</dt><dd>{_e(_money(quote.get("item_subtotal_minor")))}</dd><dt>Optional service</dt><dd>{_e(_money(quote.get("extra_subtotal_minor")))}</dd><dt>Delivery</dt><dd>{_e(_money(quote.get("shipping_minor")))}</dd><dt>Total</dt><dd><strong>{_e(_money(quote.get("total_minor")))}</strong></dd><dt>Estimated arrival</dt><dd>{_e(quote.get("arrival_days"))} day(s)</dd></dl>{warning}</section>"""

    def _token_input(self) -> str:
        token = self._review_token()
        return f'<input type="hidden" name="review_token" value="{_e(token)}">'

    def _confirm(self) -> str:
        return (
            '<label><input type="checkbox" name="confirm" value="yes" required> '
            "I have reviewed the delivery details and total and want to place this simulated order.</label>"
            + self._field_error("confirm")
            + self._field_error("review_token")
        )

    def _render_accordion(self, catalog: Mapping[str, Any], cart: Mapping[str, Any]) -> str:
        selected = str(cart.get("method", ""))
        return f"""<main class="checkout accordion"><p class="simulation">Simulated checkout</p><h2>Checkout</h2>
<p>Complete all four sections. Update the order summary after changing your details or delivery method.</p>{self._error_summary()}
<form method="post" action="/checkout" novalidate>
<details open><summary>1. Contact</summary>{self._input("full_name", "Full name")}{self._input("email", "Email", "email")}{self._input("phone", "Phone (optional)", "tel", required=False)}</details>
<details><summary>2. Delivery address</summary>{self._input("address", "Street address")}{self._input("postal_code", "Postcode")}{self._input("city", "City")}<p>Destination: Sweden (SE)</p></details>
<details><summary>3. Delivery</summary>{self._method_fields(catalog, selected)}<button class="secondary" type="submit" formaction="/checkout/quote">Update order summary</button></details>
<details open><summary>4. Review and confirm</summary>{self._quote_summary(catalog, cart)}{self._token_input()}{self._confirm()}<div class="actions"><button type="submit">Place simulated order</button><a href="/cart">Back to cart</a></div></details>
</form></main>"""

    def _render_express(self, catalog: Mapping[str, Any], cart: Mapping[str, Any]) -> str:
        selected = str(cart.get("method", ""))
        p = self._saved_profile
        return f"""<main class="checkout express"><p class="simulation">Simulated checkout</p><h2>Express checkout</h2>
<p class="muted">Use the saved demo delivery details and review the current total.</p>{self._error_summary()}
<div class="express-grid"><address class="saved-address"><h3>Saved delivery address</h3><strong>{_e(p["full_name"])}</strong><br>{_e(p["address"])}<br>{_e(p["postal_code"])} {_e(p["city"])}<br>Sweden<br>{_e(p["phone"])}</address>{self._quote_summary(catalog, cart)}</div>
<form method="post" action="/checkout" novalidate>{self._input("email", "Receipt email", "email")}{self._method_fields(catalog, selected)}
<button class="secondary" type="submit" formaction="/checkout/quote">Update delivery and total</button>
{self._token_input()}{self._confirm()}<div class="actions"><button type="submit">Place simulated order</button><a href="/cart">Back to cart</a></div></form></main>"""

    def _wizard_progress(self, current: str) -> str:
        labels = (("contact", "Contact"), ("address", "Address"), ("delivery", "Delivery"), ("review", "Review"))
        rows = "".join(
            f'<li{" aria-current=\"step\"" if key == current else ""}>{index}. {_e(label)}</li>'
            for index, (key, label) in enumerate(labels, 1)
        )
        return f'<nav class="progress" aria-label="Checkout progress"><ol>{rows}</ol></nav>'

    def _render_wizard(self, path: str, catalog: Mapping[str, Any], cart: Mapping[str, Any]) -> str:
        requested = {
            "/checkout/contact": "contact",
            "/checkout/address": "address",
            "/checkout/delivery": "delivery",
            "/checkout/review": "review",
        }.get(path)
        target_path = self._wizard_target()
        target = target_path.rsplit("/", 1)[-1]
        current = target if path == "/checkout" else (requested or target)
        prerequisite_warning = ""
        order = ("contact", "address", "delivery", "review")
        if order.index(current) > order.index(target):
            current = target
            prerequisite_warning = '<div class="error-summary" role="alert">Complete the earlier checkout steps first.</div>'

        common = f'<p class="simulation">Simulated checkout</p><h2>Checkout</h2>{self._wizard_progress(current)}{prerequisite_warning}{self._error_summary()}'
        if current == "contact":
            panel = f"""<section class="panel"><h3>Contact details</h3><form method="post" action="/checkout/contact" novalidate>{self._input("full_name", "Full name")}{self._input("email", "Email", "email")}{self._input("phone", "Phone", "tel")}<div class="actions"><button type="submit">Continue to address</button><a href="/cart">Back to cart</a></div></form></section>"""
        elif current == "address":
            panel = f"""<section class="panel"><h3>Delivery address</h3><form method="post" action="/checkout/address" novalidate>{self._input("address", "Street address")}{self._input("postal_code", "Postcode")}{self._input("city", "City")}<p>Destination: Sweden (SE)</p><div class="actions"><a href="/checkout/contact">Back to contact</a><button type="submit">Continue to delivery</button></div></form></section>"""
        elif current == "delivery":
            panel = f"""<section class="panel"><h3>Delivery and payment</h3><form method="post" action="/checkout/delivery" novalidate>{self._method_fields(catalog, str(cart.get("method", "")))}{self._payment_fields()}<p>No real payment details are collected.</p><div class="actions"><a href="/checkout/address">Back to address</a><button type="submit">Review order</button></div></form></section>"""
        else:
            panel = self._wizard_review(catalog, cart)
        return f'<main class="checkout wizard">{common}{panel}</main>'

    def _wizard_review(self, catalog: Mapping[str, Any], cart: Mapping[str, Any]) -> str:
        d = self._draft
        return f"""<section class="panel"><h3>Review your order</h3>
<section aria-labelledby="review-contact"><h4 id="review-contact">Contact <a href="/checkout/contact">Edit</a></h4><p>{_e(d.get("full_name"))}<br>{_e(d.get("email"))}<br>{_e(d.get("phone"))}</p></section>
<section aria-labelledby="review-address"><h4 id="review-address">Delivery address <a href="/checkout/address">Edit</a></h4><address>{_e(d.get("address"))}<br>{_e(d.get("postal_code"))} {_e(d.get("city"))}<br>Sweden</address></section>
<section aria-labelledby="review-delivery"><h4 id="review-delivery">Delivery and simulated payment <a href="/checkout/delivery">Edit</a></h4><p>{_e(_label(cart.get("method")))}; {_e(_label(d.get("payment_method")))}</p></section>
{self._quote_summary(catalog, cart)}<form method="post" action="/checkout" novalidate>{self._token_input()}{self._confirm()}<div class="actions"><a href="/checkout/delivery">Back to delivery</a><button type="submit">Place simulated order</button></div></form></section>"""

    def snapshot(self) -> dict[str, object]:
        """Return detached private checkout state for trusted evaluation."""

        return copy.deepcopy(
            {
                "mode": self.mode,
                "draft": self._draft,
                "journal": self._journal,
                "committed_profiles": self._committed_profiles,
            }
        )
