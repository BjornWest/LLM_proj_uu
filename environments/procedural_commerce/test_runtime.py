"""HTTP and privacy tests for the procedural commerce runtime."""

from __future__ import annotations

import copy
import http.client
import threading
import unittest
from urllib.parse import urlencode, urlsplit

from environments.procedural_commerce.generator import generate_world
from environments.procedural_commerce.runtime import Runtime


class RuntimeHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.world = generate_world(37)
        self.runtime = Runtime(self.world)

    def tearDown(self) -> None:
        self.runtime.close()

    def request(
        self,
        site: str,
        path: str,
        *,
        method: str = "GET",
        fields: dict[str, str] | None = None,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], str]:
        parsed = urlsplit(self.runtime.origins[site])
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
        request_headers = dict(headers or {})
        if fields is not None:
            body = urlencode(fields).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        result = (
            response.status,
            {key.lower(): value for key, value in response.getheaders()},
            raw.decode("utf-8"),
        )
        connection.close()
        return result

    def stocked_offer(self, retailer_id: str) -> dict:
        return next(
            offer
            for offer in self.world["offers"]
            if offer["retailer_id"] == retailer_id and offer["stock_quantity"] > 0
        )

    def test_four_distinct_origins_serve_only_their_supported_pages(self) -> None:
        self.assertEqual(
            set(self.runtime.origins),
            {"aggregator", "nordhem", "vardagslagret", "teknikgarden"},
        )
        self.assertEqual(len(set(self.runtime.origins.values())), 4)
        for site in self.runtime.origins:
            status, headers, body = self.request(site, "/")
            self.assertEqual(status, 200)
            self.assertTrue(headers["content-type"].startswith("text/html"))
            self.assertIn("<!doctype html>", body.lower())

        self.assertEqual(self.request("aggregator", "/cart")[0], 404)
        self.assertEqual(self.request("nordhem", "/world")[0], 404)
        self.assertEqual(self.request("nordhem", "/snapshot")[0], 404)
        self.assertEqual(self.request("nordhem", "/ready")[0], 404)
        self.assertEqual(self.request("nordhem", "/cart", method="PUT")[0], 405)
        self.assertEqual(self.request("nordhem", "/not-a-route", method="PUT")[0], 404)

    def test_native_form_post_cart_checkout_and_scoped_receipt(self) -> None:
        offer = self.stocked_offer("nordhem")
        status, headers, _ = self.request(
            "nordhem",
            "/cart/set",
            method="POST",
            fields={
                "offer_id": offer["offer_id"],
                "quantity": "1",
                "destination": "SE",
                "method": "standard",
                "extra": "false",
            },
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/cart")
        cart = self.runtime.snapshot()["carts"]["nordhem"]
        self.assertEqual(cart["offer_id"], offer["offer_id"])

        status, headers, _ = self.request(
            "nordhem", "/checkout", method="POST", fields={}
        )
        self.assertEqual(status, 303)
        self.assertRegex(headers["location"], r"^/receipt/order-[0-9]{6}$")
        receipt_path = headers["location"]
        status, _, receipt = self.request("nordhem", receipt_path)
        self.assertEqual(status, 200)
        self.assertIn(offer["offer_id"], receipt)
        self.assertIn("Order confirmed", receipt)

        self.assertEqual(self.request("vardagslagret", receipt_path)[0], 404)
        snapshot = self.runtime.snapshot()
        self.assertIsNone(snapshot["carts"]["nordhem"])
        self.assertEqual(len(snapshot["orders"]), 1)
        self.assertEqual(snapshot["orders"][0]["quote"]["retailer_id"], "nordhem")

    def test_retailer_origin_cannot_mutate_or_read_another_retailer(self) -> None:
        offer = self.stocked_offer("nordhem")
        before = self.runtime.snapshot()
        status, headers, _ = self.request(
            "vardagslagret",
            "/cart/set",
            method="POST",
            fields={"offer_id": offer["offer_id"], "quantity": "1"},
        )
        self.assertEqual(status, 303)
        self.assertTrue(headers["location"].startswith("/cart?notice="))
        self.assertEqual(self.runtime.snapshot(), before)
        self.assertEqual(
            self.request(
                "vardagslagret", f"/quote?offer_id={offer['offer_id']}"
            )[0],
            404,
        )

        self.request(
            "nordhem",
            "/cart/set",
            method="POST",
            fields={"offer_id": offer["offer_id"], "quantity": "1", "extra": "false"},
        )
        status, _, other_cart = self.request("vardagslagret", "/cart")
        self.assertEqual(status, 200)
        self.assertNotIn(offer["offer_id"], other_cart)
        self.assertIn("cart is empty", other_cart.lower())

    def test_public_html_omits_private_world_and_session_data(self) -> None:
        self.runtime.close()
        world = copy.deepcopy(self.world)
        sentinel = "PRIVATE-ORACLE-SENTINEL-7f0ce"
        world["private_provenance"]["secret_review_label"] = sentinel
        self.runtime = Runtime(world)
        product_id = world["products"][0]["product_id"]
        paths = ["/", "/search?q=", f"/products/{product_id}"]
        bodies: list[str] = []
        for site in self.runtime.origins:
            for path in paths:
                status, _, body = self.request(site, path)
                self.assertEqual(status, 200)
                bodies.append(body)
            if site != "aggregator":
                for path in ("/policy", "/cart", "/checkout"):
                    status, _, body = self.request(site, path)
                    self.assertEqual(status, 200)
                    bodies.append(body)
        public_html = "\n".join(bodies)
        self.assertNotIn(sentinel, public_html)
        self.assertNotIn("private_provenance", public_html)
        self.assertNotIn("reference_price_minor", public_html)
        self.assertNotIn("stock_by_offer", public_html)
        self.assertNotIn("event-", public_html)

    def test_validation_body_limit_and_redirects_do_not_trust_host(self) -> None:
        offer = self.stocked_offer("nordhem")
        status, _, _ = self.request(
            "nordhem",
            "/cart/set",
            method="POST",
            fields={"offer_id": offer["offer_id"], "quantity": "true"},
        )
        self.assertEqual(status, 400)
        self.assertTrue(all(cart is None for cart in self.runtime.snapshot()["carts"].values()))

        status, _, _ = self.request(
            "nordhem",
            "/cart/set",
            method="POST",
            body=b"x" * 16_385,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 413)

        status, headers, _ = self.request(
            "nordhem",
            "/cart/set",
            method="POST",
            fields={"offer_id": offer["offer_id"], "quantity": "1", "extra": "false"},
            headers={"Host": "attacker.invalid"},
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/cart")
        status, _, html = self.request(
            "nordhem", "/cart", headers={"Host": "attacker.invalid"}
        )
        self.assertEqual(status, 200)
        self.assertNotIn("attacker.invalid", html)
        for origin in self.runtime.origins.values():
            self.assertTrue(origin.startswith("http://127.0.0.1:"))

    def test_live_quote_uses_session_stock(self) -> None:
        offer = self.stocked_offer("nordhem")
        quantity = offer["stock_quantity"]
        self.request(
            "nordhem",
            "/cart/set",
            method="POST",
            fields={
                "offer_id": offer["offer_id"],
                "quantity": str(quantity),
                "extra": "false",
            },
        )
        self.assertEqual(
            self.request("nordhem", "/checkout", method="POST", fields={})[0], 303
        )
        query = urlencode(
            {
                "offer_id": offer["offer_id"],
                "quantity": "1",
                "destination": "SE",
                "method": "standard",
                "extra": "false",
            }
        )
        status, _, body = self.request("nordhem", "/quote?" + query)
        self.assertEqual(status, 200)
        self.assertIn("cannot currently be purchased", body)
        self.assertIn("out_of_stock", body)

    def test_unchecked_extra_on_cart_update_explicitly_deselects_it(self) -> None:
        offer = next(
            row
            for row in self.world["offers"]
            if row["extra_preselected"] and row["stock_quantity"] > 0
        )
        site = offer["retailer_id"]
        status, _, _ = self.request(
            site,
            "/cart/set",
            method="POST",
            fields={"offer_id": offer["offer_id"], "quantity": "1", "extra": "true"},
        )
        self.assertEqual(status, 303)
        self.assertIs(self.runtime.snapshot()["carts"][site]["extra"], True)

        # This is the native form encoding for an unchecked checkbox: the extra
        # control is absent while the other successful controls are submitted.
        status, headers, _ = self.request(
            site,
            "/cart/update",
            method="POST",
            fields={"quantity": "1", "destination": "SE", "method": "standard"},
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/cart")
        snapshot = self.runtime.snapshot()
        self.assertIs(snapshot["carts"][site]["extra"], False)
        self.assertIs(snapshot["events"][-1]["payload"]["extra"], False)

    def test_unchecked_extra_on_first_cart_set_overrides_public_preselection(self) -> None:
        offer = next(
            row
            for row in self.world["offers"]
            if row["extra_preselected"] and row["stock_quantity"] > 0
        )
        site = offer["retailer_id"]
        status, headers, _ = self.request(
            site,
            "/cart/set",
            method="POST",
            fields={
                "offer_id": offer["offer_id"],
                "quantity": "1",
                "destination": "SE",
                "method": "standard",
            },
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/cart")
        snapshot = self.runtime.snapshot()
        self.assertIs(snapshot["carts"][site]["extra"], False)
        self.assertIs(snapshot["events"][-1]["payload"]["extra"], False)

    def test_cart_line_limit_has_clear_remove_guidance(self) -> None:
        first = self.stocked_offer("nordhem")
        second = next(
            row
            for row in self.world["offers"]
            if row["retailer_id"] == "nordhem"
            and row["offer_id"] != first["offer_id"]
        )
        self.request(
            "nordhem",
            "/cart/set",
            method="POST",
            fields={"offer_id": first["offer_id"], "quantity": "1"},
        )
        status, headers, _ = self.request(
            "nordhem",
            "/cart/set",
            method="POST",
            fields={"offer_id": second["offer_id"], "quantity": "1"},
        )
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/cart?notice=cart_line_limit")
        status, _, body = self.request("nordhem", headers["location"])
        self.assertEqual(status, 200)
        self.assertIn("Remove it before selecting another product", body)
        self.assertEqual(
            self.runtime.snapshot()["carts"]["nordhem"]["offer_id"],
            first["offer_id"],
        )

    def test_concurrent_posts_are_serialized_without_lost_orders(self) -> None:
        offers = [
            self.stocked_offer(retailer_id)
            for retailer_id in ("nordhem", "vardagslagret", "teknikgarden")
        ]
        barrier = threading.Barrier(len(offers))
        failures: list[BaseException] = []

        def add(offer: dict) -> None:
            try:
                barrier.wait(timeout=2)
                status, _, _ = self.request(
                    offer["retailer_id"],
                    "/cart/set",
                    method="POST",
                    fields={
                        "offer_id": offer["offer_id"],
                        "quantity": "1",
                        "extra": "false",
                    },
                )
                if status != 303:
                    raise AssertionError(status)
            except BaseException as exc:  # make thread failures visible to unittest
                failures.append(exc)

        threads = [threading.Thread(target=add, args=(offer,)) for offer in offers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        self.assertFalse(failures)
        snapshot = self.runtime.snapshot()
        self.assertEqual(sum(cart is not None for cart in snapshot["carts"].values()), 3)
        self.assertEqual(len(snapshot["events"]), 3)


class RuntimeIsolationTests(unittest.TestCase):
    def test_runtimes_have_isolated_state_and_ports(self) -> None:
        world = generate_world(8)
        first = Runtime(world)
        second = Runtime(world)
        try:
            offer = next(row for row in world["offers"] if row["stock_quantity"] > 0)
            first.session.set_cart(offer["offer_id"], extra=False)
            self.assertIsNotNone(
                first.snapshot()["carts"][offer["retailer_id"]]
            )
            self.assertTrue(all(cart is None for cart in second.snapshot()["carts"].values()))
            self.assertTrue(set(first.origins.values()).isdisjoint(second.origins.values()))
            first.close()
            first.close()
        finally:
            first.close()
            second.close()


if __name__ == "__main__":
    unittest.main()
