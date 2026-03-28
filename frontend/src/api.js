// All API calls to the Django backend
// Vite proxies /api → http://localhost:8000

const BASE = '/api'

// ── Stores ────────────────────────────────────────────────────────────────

export async function getStores() {
    const r = await fetch(`${BASE}/stores/`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

export async function addStore(domain, clientId, clientSecret) {
    const r = await fetch(`${BASE}/stores/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain, client_id: clientId, client_secret: clientSecret }),
    })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

// ── Fetch (bulk export) ───────────────────────────────────────────────────

export async function triggerFetch(store) {
    const r = await fetch(`${BASE}/stores/${store}/fetch/`, { method: 'POST' })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

// ── Products ──────────────────────────────────────────────────────────────

export async function getProducts(store) {
    const r = await fetch(`${BASE}/stores/${store}/products/`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

export async function getLocations(store) {
    const r = await fetch(`${BASE}/stores/${store}/locations/`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

export async function getCollectionHandles(store) {
    const r = await fetch(`${BASE}/stores/${store}/collection-handles/`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

export async function getMetafieldDefs(store) {
    const r = await fetch(`${BASE}/stores/${store}/metafield-defs/`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

export async function getMetafieldOwners(store) {
    const r = await fetch(`${BASE}/stores/${store}/metafield-owners/`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

export async function getFieldSchema(store) {
    const r = await fetch(`${BASE}/stores/${store}/field-schema/`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

// ── Sync ──────────────────────────────────────────────────────────────────

// Triggers sync by sending a message over the already-open WebSocket
export async function startSync(store) {
    const r = await fetch(`${BASE}/stores/${store}/sync/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

export async function syncProduct(store, productId, productRow, variantRows) {
    const encoded = encodeURIComponent(productId)
    const r = await fetch(`${BASE}/stores/${store}/sync/product/${encoded}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ productRow, variantRows }),
    })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

// ── Snapshots ─────────────────────────────────────────────────────────────

export async function getSnapshots(store) {
    const r = await fetch(`${BASE}/stores/${store}/snapshots/`)
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

export async function rollbackPreview(store, timestamp) {
    const r = await fetch(`${BASE}/stores/${store}/snapshots/${timestamp}/rollback/`, { method: 'POST' })
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

export async function saveProducts(storeName, rows) {
    const res = await fetch(`/api/stores/${storeName}/save/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rows })
    })
    if (!res.ok) throw new Error(`Save failed: ${res.status}`)
    return res.json()
}