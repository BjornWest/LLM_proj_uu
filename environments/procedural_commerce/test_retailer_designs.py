from __future__ import annotations

import unittest
from html.parser import HTMLParser

from .generator import generate_world, retailer_view
from .retailer_designs import render_retailer


class _Structure(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.starts: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.starts.append((tag, dict(attrs)))

    def tags(self, name: str) -> list[dict[str, str | None]]:
        return [attrs for tag, attrs in self.starts if tag == name]


class RetailerDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.world = generate_world(7, "small")
        cls.site = "nordhem"
        cls.catalog = retailer_view(cls.world, cls.site)
        cls.context = {"catalog": cls.catalog, "cart": None}
        cls.origins = {cls.site: "/store"}

    def render(self, design: str, path: str = "/", query: dict[str, str] | None = None, **options: object) -> str:
        rendered = render_retailer(
            self.site,
            path,
            query or {},
            self.context,
            self.origins,
            design,
            options or None,
        )
        self.assertIsInstance(rendered, str)
        return rendered or ""

    def test_home_navigation_landmarks_are_distinct(self) -> None:
        department = _Structure()
        department.feed(self.render("department-market"))
        editorial = _Structure()
        editorial.feed(self.render("editorial-boutique"))
        technical = _Structure()
        technical.feed(self.render("technical-catalog"))

        self.assertIn("Utility navigation", [row.get("aria-label") for row in department.tags("nav")])
        self.assertIn("Departments", [row.get("aria-label") for row in department.tags("nav")])
        self.assertIn("Primary navigation", [row.get("aria-label") for row in editorial.tags("nav")])
        self.assertIn("Catalog navigation", [row.get("aria-label") for row in technical.tags("nav")])
        self.assertEqual(len(technical.tags("header") and [row for row in technical.tags("nav") if row.get("aria-label") == "Primary navigation"]), 0)
        self.assertTrue(department.tags("aside"))
        self.assertTrue(technical.tags("aside"))

    def test_search_results_have_different_native_structures(self) -> None:
        department = _Structure()
        department.feed(self.render("department-market", "/search"))
        editorial = _Structure()
        editorial.feed(self.render("editorial-boutique", "/search"))
        technical = _Structure()
        technical.feed(self.render("technical-catalog", "/search"))

        self.assertGreaterEqual(len(department.tags("img")), len(self.catalog["products"]))
        self.assertTrue(editorial.tags("ol"))
        self.assertFalse(editorial.tags("img"))
        self.assertTrue(technical.tags("table"))
        self.assertTrue(any(row.get("scope") == "row" for row in technical.tags("th")))

    def test_product_forms_preserve_runtime_contract_and_images_have_factual_alt(self) -> None:
        offer = self.catalog["offers"][0]
        product_id = offer["product_id"]
        for design in ("department-market", "editorial-boutique", "technical-catalog"):
            page = self.render(design, f"/products/{product_id}")
            tree = _Structure()
            tree.feed(page)
            purchase = [row for row in tree.tags("form") if row.get("action") == "/store/cart/set"]
            self.assertEqual(len(purchase), 1)
            names = {row.get("name") for row in tree.tags("input") + tree.tags("select")}
            self.assertTrue({"offer_id", "quantity", "destination", "method"} <= names)
            self.assertIn(f"Offer ID: {offer['offer_id']}", page)
            self.assertIn("/store/quote?offer_id=", page)
            self.assertIn("quantity=1", page)
            self.assertIn("destination=SE", page)
            self.assertIn("method=standard", page)
            for image in tree.tags("img"):
                self.assertTrue((image.get("src") or "").startswith("data:image/svg+xml,"))
                self.assertIn("catalog illustration/view", image.get("alt") or "")
        technical = self.render("technical-catalog", f"/products/{product_id}")
        technical_tree = _Structure()
        technical_tree.feed(technical)
        self.assertTrue(technical_tree.tags("fieldset"))
        self.assertTrue(technical_tree.tags("details"))
        self.assertTrue(all("open" not in row for row in technical_tree.tags("details")))

    def test_editorial_details_are_linked_and_separate(self) -> None:
        product = self.catalog["products"][0]
        path = f"/products/{product['product_id']}"
        page = self.render("editorial-boutique", path)
        self.assertIn(f'{path}/details', page)
        self.assertNotIn("Full catalog attributes", page)
        details = self.render("editorial-boutique", path + "/details")
        self.assertIn("Full catalog attributes", details)
        for key, value in product["attributes"].items():
            self.assertIn(str(value), details)
            self.assertIn(key.replace("_", " ").capitalize(), details)

    def test_catalog_projection_is_escaped_and_private_data_is_not_rendered(self) -> None:
        catalog = retailer_view(self.world, self.site)
        catalog["products"][0]["name"] = '<script data-private="renderer_key">leak</script>'
        context = {"catalog": catalog, "cart": None, "private_provenance": "DO-NOT-RENDER"}
        page = render_retailer(
            self.site,
            f"/products/{catalog['products'][0]['product_id']}",
            {},
            context,
            self.origins,
            "department-market",
            None,
        )
        self.assertIsInstance(page, str)
        self.assertNotIn("<script", page or "")
        self.assertNotIn("DO-NOT-RENDER", page or "")
        self.assertNotIn("private_provenance", page or "")

    def test_options_change_semantics_and_reject_incompatible_details(self) -> None:
        collapsed = self.render("department-market", nav_expanded=False)
        expanded = self.render("department-market", nav_expanded=True)
        self.assertGreater(expanded.count("/products/"), collapsed.count("/products/"))
        product_id = self.catalog["products"][0]["product_id"]
        one = self.render("department-market", f"/products/{product_id}", image_count=1)
        two = self.render("department-market", f"/products/{product_id}", image_count=2)
        self.assertEqual(one.count("<img "), 1)
        self.assertEqual(two.count("<img "), 2)
        with self.assertRaises(ValueError):
            render_retailer(self.site, "/", {}, self.context, self.origins, "technical-catalog", {"details_presentation": "inline"})

    def test_runtime_legacy_style_option_does_not_cross_design_boundary(self) -> None:
        page = self.render("department-market", legacy_style="boutique")
        self.assertIn('aria-label="Departments"', page)
        self.assertNotIn("boutique-story", page)

    def test_transaction_routes_fall_back_to_existing_renderer(self) -> None:
        for route in ("/cart", "/quote", "/checkout", "/policy", "/receipt/order-1"):
            self.assertIsNone(render_retailer(self.site, route, {}, self.context, self.origins, "department-market", None))

    def test_every_design_navigation_reaches_policy(self) -> None:
        for design in ("department-market", "editorial-boutique", "technical-catalog"):
            page = self.render(design, nav_expanded=False)
            self.assertIn('href="/store/policy"', page)


if __name__ == "__main__":
    unittest.main()
