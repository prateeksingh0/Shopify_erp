import { useState, useEffect, useMemo, useRef } from 'react'
import { syncProduct } from '../api'
import styles from './ProductPanel.module.css'

// ── Exact copy of ProductGrid's getCellValidationError ────────────────────────
function getCellValidationError(key, value, fieldSchema = {}, rowData = null, allowedCollectionHandles = []) {
    const v = String(value || '').trim()
    const empty = !v || v.toLowerCase() === 'nan' || v.toLowerCase() === 'none'

    if (key === 'Collection Handles' && !empty) {
        const tokens = v.split(',').map(t => t.trim().toLowerCase()).filter(Boolean)
        const invalidFormat = tokens.filter(t => !/^[a-z0-9-]+$/.test(t))
        if (invalidFormat.length)
            return `Invalid format: "${invalidFormat.join('", "')}" — handles must be lowercase letters, numbers, hyphens only`
        if (allowedCollectionHandles.length) {
            const notFound = tokens.filter(t => !allowedCollectionHandles.includes(t))
            if (notFound.length)
                return `Handle(s) not found in store: ${notFound.join(', ')}`
        }
    }

    const enumVals = fieldSchema.enums?.[key]
    if (!empty && Array.isArray(enumVals) && enumVals.length) {
        if (!enumVals.map(e => e.toUpperCase()).includes(v.toUpperCase()))
            return `Must be one of: ${enumVals.join(', ')}`
    }

    for (const [pattern, rule] of Object.entries(fieldSchema.validations || {})) {
        const matches = rule.prefix_match ? key.startsWith(pattern) : key === pattern
        if (!matches) continue
        if (rule.type === 'required') {
            if (empty) return 'This field is required'
        } else if (rule.type === 'url_list' && !empty) {
            for (const token of v.split(',').map(t => t.trim()).filter(Boolean)) {
                if (!/^https?:\/\//i.test(token))
                    return `'${token}' is not a valid URL`
            }
        } else if (rule.type === 'collection_handles' && !empty) {
            const tokens = v.split(',').map(t => t.trim().toLowerCase()).filter(Boolean)
            const invalidFormat = tokens.filter(t => !/^[a-z0-9-]+$/.test(t))
            if (invalidFormat.length)
                return `Invalid format: "${invalidFormat.join('", "')}" — handles must be lowercase, alphanumeric, hyphens only`
            if (allowedCollectionHandles.length) {
                const notFound = tokens.filter(t => !allowedCollectionHandles.includes(t))
                if (notFound.length)
                    return `Handle(s) not found in store: ${notFound.join(', ')}`
            }
        } else if (rule.type === 'paired' && !empty && rowData) {
            const partnerVal = String(rowData[rule.partner] || '').trim()
            if (!partnerVal || partnerVal.toLowerCase() === 'nan')
                return `Requires '${rule.partner}' to also be filled`
        } else if (rule.type === 'decimal' && !empty) {
            const n = Number(v)
            if (isNaN(n)) return 'Must be a valid number'
            if (rule.min !== undefined && n < rule.min) return `Must be ≥ ${rule.min}`
        } else if (rule.type === 'integer' && !empty) {
            const n = Number(v)
            if (!Number.isInteger(n)) return 'Must be a whole number'
            if (rule.min !== undefined && n < rule.min) return `Must be ≥ ${rule.min}`
        } else if (rule.type === 'text' && !empty && rule.max_length) {
            if (v.length > rule.max_length) return `Too long (${v.length}/${rule.max_length} chars)`
        }
        break
    }
    return null
}

// ── Exact copy of ProductGrid's isReadOnly ────────────────────────────────────
function isReadOnly(key) {
    if (key.endsWith(' ID')) return true
    if ([
        'Created At', 'Updated At', 'Published At', 'Gift Card',
        'Fulfillment Service', 'Sync Status', 'Last Synced', 'Collection Names',
        'Product Category ID', 'Product Category Name', 'Product Category Full Path'
    ].includes(key)) return true
    return false
}

// ── Classify keys into panel sections ────────────────────────────────────────
function classifyKeys(allKeys) {
    const MEDIA_KEYS = new Set(['Image URLs', 'Image Alt Text'])
    const PRICE_KEYS = new Set(['Variant Price', 'Variant Compare At Price'])
    const INVENTORY_KEYS = k => k === 'Variant Inventory Qty' || k.startsWith('Inventory Qty -') || k === 'Variant SKU' || k === 'Variant Barcode'
    const SHIPPING_KEYS = new Set(['Variant Grams', 'Variant Weight Unit', 'Variant Requires Shipping', 'Variant Fulfillment Service', 'Country of Origin', 'HS Code'])
    const SEO_KEYS = new Set(['SEO Title', 'SEO Description', 'Handle'])
    const SIDEBAR_KEYS = new Set(['Status', 'Vendor', 'Type', 'Tags', 'Collection Handles', 'Collection Names', 'Product Category ID', 'Product Category Name', 'Product Category Full Path'])
    const VARIANT_KEYS = new Set(['Variant ID', 'Option1 Name', 'Option1 Value', 'Option2 Name', 'Option2 Value', 'Option3 Name', 'Option3 Value', 'Variant Position'])
    const SKIP_KEYS = new Set(['Product ID', 'Title', 'Body (HTML)', 'Delete', 'Sync Status', 'Last Synced', 'Created At', 'Updated At', 'Published At'])

    const s = { media: [], price: [], inventory: [], shipping: [], seo: [], sidebar: [], metafields: [], variantCore: [], other: [] }
    for (const k of allKeys) {
        if (SKIP_KEYS.has(k)) continue
        if (MEDIA_KEYS.has(k)) { s.media.push(k); continue }
        if (PRICE_KEYS.has(k)) { s.price.push(k); continue }
        if (INVENTORY_KEYS(k)) { s.inventory.push(k); continue }
        if (SHIPPING_KEYS.has(k)) { s.shipping.push(k); continue }
        if (SEO_KEYS.has(k)) { s.seo.push(k); continue }
        if (SIDEBAR_KEYS.has(k)) { s.sidebar.push(k); continue }
        if (VARIANT_KEYS.has(k)) { s.variantCore.push(k); continue }
        if (k.includes('.') && !k.startsWith('Inventory Qty -')) { s.metafields.push(k); continue }
        s.other.push(k)
    }
    return s
}

// ── Derive allowed values from all rows (mirrors ProductGrid useEffects) ──────
function deriveAllowedValues(allRows) {
    const vendors = new Set(), statuses = new Set(), types = new Set()
    for (const row of allRows) {
        if (row['Vendor']) vendors.add(String(row['Vendor']).trim())
        if (row['Status']) statuses.add(String(row['Status']).trim())
        if (row['Type']) types.add(String(row['Type']).trim())
    }
    return {
        vendors: Array.from(vendors).filter(Boolean).sort(),
        statuses: Array.from(statuses).filter(Boolean).sort(),
        types: Array.from(types).filter(Boolean).sort(),
    }
}

// ── Get dropdown options for a field — mirrors ProductGrid column logic ────────
function getFieldOptions(key, fieldSchema, metafieldDefs, metafieldOwners, allowed) {
    const SEO_META_KEYS = new Set(['global.title_tag', 'global.description_tag'])
    const isMetafield = key.includes('.') && !key.startsWith('Inventory Qty -') && !SEO_META_KEYS.has(key)

    if (isMetafield) {
        const owner = metafieldOwners?.[key]
        const prodDef = metafieldDefs?.product?.[key] || null
        const varDef = metafieldDefs?.variant?.[key] || null
        const mfDef = (owner === 'product' ? prodDef : owner === 'variant' ? varDef : varDef || prodDef) || null
        const mfType = mfDef?.type || null
        if (mfType === 'boolean') return ['', 'true', 'false']
        if (Array.isArray(mfDef?.choices) && mfDef.choices.length)
            return ['', ...Array.from(new Set(mfDef.choices.map(v => String(v).trim()).filter(Boolean)))]
    }

    // Enum from fieldSchema (Shopify introspection)
    const enumVals = fieldSchema?.enums?.[key]
    if (Array.isArray(enumVals) && enumVals.length) return ['', ...enumVals]

    // Fixed dropdowns — same as ProductGrid
    if (key === 'Vendor') return allowed.vendors.length ? ['', ...allowed.vendors] : null
    if (key === 'Status') return allowed.statuses.length ? ['', ...allowed.statuses] : ['', 'active', 'draft', 'archived']
    if (key === 'Type') return allowed.types.length ? ['', ...allowed.types] : null
    if (key === 'Delete') return ['', 'YES']

    return null
}

// ── Collection Handles field with autocomplete ────────────────────────────────
function CollectionHandlesField({ value, onChange, readOnly, fullWidth, error, storeCollectionHandles }) {
    const [localValue, setLocalValue] = useState(value)
    const [focused, setFocused] = useState(false)
    const inputRef = useRef(null)
    const containerRef = useRef(null)

    useEffect(() => { setLocalValue(value) }, [value])

    const options = useMemo(
        () => (storeCollectionHandles || []).map(x => String(x).trim().toLowerCase()).filter(Boolean),
        [storeCollectionHandles]
    )

    // Current token being typed (last comma-separated segment)
    const currentToken = useMemo(() => {
        const parts = localValue.split(',')
        return (parts[parts.length - 1] || '').trim().toLowerCase()
    }, [localValue])

    const suggestions = useMemo(() => {
        if (!focused) return []
        if (!currentToken) return options.slice(0, 12)
        return options.filter(h => h.startsWith(currentToken)).slice(0, 12)
    }, [options, currentToken, focused])

    function applySuggestion(handle) {
        const parts = localValue.split(',')
        parts[parts.length - 1] = handle
        const next = parts.map(x => x.trim()).filter(Boolean).join(', ') + ', '
        setLocalValue(next)
        onChange(next.trim().replace(/,\s*$/, ''))
        setTimeout(() => inputRef.current?.focus(), 0)
    }

    function handleBlur(e) {
        // Don't blur if clicking a suggestion
        if (containerRef.current?.contains(e.relatedTarget)) return
        setFocused(false)
        if (localValue !== value) onChange(localValue)
    }

    return (
        <div
            ref={containerRef}
            className={`${styles.field} ${fullWidth ? styles.fieldFull : ''}`}
            style={{ position: 'relative' }}
        >
            <label className={`${styles.label} ${error ? styles.labelError : ''}`}>Collection Handles</label>
            <textarea
                ref={inputRef}
                className={`${styles.input} ${styles.textarea} ${readOnly ? styles.roInput : ''} ${error ? styles.inputError : ''}`}
                value={localValue}
                readOnly={readOnly}
                onChange={e => setLocalValue(e.target.value)}
                onFocus={() => setFocused(true)}
                onBlur={handleBlur}
                placeholder="handle1, handle2"
            />
            {suggestions.length > 0 && (
                <div className={styles.suggestList}>
                    {suggestions.map(h => (
                        <button
                            key={h}
                            type="button"
                            className={styles.suggestItem}
                            tabIndex={0}
                            onMouseDown={e => { e.preventDefault(); applySuggestion(h) }}
                        >
                            {h}
                        </button>
                    ))}
                </div>
            )}
            {error && <div className={styles.fieldError}>{error}</div>}
        </div>
    )
}

// ── Field component — input, textarea, or select depending on context ─────────
function Field({ fieldKey, value, onChange, readOnly, fullWidth, error, options }) {
    const isLong = ['Body (HTML)', 'SEO Description', 'Tags', 'Collection Handles', 'Image URLs'].includes(fieldKey)
    const [localValue, setLocalValue] = useState(value)

    // Sync local value if parent value changes externally (e.g. different product opened)
    useEffect(() => {
        setLocalValue(value)
    }, [value])

    const handleChange = e => setLocalValue(e.target.value)
    const handleBlur = () => { if (!readOnly && localValue !== value) onChange(localValue) }

    let control
    if (options && !readOnly) {
        control = (
            <select
                className={`${styles.input} ${styles.selectInput} ${error ? styles.inputError : ''}`}
                value={localValue}
                onChange={e => { setLocalValue(e.target.value); onChange(e.target.value) }}
            >
                {options.map(o => <option key={o} value={o}>{o || '(none)'}</option>)}
            </select>
        )
    } else if (isLong) {
        control = (
            <textarea
                className={`${styles.input} ${styles.textarea} ${readOnly ? styles.roInput : ''} ${error ? styles.inputError : ''}`}
                value={localValue}
                readOnly={readOnly}
                onChange={handleChange}
                onBlur={handleBlur}
            />
        )
    } else {
        control = (
            <input
                className={`${styles.input} ${readOnly ? styles.roInput : ''} ${error ? styles.inputError : ''}`}
                value={localValue}
                readOnly={readOnly}
                onChange={handleChange}
                onBlur={handleBlur}
            />
        )
    }

    return (
        <div className={`${styles.field} ${fullWidth ? styles.fieldFull : ''}`}>
            <label className={`${styles.label} ${error ? styles.labelError : ''}`}>{fieldKey}</label>
            {control}
            {error && <div className={styles.fieldError}>{error}</div>}
        </div>
    )
}

// ── Collapsible section card ──────────────────────────────────────────────────
function Section({ title, defaultOpen = true, children }) {
    const [open, setOpen] = useState(defaultOpen)
    return (
        <div className={styles.section}>
            <button className={styles.sectionHeader} onClick={() => setOpen(o => !o)}>
                <span>{title}</span>
                <span className={styles.sectionChevron}>{open ? '▾' : '▸'}</span>
            </button>
            {open && <div className={styles.sectionBody}>{children}</div>}
        </div>
    )
}

// ── Image gallery ─────────────────────────────────────────────────────────────
function MediaSection({ value, onChange, error }) {
    const urls = String(value || '').split(',').map(u => u.trim()).filter(Boolean)
    return (
        <div className={styles.mediaGrid}>
            {urls.map((url, i) => (
                <div key={i} className={styles.mediaThumb}
                    style={{ backgroundImage: `url(${url})` }}
                    onClick={() => window.open(url, '_blank')}
                    title={url}
                />
            ))}
            <div className={styles.mediaAdd}>＋</div>
            <Field fieldKey="Image URLs" value={value} onChange={onChange} fullWidth error={error} />
        </div>
    )
}

// ── Single variant row in the variants list ───────────────────────────────────
function VariantRow({ vr, idx, activeVariant, setActiveVariant, onDelete }) {
    const label = [vr['Option1 Value'], vr['Option2 Value'], vr['Option3 Value']]
        .filter(Boolean).join(' / ') || `Variant ${idx + 1}`
    const price = vr['Variant Price'] || '—'
    const sku = vr['Variant SKU'] || '—'
    const inv = Object.entries(vr)
        .filter(([k]) => k.startsWith('Inventory Qty -'))
        .reduce((sum, [, v]) => {
            const n = parseInt(v, 10)
            return sum + (isNaN(n) ? 0 : n)
        }, 0)
    const imgUrl = String(vr['Image URLs'] || '').split(',').map(u => u.trim()).find(u => u.startsWith('http')) || ''
    return (
        <div
            className={`${styles.variantRow} ${activeVariant === idx ? styles.variantRowActive : ''}`}
            onClick={() => setActiveVariant(idx)}
        >
            <div className={styles.vrThumb}>
                {imgUrl
                    ? <div className={styles.vrImg} style={{ backgroundImage: `url(${imgUrl})` }} />
                    : <div className={styles.vrImgEmpty} />}
            </div>
            <div className={styles.vrInfo}>
                <div className={styles.vrLabel}>{label}</div>
                <div className={styles.vrMeta}>{sku !== '—' ? `SKU: ${sku}` : ''}</div>
            </div>
            <div className={styles.vrRight}>
                <div className={styles.vrPrice}>{price !== '—' ? `$${price}` : '—'}</div>
                <div className={styles.vrInv}>{inv} in stock</div>
            </div>
            <button className={styles.vrDelete}
                onClick={e => { e.stopPropagation(); onDelete(idx) }}>✕
            </button>
        </div>
    )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function ProductPanel({
    product, allKeys, productLevelKeys,
    onClose, onSave, onDelete,
    selectedStore, isSyncing, setIsSyncing,
    fieldSchema = { enums: {}, validations: {} },
    storeCollectionHandles = [],
    metafieldDefs = { product: {}, variant: {} },
    metafieldOwners = {},
    allRows = [],
}) {
    const [productRow, setProductRow] = useState(() => ({ ...product.productRow }))
    const [variantRows, setVariantRows] = useState(() => product.variantRows.map(r => ({ ...r })))
    const [activeVariant, setActiveVariant] = useState(0)
    const [syncStatus, setSyncStatus] = useState(null)
    const [dirty, setDirty] = useState(false)

    // Re-init when a different product is opened
    useEffect(() => {
        setProductRow({ ...product.productRow })
        setVariantRows(product.variantRows.map(r => ({ ...r })))
        setActiveVariant(0)
        setSyncStatus(null)
        setDirty(false)
    }, [product.productRow['Product ID'] || product.productRow['Handle']])

    const sections = useMemo(() => classifyKeys(allKeys), [allKeys])

    // Derive allowed dropdown values from ALL rows (same as ProductGrid useEffects)
    const allowed = useMemo(() => deriveAllowedValues(allRows), [allRows])

    // Shorthand setters
    const setP = (key, val) => {
        setProductRow(p => ({ ...p, [key]: val }))
        // If it's a product-level key, propagate to all variant rows too
        if (productLevelKeys.has(key)) {
            setVariantRows(prev => prev.map(vr => ({ ...vr, [key]: val })))
        }
        setDirty(true)
    }
    const setV = (idx, key, val) => {
        setVariantRows(prev => {
            const next = [...prev]
            next[idx] = { ...next[idx], [key]: val }
            return next
        })
        setDirty(true)
    }

    // Get dropdown options for a field
    const opts = (key) => getFieldOptions(key, fieldSchema, metafieldDefs, metafieldOwners, allowed)

    // Validate a field with the correct row context (mirrors getCellValidationError usage in ProductGrid)
    const activeVR = variantRows[activeVariant] || {}
    const validate = (key, value, isVariant) => {
        const rowData = isVariant ? activeVR : productRow
        return getCellValidationError(key, value, fieldSchema, rowData, storeCollectionHandles)
    }

    // Render a Field with options + validation wired up
    const F = ({ k, isVariant = false, fullWidth = false }) => {
        const value = isVariant ? (activeVR[k] ?? '') : (productRow[k] ?? '')
        const ro = isReadOnly(k)
        const options = ro ? null : opts(k)
        const error = ro ? null : validate(k, value, isVariant)
        const onChange = isVariant ? v => setV(activeVariant, k, v) : v => setP(k, v)

        // Collection Handles gets its own autocomplete component
        if (k === 'Collection Handles' && !ro) {
            return (
                <CollectionHandlesField
                    value={String(value)}
                    onChange={onChange}
                    readOnly={ro}
                    fullWidth={fullWidth}
                    error={error}
                    storeCollectionHandles={storeCollectionHandles}
                />
            )
        }

        return (
            <Field
                fieldKey={k}
                value={String(value)}
                onChange={onChange}
                readOnly={ro}
                fullWidth={fullWidth}
                options={options}
                error={error}
            />
        )
    }

    function addVariant() {
        const blank = Object.fromEntries(allKeys.map(k => [
            k, productLevelKeys.has(k) ? (productRow[k] ?? '') : ''
        ]))
        setVariantRows(prev => [...prev, blank])
        setActiveVariant(variantRows.length)
        setDirty(true)
    }

    async function handleSync() {
        if (!selectedStore) return
        setSyncStatus('syncing'); setIsSyncing(true)
        try {
            const pid = productRow['Product ID']
            await syncProduct(
                selectedStore.store_name,
                pid || '__new__',
                productRow,
                variantRows
            )
            setSyncStatus('done')
            onSave({ productRow, variantRows })
            setDirty(false)
            // Close panel for new products — parent will reload fresh data
            if (!pid) onClose()
        } catch {
            setSyncStatus('error')
        } finally {
            setIsSyncing(false)
        }
    }

    async function handleDeleteProduct() {
        if (!productRow['Product ID']) return
        if (!confirm(`Delete "${productRow['Title']}"? This cannot be undone.`)) return

        setSyncStatus('syncing')
        setIsSyncing(true)
        try {
            // Mark all variant rows for deletion
            const markedVariants = variantRows.map(vr => ({ ...vr, 'Delete': 'YES' }))
            const markedProduct = { ...productRow, 'Delete': 'YES' }

            await syncProduct(
                selectedStore.store_name,
                productRow['Product ID'],
                markedProduct,
                markedVariants
            )
            if (onDelete) onDelete(productRow['Product ID'])
            onClose()
        } catch (e) {
            setSyncStatus('error')
            console.error(e)
        } finally {
            setIsSyncing(false)
        }
    }

    async function handleDeleteVariant(idx) {
        const vr = variantRows[idx]
        const vid = vr['Variant ID']

        // New variant (no ID) — just remove locally
        if (!vid || vid === '' || vid.toLowerCase() === 'nan') {
            setVariantRows(prev => prev.filter((_, i) => i !== idx))
            setActiveVariant(v => Math.max(0, v >= idx ? v - 1 : v))
            setDirty(true)
            return
        }

        if (!confirm('Delete this variant? This cannot be undone.')) return

        setSyncStatus('syncing')
        setIsSyncing(true)
        try {
            const markedVariant = { ...vr, 'Delete': 'YES' }
            await syncProduct(
                selectedStore.store_name,
                productRow['Product ID'],
                productRow,
                [markedVariant]
            )
            setVariantRows(prev => prev.filter((_, i) => i !== idx))
            setActiveVariant(v => Math.max(0, v >= idx ? v - 1 : v))
            setSyncStatus('done')
            setDirty(false)
        } catch (e) {
            setSyncStatus('error')
            console.error(e)
        } finally {
            setIsSyncing(false)
        }
    }

    const status = String(productRow['Status'] || '').toLowerCase()
    const dotColor = { active: '#10b981', draft: '#f59e0b', archived: '#94a3b8' }[status] || '#94a3b8'

    const productMetafields = sections.metafields.filter(k => productLevelKeys.has(k))
    const variantMetafields = sections.metafields.filter(k => !productLevelKeys.has(k))
    const productOther = sections.other.filter(k => productLevelKeys.has(k))
    const variantOther = sections.other.filter(k => !productLevelKeys.has(k))

    return (
        <>
            <div className={styles.backdrop} onClick={onClose} />
            <div className={styles.panel}>

                {/* ── Top bar ── */}
                <div className={styles.topBar}>
                    <div className={styles.topLeft}>
                        <button className={styles.backBtn} onClick={onClose}>← Back</button>
                        <div className={styles.topTitle}>{productRow['Title'] || 'Product'}</div>
                        <div className={styles.topStatusPill} style={{ '--dot': dotColor }}>
                            <span className={styles.topStatusDot} />
                            {status || '—'}
                        </div>
                    </div>
                    <div className={styles.topActions}>
                        {dirty && <span className={styles.unsavedDot} title="Unsaved changes">●</span>}
                        {productRow['Product ID'] && (
                            <button className={styles.deleteBtn} onClick={handleDeleteProduct}
                                disabled={isSyncing}>
                                🗑 Delete
                            </button>
                        )}
                        <button className={styles.syncBtn} onClick={handleSync}
                            disabled={isSyncing || (!productRow['Product ID'] && !productRow['Title'])}>
                            {syncStatus === 'syncing' ? '…' : syncStatus === 'done' ? '✓ Synced' : syncStatus === 'error' ? '✕ Error' : '⟳ Sync'}
                        </button>
                    </div>
                </div>

                {/* ── Two-column layout ── */}
                <div className={styles.layout}>

                    {/* ══ LEFT ══ */}
                    <div className={styles.main}>

                        <Section title="Title">
                            <F k="Title" fullWidth />
                        </Section>

                        <Section title="Description">
                            <F k="Body (HTML)" fullWidth />
                        </Section>

                        {productRow['Image URLs'] !== undefined && (
                            <Section title="Media">
                                <MediaSection
                                    value={productRow['Image URLs'] || ''}
                                    onChange={v => setP('Image URLs', v)}
                                    error={validate('Image URLs', productRow['Image URLs'] || '', false)}
                                />
                                {sections.media.filter(k => k !== 'Image URLs').map(k => (
                                    <F key={k} k={k} fullWidth />
                                ))}
                            </Section>
                        )}

                        <Section title={`Variants (${variantRows.length})`}>
                            <div className={styles.variantList}>
                                {variantRows.map((vr, i) => (
                                    <VariantRow key={i} vr={vr} idx={i}
                                        activeVariant={activeVariant}
                                        setActiveVariant={setActiveVariant}
                                        onDelete={handleDeleteVariant} />
                                ))}
                            </div>
                            <button className={styles.addVariantBtn} onClick={addVariant}>
                                + Add variant
                            </button>

                            {variantRows.length > 0 && (
                                <div className={styles.variantDetail}>
                                    <div className={styles.variantDetailTitle}>
                                        Editing: {[activeVR['Option1 Value'], activeVR['Option2 Value'], activeVR['Option3 Value']]
                                            .filter(Boolean).join(' / ') || `Variant ${activeVariant + 1}`}
                                    </div>
                                    <div className={styles.fieldGrid2}>
                                        {sections.variantCore.map(k => <F key={k} k={k} isVariant />)}
                                        {variantOther.map(k => <F key={k} k={k} isVariant />)}
                                    </div>

                                    {sections.price.length > 0 && (
                                        <div className={styles.variantSubSection}>
                                            <div className={styles.variantDetailTitle}>Pricing</div>
                                            <div className={styles.fieldRow}>
                                                {sections.price.map(k => <F key={k} k={k} isVariant />)}
                                            </div>
                                        </div>
                                    )}

                                    {sections.inventory.length > 0 && (
                                        <div className={styles.variantSubSection}>
                                            <div className={styles.variantDetailTitle}>Inventory</div>
                                            <div className={styles.fieldGrid2}>
                                                {sections.inventory.map(k => <F key={k} k={k} isVariant />)}
                                            </div>
                                        </div>
                                    )}

                                    {sections.shipping.length > 0 && (
                                        <div className={styles.variantSubSection}>
                                            <div className={styles.variantDetailTitle}>Shipping</div>
                                            <div className={styles.fieldGrid2}>
                                                {sections.shipping.map(k => {
                                                    const isVariant = activeVR[k] !== undefined
                                                    return <F key={k} k={k} isVariant={isVariant} />
                                                })}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </Section>

                        {sections.metafields.length > 0 && (
                            <Section title="Metafields" defaultOpen={false}>
                                {productMetafields.length > 0 && (
                                    <>
                                        <div className={styles.metaSubtitle}>Product</div>
                                        <div className={styles.fieldGrid2}>
                                            {productMetafields.map(k => <F key={k} k={k} />)}
                                        </div>
                                    </>
                                )}
                                {variantMetafields.length > 0 && (
                                    <>
                                        <div className={styles.metaSubtitle}>Variant</div>
                                        <div className={styles.fieldGrid2}>
                                            {variantMetafields.map(k => <F key={k} k={k} isVariant />)}
                                        </div>
                                    </>
                                )}
                            </Section>
                        )}

                        {sections.seo.length > 0 && (
                            <Section title="Search engine listing" defaultOpen={false}>
                                <div className={styles.fieldGrid1}>
                                    {sections.seo.map(k => <F key={k} k={k} fullWidth />)}
                                </div>
                            </Section>
                        )}

                        {productOther.length > 0 && (
                            <Section title="Other" defaultOpen={false}>
                                <div className={styles.fieldGrid2}>
                                    {productOther.map(k => <F key={k} k={k} />)}
                                </div>
                            </Section>
                        )}
                    </div>

                    {/* ══ RIGHT (sidebar) ══ */}
                    <div className={styles.sidebar}>

                        <div className={styles.sideCard}>
                            <div className={styles.sideCardTitle}>Status</div>
                            <F k="Status" fullWidth />
                        </div>

                        <div className={styles.sideCard}>
                            <div className={styles.sideCardTitle}>Product organization</div>
                            {['Type', 'Vendor', 'Collection Handles', 'Tags'].map(k =>
                                productRow[k] !== undefined && <F key={k} k={k} fullWidth />
                            )}
                        </div>

                        <div className={styles.sideCard}>
                            <div className={styles.sideCardTitle}>Details</div>
                            {['Product ID', 'Handle', 'Created At', 'Updated At', 'Published At'].map(k =>
                                productRow[k] != null && productRow[k] !== '' && (
                                    <Field key={k} fieldKey={k}
                                        value={String(productRow[k])}
                                        readOnly fullWidth />
                                )
                            )}
                        </div>

                        {(productRow['Sync Status'] || productRow['Last Synced']) && (
                            <div className={styles.sideCard}>
                                <div className={styles.sideCardTitle}>Sync</div>
                                {['Sync Status', 'Last Synced'].map(k =>
                                    productRow[k] && (
                                        <Field key={k} fieldKey={k}
                                            value={productRow[k]} readOnly fullWidth />
                                    )
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </>
    )
}