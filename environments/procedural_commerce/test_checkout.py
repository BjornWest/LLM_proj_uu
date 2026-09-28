from __future__ import annotations

import copy
from html import unescape
import re

import pytest

from .checkout import (
    CHECKOUT_FIELDS,
    CHECKOUT_GET_PATHS,
    CHECKOUT_POST_PATHS,
    DEMO_PROFILE,
    CheckoutFlow,
)
from .engine import CommerceSession
from .generator import generate_world, retailer_view


@pytest.fixture
def shop():
    world = generate_world(71, parameters={"stockout_probability": 0})
    retailer_id = world["retailers"][0]["retailer_id"]
    offer = next(row for row in world["offers"] if row["retailer_id"] == retailer_id)
    session = CommerceSession(world)
    assert session.set_cart(offer["offer_id"], extra=False)["ok"]
    return world, retailer_id, offer, session, retailer_view(world, retailer_id)


def _render(flow, catalog, path="/checkout") -> str:
    status, html = flow.render(path, catalog, {})
    assert status == 200
    return html


def _token(html: str) -> str:
    match = re.search(r'name="review_token" value="([^"]*)"', html)
    assert match is not None
    return unescape(match.group(1))


def _accordion_fields(method="standard", **changes):
    fields = {
        "full_name": DEMO_PROFILE["full_name"],
        "email": DEMO_PROFILE["email"],
        "phone": DEMO_PROFILE["phone"],
        "address": DEMO_PROFILE["address"],
        "postal_code": DEMO_PROFILE["postal_code"],
        "city": DEMO_PROFILE["city"],
        "method": method,
    }
    fields.update(changes)
    return fields


def _complete_wizard(flow: CheckoutFlow, *, method="standard"):
    assert flow.submit(
        "/checkout/contact",
        {
            "full_name": DEMO_PROFILE["full_name"],
            "email": DEMO_PROFILE["email"],
            "phone": DEMO_PROFILE["phone"],
        },
    ) == "/checkout/address"
    assert flow.submit(
        "/checkout/address",
        {
            "address": DEMO_PROFILE["address"],
            "postal_code": DEMO_PROFILE["postal_code"],
            "city": DEMO_PROFILE["city"],
        },
    ) == "/checkout/delivery"
    assert flow.submit(
        "/checkout/delivery",
        {"method": method, "payment_method": "demo-card"},
    ) == "/checkout/review"


def test_public_contract_and_three_distinct_accessible_architectures(shop):
    _, retailer_id, _, session, catalog = shop
    assert CHECKOUT_FIELDS == {
        "full_name", "email", "phone", "address", "postal_code", "city",
        "method", "payment_method", "confirm", "review_token",
    }
    assert "/checkout/review" in CHECKOUT_GET_PATHS
    assert "/checkout/quote" in CHECKOUT_POST_PATHS

    accordion = _render(CheckoutFlow(session, retailer_id, "accordion"), catalog)
    express = _render(CheckoutFlow(session, retailer_id, "express"), catalog)
    wizard = _render(CheckoutFlow(session, retailer_id, "wizard"), catalog)
    assert accordion.count("<details") == 4
    assert "Update order summary" in accordion
    assert "Saved delivery address" in express
    assert "Express checkout" in express
    assert 'aria-label="Checkout progress"' in wizard
    assert 'action="/checkout/contact"' in wizard
    for html in (accordion, express, wizard):
        assert "Simulated checkout" in html
        assert "no real payment or personal data" in html.lower()
        assert "novalidate" in html
        assert 'name="card' not in html
        assert "private_provenance" not in html


def test_accordion_native_quote_shape_sticky_errors_escaping_and_commit(shop):
    _, retailer_id, _, session, catalog = shop
    flow = CheckoutFlow(session, retailer_id, "accordion")
    bad = _accordion_fields(
        full_name='<script>alert("x")</script>',
        email="bad",
        postal_code="12",
    )
    # Native formaction submits every successful control in the enclosing form,
    # including its hidden review token and a checked confirmation box.
    bad.update({"review_token": "", "confirm": "yes"})
    assert flow.submit("/checkout/quote", bad) == "/checkout"
    assert session.snapshot()["orders"] == []
    html = _render(flow, catalog)
    assert "Enter a valid email address" in html
    assert "Enter a five-digit Swedish postcode" in html
    assert "&lt;script&gt;" in html and "<script>alert" not in html

    quote_form = _accordion_fields()
    quote_form["review_token"] = "old-token"
    assert flow.submit("/checkout/quote", quote_form) == "/checkout"
    html = _render(flow, catalog)
    token = _token(html)
    assert token
    final = {**quote_form, "review_token": token, "confirm": "yes"}
    assert flow.submit("/checkout", final) == "/receipt/order-000001"
    snap = flow.snapshot()
    assert snap["committed_profiles"]["order-000001"]["address"] == DEMO_PROFILE["address"]
    assert len(session.snapshot()["orders"]) == 1


def test_wizard_enforces_prerequisites_supports_back_edit_and_direct_final_rejected(shop):
    _, retailer_id, _, session, catalog = shop
    flow = CheckoutFlow(session, retailer_id, "wizard")
    assert flow.submit(
        "/checkout/address",
        {"address": "Skip 1", "postal_code": "12345", "city": "Stockholm"},
    ) == "/checkout/contact"
    direct_review = _render(flow, catalog, "/checkout/review")
    assert "Complete the earlier checkout steps first" in direct_review
    assert 'action="/checkout/contact"' in direct_review
    assert "Place simulated order" not in direct_review
    assert flow.submit(
        "/checkout", {"review_token": "made-up", "confirm": "yes"}
    ) == "/checkout/contact"
    assert session.snapshot()["orders"] == []

    _complete_wizard(flow)
    first_review = _render(flow, catalog, "/checkout/review")
    stale = _token(first_review)
    assert flow.submit(
        "/checkout/contact",
        {
            "full_name": "Edited Example",
            "email": DEMO_PROFILE["email"],
            "phone": DEMO_PROFILE["phone"],
        },
    ) == "/checkout/address"
    edited_review = _render(flow, catalog, "/checkout/review")
    assert "Edited Example" in edited_review
    assert _token(edited_review) != stale
    assert flow.submit(
        "/checkout", {"review_token": stale, "confirm": "yes"}
    ) == "/checkout/review"
    assert session.snapshot()["orders"] == []
    assert "changed" in _render(flow, catalog, "/checkout/review").lower()


def test_delivery_reprice_requires_second_confirmation_and_changes_only_method(shop):
    _, retailer_id, _, session, catalog = shop
    flow = CheckoutFlow(session, retailer_id, "express")
    before = copy.deepcopy(session.quote_cart(retailer_id))
    old_token = _token(_render(flow, catalog))
    attempted = {
        "email": DEMO_PROFILE["email"],
        "method": "express",
        "confirm": "yes",
        "review_token": old_token,
    }
    assert flow.submit("/checkout", attempted) == "/checkout"
    changed = session.quote_cart(retailer_id)
    assert changed["method"] == "express"
    assert changed["quantity"] == before["quantity"]
    assert changed["extra"] == before["extra"]
    assert changed["quote"]["total_minor"] != before["quote"]["total_minor"]
    assert session.snapshot()["orders"] == []
    changed_html = _render(flow, catalog)
    assert "delivery price changed" in changed_html.lower()
    new_token = _token(changed_html)
    assert new_token != old_token
    attempted["review_token"] = new_token
    assert flow.submit("/checkout", attempted) == "/receipt/order-000001"


def test_cart_change_then_revert_keeps_old_review_token_stale(shop):
    _, retailer_id, _, session, catalog = shop
    flow = CheckoutFlow(session, retailer_id, "express")
    token = _token(_render(flow, catalog))
    assert session.update_cart(retailer_id, method="express")["ok"]
    flow.invalidate_cart()
    assert session.update_cart(retailer_id, method="standard")["ok"]
    flow.invalidate_cart()
    assert flow.submit(
        "/checkout",
        {
            "email": DEMO_PROFILE["email"],
            "method": "standard",
            "confirm": "yes",
            "review_token": token,
        },
    ) == "/checkout"
    assert session.snapshot()["orders"] == []
    assert "changed" in _render(flow, catalog).lower()


def test_duplicate_final_submit_is_idempotent(shop):
    _, retailer_id, _, session, catalog = shop
    flow = CheckoutFlow(session, retailer_id, "express")
    form = {
        "email": DEMO_PROFILE["email"],
        "method": "standard",
        "confirm": "yes",
        "review_token": _token(_render(flow, catalog)),
    }
    assert flow.submit("/checkout", form) == "/receipt/order-000001"
    assert flow.submit("/checkout", form) == "/receipt/order-000001"
    assert len(session.snapshot()["orders"]) == 1
    assert [row["result"] for row in flow.snapshot()["journal"] if row["action"] == "commit"][-2:] == [
        "committed", "replayed"
    ]


def test_missing_unknown_duplicate_like_and_empty_cart_never_commit(shop):
    _, retailer_id, _, session, catalog = shop
    flow = CheckoutFlow(session, retailer_id, "express")
    token = _token(_render(flow, catalog))
    assert flow.submit("/checkout", {"review_token": token, "confirm": "yes"}) == "/checkout"
    assert flow.submit(
        "/checkout",
        {
            "email": [DEMO_PROFILE["email"], "other@example.test"],
            "method": "standard",
            "confirm": "yes",
            "review_token": token,
        },
    ) == "/checkout"
    assert session.snapshot()["orders"] == []

    assert session.remove_cart(retailer_id)["ok"]
    flow.invalidate_cart()
    html = _render(flow, catalog)
    assert "cart is empty" in html.lower()
    assert flow.submit(
        "/checkout",
        {
            "email": DEMO_PROFILE["email"], "method": "standard",
            "confirm": "yes", "review_token": token,
        },
    ) == "/checkout"
    assert session.snapshot()["orders"] == []


def test_retailer_controllers_are_isolated_and_get_is_commerce_read_only():
    world = generate_world(81, parameters={"stockout_probability": 0})
    session = CommerceSession(world)
    retailer_ids = [row["retailer_id"] for row in world["retailers"][:2]]
    for retailer_id in retailer_ids:
        offer = next(row for row in world["offers"] if row["retailer_id"] == retailer_id)
        assert session.set_cart(offer["offer_id"], extra=False)["ok"]
    left = CheckoutFlow(session, retailer_ids[0], "express")
    right = CheckoutFlow(session, retailer_ids[1], "express")
    catalog = retailer_view(world, retailer_ids[0])
    before_session = session.snapshot()
    before_flow = left.snapshot()
    first = _render(left, catalog)
    second = _render(left, catalog)
    assert first == second
    assert session.snapshot() == before_session
    assert left.snapshot() == before_flow

    token = _token(first)
    assert left.submit(
        "/checkout",
        {
            "email": DEMO_PROFILE["email"], "method": "standard",
            "confirm": "yes", "review_token": token,
        },
    ) == "/receipt/order-000001"
    assert right.snapshot()["committed_profiles"] == {}
    assert session.quote_cart(retailer_ids[1]) is not None


def test_snapshot_is_detached_and_contains_no_review_secret(shop):
    _, retailer_id, _, session, _ = shop
    flow = CheckoutFlow(session, retailer_id, "express")
    snapshot = flow.snapshot()
    assert set(snapshot) == {"mode", "draft", "journal", "committed_profiles"}
    snapshot["draft"]["email"] = "changed@example.test"
    assert flow.snapshot()["draft"]["email"] == DEMO_PROFILE["email"]
    assert "secret" not in repr(flow.snapshot()).lower()
