from __future__ import annotations

import unittest

from .generator import aggregator_view, generate_world, retailer_view
from .renderers import render_page


class RendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.world = generate_world(7, "small")
        cls.origins = {"aggregator": "/directory", "nordhem": "/nordhem", "vardagslagret": "/vardagslagret", "teknikgarden": "/teknikgarden"}

    def context(self, site: str, variant: str = "compact") -> dict:
        catalog = aggregator_view(self.world) if site == "aggregator" else retailer_view(self.world, site)
        return {"catalog": catalog, "layout_variant": variant, "cart": None, "quote": None, "orders": [], "error": None}

    def test_legacy_brand_pages_render_without_claiming_design_diversity(self) -> None:
        pages = {site: render_page(site, "/", {}, self.context(site), self.origins) for site in ("aggregator", "nordhem", "vardagslagret", "teknikgarden")}
        self.assertIn("directory-shell", pages["aggregator"])
        self.assertIn("nordhem-site", pages["nordhem"])
        self.assertIn("vardagslagret-site", pages["vardagslagret"])
        self.assertIn("teknikgarden-site", pages["teknikgarden"])
        self.assertEqual(len(set(pages.values())), 4)

    def test_search_pagination_and_escaping(self) -> None:
        page = render_page("aggregator", "/search", {"q": "<script>", "page": "1"}, self.context("aggregator"), self.origins)
        self.assertNotIn("<script>", page)
        self.assertIn("No products matched", page)
        large = generate_world(7, "large")
        context = {"catalog": aggregator_view(large), "layout_variant": "expanded", "cart": None, "quote": None, "orders": [], "error": None}
        page = render_page("aggregator", "/search", {"page": "2"}, context, self.origins)
        self.assertIn('rel="prev"', page)
        self.assertIn("Page 2 of 8", page)

    def test_retailer_routes_use_authoritative_quote_and_forms(self) -> None:
        site = "nordhem"
        context = self.context(site, "expanded")
        offer = retailer_view(self.world, site)["offers"][0]
        product = offer["product_id"]
        product_page = render_page(site, f"/products/{product}", {}, context, self.origins)
        self.assertIn('method="post"', product_page)
        self.assertIn('action="/nordhem/cart/set"', product_page)
        self.assertTrue("Leave unchecked to decline" in product_page or "No optional extra is available" in product_page)
        quote = {"eligible": True, "reason_codes": [], "offer_id": offer["offer_id"], "product_id": product, "retailer_id": site, "quantity": 1, "destination": "SE", "method": "standard", "extra": False, "item_subtotal_minor": offer["price_minor"], "extra_subtotal_minor": 0, "shipping_minor": 4900, "total_minor": offer["price_minor"] + 4900, "arrival_days": 3}
        context["quote"] = quote
        context["cart"] = {"offer_id": offer["offer_id"], "quantity": 1, "destination": "SE", "method": "standard", "extra": False, "quote": quote}
        cart = render_page(site, "/cart", {}, context, self.origins)
        checkout = render_page(site, "/checkout", {}, context, self.origins)
        quote_page = render_page(site, "/quote", {"offer_id": offer["offer_id"]}, context, self.origins)
        self.assertIn("Complete total", cart)
        self.assertIn("Place simulated order", checkout)
        self.assertIn("Complete delivery quote", quote_page)
        self.assertIn(str(quote["total_minor"] // 100), quote_page)

    def test_unknown_routes_and_receipts_are_not_fake(self) -> None:
        context = self.context("teknikgarden")
        missing = render_page("teknikgarden", "/products/no-such-product", {}, context, self.origins)
        self.assertIn("Product not found", missing)
        receipt = render_page("teknikgarden", "/receipt/no-order", {}, context, self.origins)
        self.assertIn("Receipt not found", receipt)
        unsupported = render_page("aggregator", "/cart", {}, self.context("aggregator"), self.origins)
        self.assertIn("Page not found", unsupported)

    def test_one_line_cart_explains_remove_before_different_product(self) -> None:
        site = "nordhem"
        catalog = retailer_view(self.world, site)
        first_offer = catalog["offers"][0]
        second_product = next(product for product in catalog["products"] if product["product_id"] != first_offer["product_id"])
        quote = {"eligible": True, "offer_id": first_offer["offer_id"], "product_id": first_offer["product_id"], "quantity": 1, "destination": "SE", "method": "standard", "extra": False, "item_subtotal_minor": first_offer["price_minor"], "extra_subtotal_minor": 0, "shipping_minor": 4900, "total_minor": first_offer["price_minor"] + 4900, "arrival_days": 3}
        context = {"catalog": catalog, "layout_variant": "compact", "cart": {"offer_id": first_offer["offer_id"], "quantity": 1, "destination": "SE", "method": "standard", "extra": False, "quote": quote}, "quote": quote, "orders": [], "error": "cart_line_limit"}
        product_page = render_page(site, f"/products/{second_product['product_id']}", {}, context, self.origins)
        cart_page = render_page(site, "/cart", {}, context, self.origins)
        self.assertIn("one product line per basket", product_page)
        self.assertIn("remove the current line before adding another product", product_page)
        self.assertIn('href="/nordhem/cart"', product_page)
        self.assertIn("one product line per basket", cart_page)
        self.assertIn("Remove item", cart_page)


if __name__ == "__main__":
    unittest.main()
