// All API calls to the Django backend
// Vite proxies /api → http://localhost:8000

const BASE = '/api'

// ── Auth helpers ──────────────────────────────────────────────────────────

export function getAccessToken() {
    return localStorage.getItem('access_token')
}

export function setTokens(access, refresh) {
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
}

export function clearTokens() {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
}

function authHeaders() {
    const token = getAccessToken()
    return {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
    }
}

async function apiFetch(url, options = {}) {
    const r = await fetch(url, {
        ...options,
        headers: { ...authHeaders(), ...(options.headers || {}) },
    })
    if (r.status === 401) {
        clearTokens()
        window.location.href = '/login'
        return
    }
    if (!r.ok) throw new Error(await r.text())
    return r.json()
}

// ── Auth endpoints ────────────────────────────────────────────────────────

export async function login(username, password) {
    const r = await fetch(`${BASE}/auth/login/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
    })
    if (!r.ok) throw new Error(await r.text())
    const data = await r.json()
    setTokens(data.access, data.refresh)
    return data
}

export async function register(username, password, email = '') {
    const r = await fetch(`${BASE}/auth/register/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, email }),
    })
    if (!r.ok) throw new Error(await r.text())
    const data = await r.json()
    setTokens(data.access, data.refresh)
    return data
}

export async function logout(refreshToken) {
    await fetch(`${BASE}/auth/logout/`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ refresh: refreshToken }),
    })
    clearTokens()
}

export async function getMe() {
    return apiFetch(`${BASE}/auth/me/`)
}

// ── Stores ────────────────────────────────────────────────────────────────

export async function getStores() {
    return apiFetch(`${BASE}/stores/`)
}

export async function addStore(domain, clientId, clientSecret) {
    return apiFetch(`${BASE}/stores/`, {
        method: 'POST',
        body: JSON.stringify({ domain, client_id: clientId, client_secret: clientSecret }),
    })
}

// ── Fetch (bulk export) ───────────────────────────────────────────────────

export async function triggerFetch(store) {
    return apiFetch(`${BASE}/stores/${store}/fetch/`, { method: 'POST' })
}

// ── Products ──────────────────────────────────────────────────────────────

export async function getProducts(store) {
    return apiFetch(`${BASE}/stores/${store}/products/`)
}

export async function getLocations(store) {
    return apiFetch(`${BASE}/stores/${store}/locations/`)
}

export async function getCollectionHandles(store) {
    return apiFetch(`${BASE}/stores/${store}/collection-handles/`)
}

export async function getMetafieldDefs(store) {
    return apiFetch(`${BASE}/stores/${store}/metafield-defs/`)
}

export async function getMetafieldOwners(store) {
    return apiFetch(`${BASE}/stores/${store}/metafield-owners/`)
}

export async function getFieldSchema(store) {
    return apiFetch(`${BASE}/stores/${store}/field-schema/`)
}

// ── Sync ──────────────────────────────────────────────────────────────────

export async function startSync(store) {
    return apiFetch(`${BASE}/stores/${store}/sync/`, { method: 'POST' })
}

export async function syncProduct(store, productId, productRow, variantRows) {
    const encoded = encodeURIComponent(productId)
    return apiFetch(`${BASE}/stores/${store}/sync/product/${encoded}/`, {
        method: 'POST',
        body: JSON.stringify({ productRow, variantRows }),
    })
}

// ── Snapshots ─────────────────────────────────────────────────────────────

export async function getSnapshots(store) {
    return apiFetch(`${BASE}/stores/${store}/snapshots/`)
}

export async function rollbackPreview(store, timestamp) {
    return apiFetch(`${BASE}/stores/${store}/snapshots/${timestamp}/rollback/`, { method: 'POST' })
}

export async function saveProducts(storeName, rows) {
    return apiFetch(`${BASE}/stores/${storeName}/save/`, {
        method: 'POST',
        body: JSON.stringify({ rows }),
    })
}

export async function getSyncLogs(store) {
    return apiFetch(`${BASE}/stores/${store}/sync/logs/`)
}

export async function deleteStore(storeName) {
    return apiFetch(`${BASE}/stores/${storeName}/`, { method: 'DELETE' })
}

export async function clearStoreData(storeName) {
    return apiFetch(`${BASE}/stores/${storeName}/clear-data/`, { method: 'POST' })
}

// ── Blogs ─────────────────────────────────────────────────────────────────

export async function fetchArticles(store) {
    return apiFetch(`${BASE}/stores/${store}/blogs/fetch/`, { method: 'POST' })
}

export async function getArticles(store) {
    return apiFetch(`${BASE}/stores/${store}/blogs/`)
}

export async function saveArticles(store, rows) {
    return apiFetch(`${BASE}/stores/${store}/blogs/save/`, {
        method: 'POST',
        body: JSON.stringify({ rows }),
    })
}

export async function syncArticles(store) {
    return apiFetch(`${BASE}/stores/${store}/blogs/sync/`, { method: 'POST' })
}

export async function getBlogList(store) {
    return apiFetch(`${BASE}/stores/${store}/blog-list/`)
}

export async function getBlogMetafieldDefs(store) {
    return apiFetch(`${BASE}/stores/${store}/blog-metafield-defs/`)
}

export async function refreshBlogMetafieldDefs(store) {
    return apiFetch(`${BASE}/stores/${store}/blog-metafield-defs/`, { method: 'POST' })
}

export async function createBlog(store, payload) {
    return apiFetch(`${BASE}/stores/${store}/blogs/create-blog/`, {
        method: 'POST',
        body: JSON.stringify(payload),
    })
}

export async function getArticleMetafieldDefs(store) {
    return apiFetch(`${BASE}/stores/${store}/article-metafield-defs/`)
}

export async function refreshArticleMetafieldDefs(store) {
    return apiFetch(`${BASE}/stores/${store}/article-metafield-defs/`, { method: 'POST' })
}

export async function syncArticle(store, articleId, articleRow) {
    return apiFetch(`${BASE}/stores/${store}/blogs/sync/article/`, {
        method: 'POST',
        body: JSON.stringify({ articleId, articleRow }),
    })
}

export async function getBlogDetail(store, blogId) {
    return apiFetch(`${BASE}/stores/${store}/blogs/detail/?blog_id=${encodeURIComponent(blogId)}`)
}

export async function updateBlog(store, blogId, payload) {
    return apiFetch(`${BASE}/stores/${store}/blogs/detail/`, {
        method: 'POST',
        body: JSON.stringify({ blog_id: blogId, ...payload }),
    })
}


export async function deleteBlog(store, blogId) {
    return apiFetch(`${BASE}/stores/${store}/blogs/delete/`, {
        method: 'POST',
        body: JSON.stringify({ blog_id: blogId }),
    })
}

export async function fetchBlogList(store) {
    return apiFetch(`${BASE}/stores/${store}/blogs/fetch-blog-list/`, { method: 'POST' })
}