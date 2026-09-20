/* Hemteknik storefront: all prices, offers and cart state are supplied by the retailer API. */
(function () {
  "use strict";
  const state = { offers: [], categories: [], category: "", query: "", sort: "recommended", cart: null, store: null };
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const sek = (ore) => `${(Number(ore || 0) / 100).toLocaleString("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} kr`;
  const offerProductId = (offer) => offer.product_id || offer.id || "";
  const image = (offer, cls = "") => offer.image ? `<img class="${cls}" src="${esc(offer.image)}" alt="${esc(offer.name)}">` : `<div class="product-placeholder ${cls}" aria-hidden="true">${esc((offer.brand || offer.name || "H").slice(0, 2))}</div>`;
  const api = async (path, options = {}) => {
    const response = await fetch(path, { credentials: "same-origin", headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
    let body = {};
    try { body = await response.json(); } catch (_) { body = {}; }
    if (!response.ok) throw new Error(body.message || "Något gick fel. Försök igen.");
    return body;
  };
  const announce = (message) => { const toast = $("#toast"); toast.textContent = message; toast.classList.add("show"); window.clearTimeout(announce.timer); announce.timer = window.setTimeout(() => toast.classList.remove("show"), 2800); };
  const stockLabel = (stock) => stock === "in_stock" ? "I lager" : stock === "low_stock" ? "Få kvar" : "Tillfälligt slut";
  const stockClass = (stock) => stock === "in_stock" ? "ok" : "low";
  function renderCategories() {
    $("#category-list").innerHTML = state.categories.map((cat) => `<button class="category-link" type="button" data-category="${esc(cat)}">${esc(cat)} <span>›</span></button>`).join("");
    $$(".category-link").forEach((button) => button.addEventListener("click", () => { state.category = button.dataset.category; $$(".category-link").forEach((b) => b.classList.toggle("active", b === button)); loadCatalog(); }));
  }
  function sortedOffers(offers) {
    const copy = offers.slice();
    if (state.sort === "price-low") copy.sort((a, b) => a.unit_price_ore - b.unit_price_ore);
    if (state.sort === "price-high") copy.sort((a, b) => b.unit_price_ore - a.unit_price_ore);
    if (state.sort === "name") copy.sort((a, b) => a.name.localeCompare(b.name, "sv"));
    return copy;
  }
  function renderProducts() {
    const offers = sortedOffers(state.offers);
    $("#result-count").textContent = `${offers.length} ${offers.length === 1 ? "produkt" : "produkter"}`;
    $("#result-context").textContent = state.query ? `för “${state.query}”` : state.category ? `i ${state.category}` : "";
    $("#crumb-current").textContent = state.category || "Alla produkter";
    $("#catalog-title").textContent = state.category ? state.category : state.query ? `Sökresultat för “${state.query}”` : "Teknik som gör vardagen enklare";
    $("#product-grid").innerHTML = offers.length ? offers.map(card).join("") : `<div class="status">Vi hittade inga produkter. Prova ett annat sökord.</div>`;
    offers.forEach((offer) => { const cardEl = document.querySelector(`[data-offer-card="${CSS.escape(offer.offer_id)}"]`); if (!cardEl) return; $("[data-detail]", cardEl).addEventListener("click", () => showDetail(offer)); $("[data-add]", cardEl).addEventListener("click", () => addToCart(offer.offer_id)); });
  }
  function card(offer) {
    const badge = offer.stock === "low_stock" ? `<span class="badge">Få kvar</span>` : offer.delivery?.startsWith("1") ? `<span class="badge">Snabb leverans</span>` : "";
    return `<article class="product-card" data-offer-card="${esc(offer.offer_id)}"><div class="product-media">${badge}${image(offer)}</div><div class="product-body"><span class="product-brand">${esc(offer.brand)}</span><h2 class="product-name">${esc(offer.name)}</h2><div class="product-meta">${esc(offer.variant || "")} · ${esc(offer.capacity || "")}</div><p class="product-desc">${esc(offer.description || "Kvalitetsteknik för hemmet.")}</p><div class="product-bottom"><div class="price">${sek(offer.unit_price_ore)}<small>+ ${sek(offer.shipping_ore)} frakt</small></div><button type="button" class="card-button" data-detail>Visa detaljer</button></div><div class="stock ${stockClass(offer.stock)}">● ${stockLabel(offer.stock)} · ${esc(offer.delivery || "Leveransinformation saknas")}</div><button type="button" class="card-button primary" data-add style="margin-top:11px;width:100%">Lägg i varukorg</button></div></article>`;
  }
  async function loadCatalog() {
    $("#status").textContent = "Laddar sortiment…";
    try { const params = new URLSearchParams(); if (state.query) params.set("q", state.query); if (state.category) params.set("category", state.category); const data = await api(`/api/catalog?${params}`); state.offers = data.offers || []; if (data.categories) { state.categories = data.categories; renderCategories(); } renderProducts(); $("#status").textContent = ""; } catch (error) { $("#status").textContent = error.message; }
  }
  async function refreshCart() { try { state.cart = await api("/api/cart"); renderCart(); } catch (error) { $("#cart-content").innerHTML = `<p class="error">${esc(error.message)}</p>`; } }
  function renderCart() {
    const cart = state.cart || { items: [], extras: [] }; const count = cart.items.reduce((sum, item) => sum + item.quantity, 0); $("#cart-count").textContent = count; $("#drawer-count").textContent = `(${count})`;
    if (!cart.items.length) { $("#cart-content").innerHTML = `<div class="cart-empty"><strong>Varukorgen är tom</strong><p>Hitta något du gillar och lägg det här.</p><button type="button" class="card-button primary" id="continue-shopping">Fortsätt handla</button></div>`; $("#continue-shopping").addEventListener("click", closeCart); return; }
    const warrantyByOffer = new Map((cart.extras || []).map((extra) => [extra.offer_id, extra]));
    const lines = cart.items.map((item) => { const offer = state.offers.find((row) => row.offer_id === item.offer_id); const selected = warrantyByOffer.get(item.offer_id); const choices = offer?.warranties?.length ? `<div class="warranty-box"><label for="warranty-${esc(item.offer_id)}">Extra trygghet</label><select id="warranty-${esc(item.offer_id)}" data-warranty-offer="${esc(item.offer_id)}"><option value="">Ingen extra trygghet</option>${offer.warranties.map((w) => `<option value="${esc(w.id)}" ${selected?.id === w.id ? "selected" : ""}>${esc(w.name)} · ${sek(w.price_ore)}</option>`).join("")}</select></div>` : ""; return `<div class="cart-line" data-line="${esc(item.line_id)}"><div class="line-image" aria-hidden="true">${esc((item.name || "H").slice(0, 2))}</div><div><div class="line-name">${esc(item.name)}</div><div class="line-meta">${esc(item.variant || "")} · ${esc(item.capacity || "")}</div><div class="qty-controls"><button type="button" data-qty="-1" aria-label="Minska antal">−</button><input aria-label="Antal ${esc(item.name)}" type="number" min="0" value="${item.quantity}" data-quantity><button type="button" data-qty="1" aria-label="Öka antal">+</button></div><button class="remove-link" type="button" data-remove>Ta bort</button>${choices}</div><div class="line-price">${sek(item.unit_price_ore * item.quantity)}</div></div>`; }).join("");
    $("#cart-content").innerHTML = `${lines}<div class="summary"><div class="summary-row"><span>Varor</span><strong>${sek(cart.subtotal_ore)}</strong></div><div class="summary-row"><span>Frakt</span><strong>${sek(cart.shipping_ore)}</strong></div>${cart.extras_ore ? `<div class="summary-row"><span>Tillägg</span><strong>${sek(cart.extras_ore)}</strong></div>` : ""}<div class="summary-row total"><span>Totalt</span><strong>${sek(cart.delivered_ore)}</strong></div><small>Inklusive moms</small><button type="button" class="primary-button wide" id="checkout-button">Gå till kassan</button></div>`;
    $$("[data-line]").forEach((line) => { const id = line.dataset.line; $$("[data-qty]", line).forEach((button) => button.addEventListener("click", () => updateQuantity(id, Number($("[data-quantity]", line).value) + Number(button.dataset.qty)))); $("[data-quantity]", line).addEventListener("change", (event) => updateQuantity(id, Number(event.target.value))); $("[data-remove]", line).addEventListener("click", () => updateQuantity(id, 0)); });
    $$(`[data-warranty-offer]`).forEach((select) => select.addEventListener("change", () => setWarranty(select.dataset.warrantyOffer, select.value || null)));
    $("#checkout-button").addEventListener("click", openCheckout);
  }
  async function addToCart(offerId) { try { await api("/api/cart/items", { method: "POST", body: JSON.stringify({ offer_id: offerId, quantity: 1 }) }).then((cart) => { state.cart = cart; renderCart(); }); announce("Produkten har lagts i varukorgen"); openCart(); } catch (error) { announce(error.message); } }
  async function updateQuantity(lineId, quantity) { try { state.cart = await api(`/api/cart/items/${encodeURIComponent(lineId)}`, { method: "PATCH", body: JSON.stringify({ quantity: Math.max(0, quantity) }) }); renderCart(); } catch (error) { announce(error.message); } }
  async function setWarranty(offerId, warrantyId) { try { state.cart = await api("/api/cart/warranty", { method: "PUT", body: JSON.stringify({ offer_id: offerId, warranty_id: warrantyId }) }); renderCart(); announce(warrantyId ? "Tryggheten är tillagd" : "Tryggheten är borttagen"); } catch (error) { announce(error.message); } }
  function showDetail(offer) { const warrantyOptions = offer.warranties?.length ? `<h3>Extra trygghet</h3><select id="detail-warranty" aria-label="Välj extra trygghet"><option value="">Ingen extra trygghet</option>${offer.warranties.map((w) => `<option value="${esc(w.id)}">${esc(w.name)} · ${sek(w.price_ore)}</option>`).join("")}</select>` : ""; $("#detail-content").innerHTML = `<div class="detail-layout"><div class="detail-visual">${image(offer)}</div><div><span class="product-brand">${esc(offer.brand)}</span><h2 id="detail-title">${esc(offer.name)}</h2><p class="product-meta">${esc(offer.model)} · ${esc(offer.variant)} · ${esc(offer.capacity)}</p><p>${esc(offer.description || "")}</p><dl class="detail-facts"><div><dt>Lagerstatus</dt><dd class="${stockClass(offer.stock)}">${stockLabel(offer.stock)}</dd></div><div><dt>Leverans</dt><dd>${esc(offer.delivery)}</dd></div><div><dt>Pris</dt><dd>${sek(offer.unit_price_ore)}</dd></div><div><dt>Frakt</dt><dd>${sek(offer.shipping_ore)}</dd></div></dl>${warrantyOptions}<div class="detail-buy"><div class="price">${sek(offer.unit_price_ore)}<small>exkl. eventuellt tillägg</small></div><button type="button" class="primary-button" id="detail-add">Lägg i varukorg</button></div></div></div>`; $("#detail-modal").hidden = false; $("#detail-add").addEventListener("click", async () => { await addToCart(offer.offer_id); const warranty = $("#detail-warranty")?.value; if (warranty) await setWarranty(offer.offer_id, warranty); closeModal("detail-modal"); }); }
  function openCart() { $("#cart-drawer").classList.add("open"); $("#cart-drawer").setAttribute("aria-hidden", "false"); $("#cart-toggle").setAttribute("aria-expanded", "true"); }
  function closeCart() { $("#cart-drawer").classList.remove("open"); $("#cart-drawer").setAttribute("aria-hidden", "true"); $("#cart-toggle").setAttribute("aria-expanded", "false"); }
  function closeModal(id) { $("#" + id).hidden = true; }
  function openCheckout() { if (!state.cart?.items?.length) return; const cart = state.cart; $("#checkout-summary").innerHTML = `<div class="summary-row"><span>Att betala</span><strong>${sek(cart.delivered_ore)}</strong></div><small>Varor ${sek(cart.subtotal_ore)} · Frakt ${sek(cart.shipping_ore)}${cart.extras_ore ? ` · Tillägg ${sek(cart.extras_ore)}` : ""}</small>`; $("#checkout-error").textContent = ""; $("#checkout-modal").hidden = false; }
  async function loadOrders() { const section = $("#orders"); section.hidden = false; try { const data = await api("/api/orders"); const orders = data.orders || []; $("#orders-list").innerHTML = orders.length ? orders.map((order) => `<div class="order-card"><strong>Order ${esc(order.order_id || order.id || "")} · ${sek(order.delivered_ore || order.total_ore)}</strong><p>${esc(order.created_at || "Simulerad beställning")} · ${order.items?.length || 0} artikel${order.items?.length === 1 ? "" : "ar"}</p></div>`).join("") : `<p class="muted">Du har inga tidigare köp.</p>`; } catch (error) { $("#orders-list").innerHTML = `<p class="error">${esc(error.message)}</p>`; } section.scrollIntoView({ behavior: "smooth" }); }
  $("#search-form").addEventListener("submit", (event) => { event.preventDefault(); state.query = $("#search-input").value.trim(); state.category = ""; $$(".category-link").forEach((b) => b.classList.toggle("active", b.dataset.category === "")); loadCatalog(); });
  $("#sort-select").addEventListener("change", (event) => { state.sort = event.target.value; renderProducts(); });
  $("#cart-toggle").addEventListener("click", openCart); $("#cart-close").addEventListener("click", closeCart); $("#orders-link").addEventListener("click", (event) => { event.preventDefault(); loadOrders(); }); $("#close-orders").addEventListener("click", () => { $("#orders").hidden = true; }); $("#menu-toggle").addEventListener("click", () => { const rail = $("#category-rail"); const button = $("#menu-toggle"); const shown = rail.style.display !== "block"; rail.style.display = shown ? "block" : "none"; button.setAttribute("aria-expanded", String(shown)); }); $$("[data-close]").forEach((button) => button.addEventListener("click", () => closeModal(button.dataset.close)));
  $("#checkout-form").addEventListener("submit", async (event) => { event.preventDefault(); const form = new FormData(event.target); $("#checkout-error").textContent = ""; try { const receipt = await api("/api/checkout", { method: "POST", body: JSON.stringify({ customer: Object.fromEntries(form.entries()) }) }); closeModal("checkout-modal"); closeCart(); event.target.reset(); await refreshCart(); announce(`Tack! Order ${receipt.order_id || receipt.id || ""} är registrerad.`); } catch (error) { $("#checkout-error").textContent = error.message; } });
  const initialProduct = new URLSearchParams(window.location.search).get("product_id");
  Promise.all([api("/api/store").then((store) => { state.store = store; document.title = `${store.name || "Hemteknik"} — ${store.tagline || "Elektronik för hela hemmet"}`; }), loadCatalog().then(() => { if (initialProduct) { const offer = state.offers.find((row) => offerProductId(row) === initialProduct); if (offer) showDetail(offer); } }), refreshCart()]).catch(() => {});
}());
