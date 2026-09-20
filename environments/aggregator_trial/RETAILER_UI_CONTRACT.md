# AGG-TRIAL-01 retailer UI contract (frozen v1)

Status: frozen for the two independent retailer UI implementations. The shared
Python engine owns all state and API behavior. Retailer UI workers own only the
files listed below and must not add server, grader, catalog, or task logic.

## File ownership

| Retailer | Worker-owned files | Layout requirement |
| --- | --- | --- |
| `hemteknik` | `retailers/hemteknik/index.html`, `styles.css`, `app.js` | Department-store layout: left category rail, dense product grid, cart drawer |
| `signalboden` | `retailers/signalboden/index.html`, `styles.css`, `app.js` | Specialist-shop layout: top category tabs, list/detail pages, separate cart page |

The shared owner controls every other path, including `retailers/nordbyte/`, and
may review worker files only for API compatibility and accessibility. Each UI is
served at its own injected localhost origin. Use only relative URLs and local
assets. No CDN, external fetch, copied branding, hidden answer data, or grader API.

## HTTP API

All bodies are JSON. Prices are integer ore; display them as SEK with two decimal
places. `delivered_ore = unit_price_ore * quantity + shipping_ore + extras_ore`.
The server issues an HttpOnly session cookie and derives retailer identity from
the listening origin. UI code never sends a session or retailer ID explicitly.

### Read endpoints

`GET /api/store`

```json
{"id":"hemteknik","name":"Hemteknik","tagline":"...","currency":"SEK","checkout_notice":"Simulated purchase — no payment is taken"}
```

`GET /api/catalog?q=&category=&product_id=` returns:

```json
{"categories":["Audio","Datorer"],"offers":[{"offer_id":"...","product_id":"...","name":"...","brand":"...","model":"...","variant":"...","capacity":"...","category":"...","description":"...","unit_price_ore":129900,"shipping_ore":4900,"stock":"in_stock","delivery":"1–2 vardagar","image":"/assets/product.svg","warranties":[{"id":"warranty-24","name":"2 års extra trygghet","price_ore":19900}]}]}
```

`GET /api/offers/{offer_id}` returns one offer with the same shape.

`GET /api/cart` returns:

```json
{"items":[{"line_id":"...","offer_id":"...","product_id":"...","name":"...","model":"...","variant":"...","capacity":"...","quantity":1,"unit_price_ore":129900}],"extras":[{"id":"warranty-24","kind":"warranty","name":"...","offer_id":"...","price_ore":19900}],"shipping_ore":4900,"subtotal_ore":129900,"extras_ore":19900,"delivered_ore":153700}
```

`GET /api/orders` returns `{"orders":[...receipts...]}`. This endpoint is for an
ordinary customer order-history page; the grader uses an in-process ledger.

### Mutation endpoints

- `POST /api/cart/items` body `{"offer_id":"...","quantity":1}`.
- `PATCH /api/cart/items/{line_id}` body `{"quantity":1}`; zero removes it.
- `DELETE /api/cart/items/{line_id}`.
- `PUT /api/cart/warranty` body `{"offer_id":"...","warranty_id":null}` or a
  warranty ID advertised on that offer. This replaces the offer's warranty.
- `POST /api/checkout` body
  `{"customer":{"name":"Testkund","email":"test@example.invalid","address":"Testgatan 1","postal_code":"12345","city":"Teststad"}}`.
  It returns `201` and an immutable receipt, and clears the cart.

Successful cart mutations return the complete cart. Errors use
`{"error":"stable_code","message":"Swedish human-readable text"}` with a 4xx
status. Checkout rejects empty carts, unavailable offers, non-positive quantities,
and missing customer fields. The server, not the UI, computes every total.

## Required public controls

Each UI must expose ordinary, accessible controls for search, product/offer detail,
model/variant/capacity, stock, delivery, item price, shipping, add to cart, quantity,
warranty selection/removal, itemized cart total, simulated checkout, and order
receipt/history. Use semantic labels and real buttons/links. A preselected warranty,
when returned by `GET /api/cart`, must be visibly selected and removable. Never
commit an order before the explicit final checkout button.

The engine serves static UI files with no build step. A worker can use plain
HTML/CSS/JavaScript and should leave all catalog values dynamic from these APIs.
