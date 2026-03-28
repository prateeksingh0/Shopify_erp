import { useState, useMemo } from 'react'
import ProductPanel from './ProductPanel'
import styles from './ShopifyView.module.css'
import { getProducts } from '../api'

const PRODUCT_LEVEL_KEYS = new Set([
    'Product ID', 'Title', 'Body (HTML)', 'Vendor', 'Type',
    'Tags', 'Status', 'Handle', 'SEO Title', 'SEO Description',
    'Image URLs', 'Image Alt Text', 'Collection Handles',
    'Created At', 'Updated At', 'Published At', 'Gift Card',
    'Product Category ID', 'Product Category Name', 'Product Category Full Path',
    'Collection Names',
])

function groupRows(rows) {
    const map = new Map()
    const order = []
    for (const row of rows) {
        const pid = row['Product ID'] || row['Handle'] || '__unknown__'
        if (!map.has(pid)) {
            map.set(pid, { productRow: row, variantRows: [] })
            order.push(pid)
        }
        map.get(pid).variantRows.push(row)
    }
    return order.map(pid => map.get(pid))
}

function firstImageUrl(row) {
    const raw = String(row?.['Image URLs'] || '')
    return raw.split(',').map(u => u.trim()).find(u => u.startsWith('http')) || ''
}

function priceRange(variantRows) {
    const prices = variantRows.map(r => parseFloat(r['Variant Price'])).filter(p => !isNaN(p))
    if (!prices.length) return '—'
    const min = Math.min(...prices), max = Math.max(...prices)
    return min === max ? `$${min.toFixed(2)}` : `$${min.toFixed(2)} – $${max.toFixed(2)}`
}

function totalInventory(variantRows) {
    return variantRows.reduce((sum, r) => {
        // Sum all 'Inventory Qty - {location}' columns
        const locationQty = Object.entries(r)
            .filter(([k]) => k.startsWith('Inventory Qty -'))
            .reduce((s, [, v]) => {
                const n = parseInt(v, 10)
                return s + (isNaN(n) ? 0 : n)
            }, 0)
        return sum + locationQty
    }, 0)
}

const STATUS_DOT = { active: '#10b981', draft: '#f59e0b', archived: '#94a3b8' }

export default function ShopifyView({
    rows, setRows, selectedStore, isSyncing, setIsSyncing,
    fieldSchema, storeCollectionHandles, metafieldDefs, metafieldOwners, onReload,
}) {
    const [search, setSearch] = useState('')
    const [openProduct, setOpenProduct] = useState(null)

    function handleAddProduct() {
        if (!rows.length) return
        const blank = Object.fromEntries(Object.keys(rows[0]).map(k => [k, '']))
        const newProduct = {
            productRow: blank,
            variantRows: [{ ...blank }]
        }
        setOpenProduct(newProduct)
    }

    const products = useMemo(() => groupRows(rows), [rows])

    const filtered = useMemo(() => {
        if (!search.trim()) return products
        const q = search.toLowerCase()
        return products.filter(({ productRow, variantRows }) => {
            const title = String(productRow['Title'] || '').toLowerCase()
            const vendor = String(productRow['Vendor'] || '').toLowerCase()
            const type = String(productRow['Type'] || '').toLowerCase()
            const tags = String(productRow['Tags'] || '').toLowerCase()
            const skus = variantRows.map(r => String(r['Variant SKU'] || '').toLowerCase()).join(' ')
            return title.includes(q) || vendor.includes(q) || type.includes(q) || tags.includes(q) || skus.includes(q)
        })
    }, [products, search])

    function handlePanelSave(updated) {
        setRows(prev => {
            const pid = updated.productRow['Product ID'] || updated.productRow['Handle']

            // New product — no matching rows yet, append all variant rows
            const hasMatch = prev.some(r =>
                (r['Product ID'] || r['Handle']) === pid
            )
            if (!hasMatch || !pid) {
                const newRows = updated.variantRows.map(vr => ({
                    ...updated.productRow,
                    ...vr,
                }))
                return [...prev, ...newRows]
            }

            // Existing product — merge in place
            const next = [...prev]
            let variantIdx = 0
            for (let i = 0; i < next.length; i++) {
                const rowPid = next[i]['Product ID'] || next[i]['Handle']
                if (rowPid !== pid) continue
                const merged = { ...next[i] }
                for (const k of Object.keys(merged)) {
                    if (PRODUCT_LEVEL_KEYS.has(k)) merged[k] = updated.productRow[k] ?? merged[k]
                }
                if (updated.variantRows[variantIdx]) {
                    const vr = updated.variantRows[variantIdx]
                    for (const k of Object.keys(merged)) {
                        if (!PRODUCT_LEVEL_KEYS.has(k)) merged[k] = vr[k] ?? merged[k]
                    }
                }
                next[i] = merged
                variantIdx++
            }
            return next
        })
        setOpenProduct(updated)
    }

    if (!selectedStore) return (
        <div className={styles.empty}>
            <div className={styles.emptyIcon}>⬡</div>
            <div className={styles.emptyTitle}>No store selected</div>
        </div>
    )

    if (!rows.length) return (
        <div className={styles.empty}>
            <div className={styles.emptyIcon}>↓</div>
            <div className={styles.emptyTitle}>No data loaded</div>
            <div className={styles.emptySubtitle}>Click FETCH to pull products</div>
        </div>
    )

    return (
        <div className={styles.root}>
            <div className={styles.toolbar}>
                <input
                    className={styles.search}
                    placeholder="Search title, vendor, SKU, tags…"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                />
                <button
                    className={styles.addBtn}
                    onClick={handleAddProduct}
                    disabled={!rows.length || isSyncing}
                >
                    + New Product
                </button>
                <span className={styles.count}>{filtered.length} products</span>
            </div>
            

            <div className={styles.grid}>
                {filtered.map(({ productRow, variantRows }) => {
                    const pid = productRow['Product ID'] || productRow['Handle'] || '__unknown__'
                    const imgUrl = firstImageUrl(productRow)
                    const status = String(productRow['Status'] || '').toLowerCase()
                    const dotColor = STATUS_DOT[status] || '#94a3b8'
                    const inv = totalInventory(variantRows)
                    return (
                        <div key={pid} className={styles.card}
                            onClick={() => setOpenProduct({ productRow, variantRows })}>
                            <div className={styles.cardImg}
                                style={imgUrl ? { backgroundImage: `url(${imgUrl})` } : {}}>
                                {!imgUrl && <span className={styles.noImg}>No image</span>}
                            </div>
                            <div className={styles.cardBody}>
                                <div className={styles.cardStatus}>
                                    <span className={styles.statusDot} style={{ background: dotColor }} />
                                    <span className={styles.statusLabel}>{status || '—'}</span>
                                </div>
                                <div className={styles.cardTitle}>{productRow['Title'] || '—'}</div>
                                {productRow['Vendor'] && <div className={styles.cardVendor}>{productRow['Vendor']}</div>}
                                <div className={styles.cardMeta}>
                                    <span>{priceRange(variantRows)}</span>
                                    <span className={inv > 0 ? styles.inStock : styles.outStock}>{inv} in stock</span>
                                </div>
                                <div className={styles.cardVariants}>
                                    {variantRows.length} variant{variantRows.length !== 1 ? 's' : ''}
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>

            {openProduct && (
                <ProductPanel
                    product={openProduct}
                    allKeys={rows.length ? Object.keys(rows[0]) : []}
                    productLevelKeys={PRODUCT_LEVEL_KEYS}
                    onClose={async () => {
                        setOpenProduct(null)
                        // Reload if it was a new product (no Product ID)
                        if (!openProduct.productRow['Product ID'] && onReload) {
                            try {
                                const fresh = await getProducts(selectedStore.store_name)
                                if (fresh.length) onReload(fresh)
                            } catch (e) {
                                console.error('Reload failed', e)
                            }
                        }
                    }}
                    onSave={handlePanelSave}
                    selectedStore={selectedStore}
                    isSyncing={isSyncing}
                    setIsSyncing={setIsSyncing}
                    fieldSchema={fieldSchema}
                    storeCollectionHandles={storeCollectionHandles}
                    metafieldDefs={metafieldDefs}
                    metafieldOwners={metafieldOwners}
                    allRows={rows}
                />
            )}
        </div>
    )
}