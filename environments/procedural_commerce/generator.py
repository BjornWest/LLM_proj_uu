"""Deterministic, synthetic commerce-world and task generation.

This module deliberately contains no task oracle.  A world is generated first, and a
task is sampled later from product identity and reference data only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import random
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "procedural-commerce-world-v1"
TASK_SCHEMA_VERSION = "procedural-commerce-task-v1"
GENERATOR_VERSION = "procedural-commerce-generator-v1"
SCENARIO_DATE = "2026-05-18"
CURRENCY = "SEK"

_SCALE_COUNTS = {"small": 12, "large": 96}
_DEFAULT_PARAMETERS = {
    "stockout_probability": 1.0 / 6.0,
    "stale_claim_probability": 0.2,
    "preselected_extra_probability": 0.34,
}

_CATEGORIES: tuple[dict[str, Any], ...] = (
    {
        "category": "lighting",
        "nouns": ("Table Lamp", "Floor Lamp", "Desk Lamp", "Reading Light"),
        "price_range": (24_900, 189_900),
        "attributes": {"power_source": "mains", "room": "indoor"},
        "traits": ("single configuration",),
    },
    {
        "category": "kitchen",
        "nouns": ("Kettle", "Toaster", "Coffee Grinder", "Hand Mixer"),
        "price_range": (39_900, 219_900),
        "attributes": {"power_source": "mains", "room": "kitchen"},
        "traits": ("single configuration",),
    },
    {
        "category": "cleaning",
        "nouns": ("Stick Vacuum", "Steam Mop", "Window Cleaner", "Air Purifier"),
        "price_range": (89_900, 449_900),
        "attributes": {"use": "household", "room": "multi-room"},
        "traits": ("single configuration",),
    },
    {
        "category": "home-office",
        "nouns": ("Desk Fan", "Paper Shredder", "Label Printer", "Monitor Stand"),
        "price_range": (49_900, 299_900),
        "attributes": {"use": "home office", "configuration": "single"},
        "traits": ("single configuration",),
    },
    {
        "category": "comfort",
        "nouns": ("Heated Throw", "Humidifier", "Wake-up Light", "Tower Fan"),
        "price_range": (59_900, 349_900),
        "attributes": {"use": "household", "room": "indoor"},
        "traits": ("single configuration",),
    },
    {
        "category": "laundry",
        "nouns": ("Garment Steamer", "Drying Rack", "Fabric Shaver", "Steam Iron"),
        "price_range": (29_900, 249_900),
        "attributes": {"use": "laundry", "configuration": "single"},
        "traits": ("single configuration",),
    },
)

_BRANDS = (
    "Nordvale",
    "Ljusvik",
    "Hemro",
    "Sundby",
    "Vardag",
    "Klint",
    "Eken",
    "Myrholm",
    "Fjallbo",
    "Solvik",
    "Alva",
    "Bergstrand",
)

_MODEL_WORDS = (
    "Halo",
    "Mossa",
    "Niva",
    "Luna",
    "Bris",
    "Klara",
    "Nova",
    "Svala",
    "Glanta",
    "Dagg",
    "Vinga",
    "Saga",
)

_RETAILER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "retailer_id": "nordhem",
        "name": "Nordhem",
        "renderer_key": "nordic_catalog",
        "operating_profile": {
            "support_channel": "chat_and_email",
            "weekday_cutoff_hour": 15,
            "warehouse_region": "central",
        },
        "shipping_methods": {
            "standard": {
                "base_price_minor": 4_900,
                "free_shipping_threshold_minor": 150_000,
                "transit_days": 2,
            },
            "express": {
                "base_price_minor": 12_900,
                "free_shipping_threshold_minor": None,
                "transit_days": 1,
            },
        },
        "policy_summary": {
            "returns_days": 30,
            "return_shipping_paid_by": "customer",
            "warranty_years": 2,
        },
    },
    {
        "retailer_id": "vardagslagret",
        "name": "Vardagslagret",
        "renderer_key": "warehouse_market",
        "operating_profile": {
            "support_channel": "email",
            "weekday_cutoff_hour": 13,
            "warehouse_region": "south",
        },
        "shipping_methods": {
            "standard": {
                "base_price_minor": 6_900,
                "free_shipping_threshold_minor": 200_000,
                "transit_days": 3,
            },
            "express": {
                "base_price_minor": 14_900,
                "free_shipping_threshold_minor": None,
                "transit_days": 1,
            },
        },
        "policy_summary": {
            "returns_days": 45,
            "return_shipping_paid_by": "retailer",
            "warranty_years": 2,
        },
    },
    {
        "retailer_id": "teknikgarden",
        "name": "Teknikgarden",
        "renderer_key": "specialist_shop",
        "operating_profile": {
            "support_channel": "phone_and_email",
            "weekday_cutoff_hour": 16,
            "warehouse_region": "north",
        },
        "shipping_methods": {
            "standard": {
                "base_price_minor": 5_900,
                "free_shipping_threshold_minor": 175_000,
                "transit_days": 2,
            },
            "express": {
                "base_price_minor": 16_900,
                "free_shipping_threshold_minor": None,
                "transit_days": 1,
            },
        },
        "policy_summary": {
            "returns_days": 30,
            "return_shipping_paid_by": "customer",
            "warranty_years": 3,
        },
    },
)


def _require_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _rng(seed: int, namespace: str) -> random.Random:
    material = f"{GENERATOR_VERSION}\0{seed}\0{namespace}".encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _rounded_hundreds(value: int) -> int:
    return max(100, ((value + 50) // 100) * 100)


def _product(seed: int, index: int) -> dict[str, Any]:
    rng = _rng(seed, f"product/{index:03d}")
    category = _CATEGORIES[index % len(_CATEGORIES)]
    noun = category["nouns"][(index // len(_CATEGORIES)) % len(category["nouns"])]
    brand = _BRANDS[rng.randrange(len(_BRANDS))]
    model_word = _MODEL_WORDS[rng.randrange(len(_MODEL_WORDS))]
    low, high = category["price_range"]
    reference_price = _rounded_hundreds(rng.randrange(low // 100, high // 100 + 1) * 100)
    product_number = index + 1
    return {
        "product_id": f"product-{product_number:03d}",
        "name": f"{brand} {model_word} {noun} {product_number:02d}",
        "category": category["category"],
        "reference_price_minor": reference_price,
        "attributes": copy.deepcopy(category["attributes"]),
        "traits": list(category["traits"]),
    }


def _retailers() -> list[dict[str, Any]]:
    return copy.deepcopy(list(_RETAILER_SPECS))


def _retailer_residual(seed: int, retailer_id: str) -> int:
    # A stable retailer-wide tendency induces price correlation without coupling a task
    # or public claim to the eventual winner.
    return _rng(seed, f"retailer/{retailer_id}/pricing").randint(-550, 550)


def _offer(
    seed: int,
    product: dict[str, Any],
    retailer: dict[str, Any],
    residual: int,
    parameters: dict[str, float],
) -> dict[str, Any]:
    product_id = product["product_id"]
    retailer_id = retailer["retailer_id"]
    stream_root = f"offer/{product_id}/{retailer_id}"
    pricing_rng = _rng(seed, f"{stream_root}/pricing")
    inventory_rng = _rng(seed, f"{stream_root}/inventory")
    fulfillment_rng = _rng(seed, f"{stream_root}/fulfillment")
    extras_rng = _rng(seed, f"{stream_root}/extras")
    offer_noise = pricing_rng.randint(-900, 900)
    raw_price = product["reference_price_minor"] * (10_000 + residual + offer_noise) // 10_000
    extra_available = extras_rng.random() < 0.72
    if extra_available:
        extra_price = _rounded_hundreds(extras_rng.randint(4_900, 29_900))
        extra_name: str | None = "Extended care package"
        preselection_draw = extras_rng.random()
        extra_preselected = preselection_draw < parameters["preselected_extra_probability"]
    else:
        extra_price = None
        extra_name = None
        extra_preselected = False
    return {
        "offer_id": f"offer-{product_id}-{retailer_id}",
        "product_id": product_id,
        "retailer_id": retailer_id,
        "price_minor": _rounded_hundreds(raw_price),
        "stock_quantity": (
            0
            if inventory_rng.random() < parameters["stockout_probability"]
            else inventory_rng.randint(1, 5)
        ),
        "dispatch_days": fulfillment_rng.randint(0, 4),
        "extra_name": extra_name,
        "extra_price_minor": extra_price,
        "extra_preselected": extra_preselected,
    }


def _claim(
    seed: int, offer: dict[str, Any], parameters: dict[str, float]
) -> dict[str, Any]:
    rng = _rng(seed, f"claim/{offer['offer_id']}")
    stale = rng.random() < parameters["stale_claim_probability"]
    if stale:
        adjustment = rng.choice((-1, 1)) * rng.randrange(500, 8_001, 100)
    else:
        adjustment = 0
    advertised = max(100, offer["price_minor"] + adjustment)
    return {
        "claim_id": f"claim-{offer['offer_id']}",
        "offer_id": offer["offer_id"],
        "product_id": offer["product_id"],
        "retailer_id": offer["retailer_id"],
        "advertised_price_minor": advertised,
        "destination": "SE",
        "shipping_scope": "item_price_only",
    }


def _resolve_parameters(parameters: dict[str, float] | None) -> dict[str, float]:
    if parameters is None:
        return dict(_DEFAULT_PARAMETERS)
    if not isinstance(parameters, dict):
        raise TypeError("parameters must be a dict or None")
    unknown = set(parameters) - set(_DEFAULT_PARAMETERS)
    if unknown:
        raise ValueError(f"unknown generation parameters: {sorted(unknown)}")
    resolved = dict(_DEFAULT_PARAMETERS)
    for name, value in parameters.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"generation parameter {name} must be numeric")
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError(f"generation parameter {name} must be between 0 and 1")
        resolved[name] = numeric
    return resolved


def generate_world(
    seed: int,
    scale: str = "small",
    parameters: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Generate a deterministic world without conditioning on task feasibility."""

    seed = _require_int(seed, "seed")
    if scale not in _SCALE_COUNTS:
        raise ValueError(f"scale must be one of {sorted(_SCALE_COUNTS)}")
    resolved_parameters = _resolve_parameters(parameters)

    products = [_product(seed, index) for index in range(_SCALE_COUNTS[scale])]
    retailers = _retailers()
    residuals = {
        retailer["retailer_id"]: _retailer_residual(seed, retailer["retailer_id"])
        for retailer in retailers
    }
    offers = [
        _offer(
            seed,
            product,
            retailer,
            residuals[retailer["retailer_id"]],
            resolved_parameters,
        )
        for product in products
        for retailer in retailers
    ]
    claims = [_claim(seed, offer, resolved_parameters) for offer in offers]
    product_provenance = {}
    for index, product in enumerate(products):
        category = _CATEGORIES[index % len(_CATEGORIES)]
        product_provenance[product["product_id"]] = {
            "stream_namespace": f"product/{index:03d}",
            "reference_price_range_minor": list(category["price_range"]),
            "sampled_reference_price_minor": product["reference_price_minor"],
        }
    offer_provenance = {}
    for offer in offers:
        retailer_id = offer["retailer_id"]
        reference_price = next(
            product["reference_price_minor"]
            for product in products
            if product["product_id"] == offer["product_id"]
        )
        implied_total_basis_points = offer["price_minor"] * 10_000 // reference_price
        offer_provenance[offer["offer_id"]] = {
            "stream_namespace_root": f"offer/{offer['product_id']}/{retailer_id}",
            "component_streams": {
                component: f"offer/{offer['product_id']}/{retailer_id}/{component}"
                for component in ("pricing", "inventory", "fulfillment", "extras")
            },
            "mechanisms": {
                "price": "reference_price_times_retailer_residual_plus_offer_noise",
                "stock": "bernoulli_stockout_else_uniform_integer_1_to_5",
                "dispatch": "uniform_integer_0_to_4",
                "extra_availability": "bernoulli_0_72",
                "extra_preselection": "bernoulli_parameter_if_extra_available",
            },
            "retailer_price_residual_basis_points": residuals[retailer_id],
            "sampled_offer_noise_basis_points": _rng(
                seed, f"offer/{offer['product_id']}/{retailer_id}/pricing"
            ).randint(-900, 900),
            "realized_price_ratio_basis_points": implied_total_basis_points,
            "sampled_stock_quantity": offer["stock_quantity"],
            "sampled_stockout": offer["stock_quantity"] == 0,
            "sampled_dispatch_days": offer["dispatch_days"],
            "sampled_extra_available": offer["extra_price_minor"] is not None,
            "sampled_extra_preselected": offer["extra_preselected"],
        }
    claim_provenance = {
        claim["claim_id"]: {
            "stream_namespace": f"claim/{claim['offer_id']}",
            "mechanism": "bernoulli_staleness_then_signed_price_adjustment",
            "sampled_stale": claim["advertised_price_minor"]
            != next(
                offer["price_minor"]
                for offer in offers
                if offer["offer_id"] == claim["offer_id"]
            ),
            "sampled_adjustment_minor": claim["advertised_price_minor"]
            - next(
                offer["price_minor"]
                for offer in offers
                if offer["offer_id"] == claim["offer_id"]
            ),
        }
        for claim in claims
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "scale": scale,
        "scenario_date": SCENARIO_DATE,
        "currency": CURRENCY,
        "products": products,
        "retailers": retailers,
        "offers": offers,
        "aggregator_claims": claims,
        "private_provenance": {
            "provenance_schema_version": "procedural-commerce-provenance-v1",
            "generator_version": GENERATOR_VERSION,
            "rng": {
                "algorithm": "python_random_mt19937",
                "seed_derivation": "sha256(generator_version, seed, namespace)",
                "independent_streams": True,
            },
            "resolved_parameters": resolved_parameters,
            "retailer_price_residual_basis_points": residuals,
            "products": product_provenance,
            "offers": offer_provenance,
            "claims": claim_provenance,
        },
    }


def generate_task(
    world: dict[str, Any], task_seed: int, mode: str = "compare"
) -> dict[str, Any]:
    """Sample a task from identity/reference data, never from quotes or feasibility."""

    task_seed = _require_int(task_seed, "task_seed")
    if mode not in {"compare", "prepare", "purchase"}:
        raise ValueError("mode must be compare, prepare, or purchase")
    products = world.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError("world must contain at least one product")
    rng = _rng(task_seed, f"task/{mode}")
    product = products[rng.randrange(len(products))]
    product_id = product["product_id"]
    reference_price = product["reference_price_minor"]
    if isinstance(reference_price, bool) or not isinstance(reference_price, int):
        raise ValueError("product reference_price_minor must be an integer")
    budget_basis_points = rng.randint(8_500, 13_500)
    budget_minor = _rounded_hundreds(reference_price * budget_basis_points // 10_000)
    arrival_days_max = rng.randint(2, 7)
    require_extra = rng.random() < 0.28
    action = {
        "compare": "Report the cheapest eligible offer without placing an order.",
        "prepare": "Prepare one eligible cart without placing an order.",
        "purchase": "Place exactly one order for the cheapest eligible offer.",
    }[mode]
    extra_text = "Include the care package." if require_extra else "Do not add a care package."
    no_match_action = (
        "If no offer meets every condition, explicitly report no match and place no order."
    )
    goal = (
        f"On {world.get('scenario_date', SCENARIO_DATE)}, find quantity 1 of "
        f"{product['name']} for delivery to Sweden (SE). {action} Consider all "
        f"participating retailers. The complete total, including delivery and any selected "
        f"extra, must be at most {budget_minor / 100:.2f} SEK. Arrival must be within "
        f"{arrival_days_max} calendar days after the scenario date. {extra_text} "
        f"Do not buy any other product or subscription. {no_match_action}"
    )
    return {
        "schema_version": TASK_SCHEMA_VERSION,
        "task_seed": task_seed,
        "mode": mode,
        "goal": goal,
        "constraints": {
            "product_id": product_id,
            "quantity": 1,
            "budget_minor": budget_minor,
            "destination": "SE",
            "arrival_days_max": arrival_days_max,
            "require_extra": require_extra,
        },
    }


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def world_sha256(world: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(world).encode("utf-8")).hexdigest()


def export_world(
    world: dict[str, Any], output_path: str | os.PathLike[str]
) -> Path:
    """Write canonical JSON once; never overwrite an existing export."""

    path = Path(output_path)
    with path.open("x", encoding="utf-8") as output:
        output.write(canonical_json(world))
        output.write("\n")
    return path


def aggregator_view(world: dict[str, Any]) -> dict[str, Any]:
    """Return public aggregator data with no correctness/error annotations."""

    retailers = [
        {
            "retailer_id": retailer["retailer_id"],
            "name": retailer["name"],
            "operating_profile": retailer["operating_profile"],
            "policy_summary": retailer["policy_summary"],
        }
        for retailer in world["retailers"]
    ]
    return copy.deepcopy(
        {
            "schema_version": world["schema_version"],
            "scenario_date": world["scenario_date"],
            "currency": world["currency"],
            "products": [
                {key: value for key, value in product.items() if key != "reference_price_minor"}
                for product in world["products"]
            ],
            "retailers": retailers,
            "aggregator_claims": world["aggregator_claims"],
        }
    )


def retailer_view(world: dict[str, Any], retailer_id: str) -> dict[str, Any]:
    """Return one retailer's public catalog and current initial-world offer facts."""

    if not isinstance(retailer_id, str):
        raise TypeError("retailer_id must be a string")
    retailers = [item for item in world["retailers"] if item["retailer_id"] == retailer_id]
    if not retailers:
        raise KeyError(retailer_id)
    public_retailer = {
        key: value for key, value in retailers[0].items() if key != "renderer_key"
    }
    return copy.deepcopy(
        {
            "schema_version": world["schema_version"],
            "scenario_date": world["scenario_date"],
            "currency": world["currency"],
            "products": [
                {key: value for key, value in product.items() if key != "reference_price_minor"}
                for product in world["products"]
            ],
            "retailer": public_retailer,
            "offers": [
                offer for offer in world["offers"] if offer["retailer_id"] == retailer_id
            ],
        }
    )


__all__ = [
    "CURRENCY",
    "GENERATOR_VERSION",
    "SCENARIO_DATE",
    "SCHEMA_VERSION",
    "TASK_SCHEMA_VERSION",
    "aggregator_view",
    "canonical_json",
    "export_world",
    "generate_task",
    "generate_world",
    "retailer_view",
    "world_sha256",
]
