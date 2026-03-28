import { useState, useMemo, useRef, useCallback, useEffect, forwardRef, useImperativeHandle } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community'
import styles from './ProductGrid.module.css'

ModuleRegistry.registerModules([AllCommunityModule])

const STATUS_COLORS = {
    UPDATED: { bg: '#eaf8ee' },
    CREATED: { bg: '#eef3ff' },
    ERROR: { bg: '#fdecec' },
    CONFLICT: { bg: '#fff4de' },
    DELETED: { bg: '#fbe7e7' },
    SKIPPED: { bg: '' },
}


function shopifyThumb(url) {
    if (!url) return ''
    // Already has size suffix
    if (/_\d+x\d*\.|_small\.|_medium\.|_large\./.test(url)) return url
    // Add _small before extension, before query string
    const [base, query] = url.split('?')
    const dot = base.lastIndexOf('.')
    if (dot === -1) return url
    const thumb = base.slice(0, dot) + '_small' + base.slice(dot)
    return query ? `${thumb}?${query}` : thumb
}

// Generic cell validator — driven entirely by the field_schema loaded from the store.
// No field names, enum values, or limits are hardcoded here.
function getCellValidationError(key, value, fieldSchema = {}, rowData = null, allowedCollectionHandles = []) {
    const v = String(value || '').trim()
    const empty = !v || v.toLowerCase() === 'nan' || v.toLowerCase() === 'none'

    // Collection Handles — validate format always, validate existence if handles are loaded
    if (key === 'Collection Handles' && !empty) {
        const tokens = v.split(',').map(t => t.trim().toLowerCase()).filter(Boolean)
        // Format check — handle must be a valid Shopify slug (lowercase, alphanumeric + hyphens)
        const invalidFormat = tokens.filter(t => !/^[a-z0-9-]+$/.test(t))
        if (invalidFormat.length)
            return `Invalid format: "${invalidFormat.join('", "')}" — handles must be lowercase letters, numbers, hyphens only`
        // Existence check — only if we have loaded handles to compare against
        if (allowedCollectionHandles.length) {
            const notFound = tokens.filter(t => !allowedCollectionHandles.includes(t))
            if (notFound.length)
                return `Handle(s) not found in store: ${notFound.join(', ')}`
        }
    }

    // Enum check — values from Shopify schema introspection
    const enumVals = fieldSchema.enums?.[key]
    if (!empty && Array.isArray(enumVals) && enumVals.length) {
        if (!enumVals.map(e => e.toUpperCase()).includes(v.toUpperCase()))
            return `Must be one of: ${enumVals.join(', ')}`
    }

    // Rule-based check — iterate validation table
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

// ── Image preview cell renderer ──────────────────────────────────────────────

function ImagePreviewCell(params) {
    const raw = String(params.data?.['Image URLs'] || '')
    const originalUrl = raw.split(',').map(u => u.trim()).find(u => u.startsWith('http')) || ''
    const thumbUrl = shopifyThumb(originalUrl)
    if (!originalUrl) return null
    return (
        <div style={{ display: 'flex', alignItems: 'center', height: '100%', overflow: 'hidden' }}>
            <img
                src={thumbUrl}
                alt=""
                loading="lazy"
                decoding="async"
                width="44"
                height="38"
                style={{
                    height: '38px',
                    width: '44px',
                    objectFit: 'cover',
                    borderRadius: '3px',
                    cursor: 'pointer',
                    flexShrink: 0,
                }}
                onClick={(e) => { e.stopPropagation(); window.open(originalUrl, '_blank') }}
                onError={(e) => { e.currentTarget.style.display = 'none' }}
            />
        </div>
    )
}

function isReadOnly(key) {
    if (key.endsWith(' ID')) return true
    if ([
        'Created At', 'Updated At', 'Published At', 'Gift Card',
        'Fulfillment Service', 'Sync Status', 'Last Synced', 'Collection Names',
        'Product Category ID', 'Product Category Name', 'Product Category Full Path'
    ].includes(key)) return true
    return false
}

function getScopedMetafieldDef(key, defs, owners) {
    const owner = owners[key]
    const productDef = defs?.product?.[key] || null
    const variantDef = defs?.variant?.[key] || null

    if (owner === 'product') return productDef
    if (owner === 'variant') return variantDef

    return variantDef || productDef || null
}

const CollectionHandlesEditor = forwardRef((props, ref) => {
    const inputRef = useRef(null)
    const [value, setValue] = useState(String(props.value || ''))

    const options = useMemo(
        () => (props.options || []).map(x => String(x).trim().toLowerCase()).filter(Boolean),
        [props.options]
    )

    const currentToken = useMemo(() => {
        const parts = value.split(',')
        return (parts[parts.length - 1] || '').trim().toLowerCase()
    }, [value])

    const suggestions = useMemo(() => {
        if (!currentToken) return options.slice(0, 12)
        return options.filter(h => h.startsWith(currentToken)).slice(0, 12)
    }, [options, currentToken])

    const applySuggestion = (handle) => {
        const parts = value.split(',')
        parts[parts.length - 1] = handle
        const next = parts.map(x => x.trim()).filter(Boolean).join(', ') + ', '
        setValue(next)
        setTimeout(() => inputRef.current?.focus(), 0)
    }

    useImperativeHandle(ref, () => ({
        getValue: () => value,
        isPopup: () => true,
        afterGuiAttached: () => {
            setTimeout(() => {
                inputRef.current?.focus()
                inputRef.current?.setSelectionRange(value.length, value.length)
            }, 0)
        },
    }), [value])

    return (
        <div className={styles.collectionEditorPopup}>
            <input
                ref={inputRef}
                className={styles.collectionEditorInput}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="handle1, handle2"
            />
            <div className={styles.collectionEditorList}>
                {suggestions.length ? suggestions.map((h) => (
                    <button
                        key={h}
                        type="button"
                        className={styles.collectionEditorItem}
                        onMouseDown={(e) => {
                            e.preventDefault()
                            applySuggestion(h)
                        }}
                    >
                        {h}
                    </button>
                )) : (
                    <div className={styles.collectionEditorEmpty}>No matching handle</div>
                )}
            </div>
        </div>
    )
})

export default function ProductGrid({ rows, setRows, syncState, isSyncing, selectedStore, rollbackChangedIndices, loadKey, metafieldDefs = {}, metafieldOwners = {}, fieldSchema = { enums: {}, validations: {} }, storeCollectionHandles = [] }) {
    const gridRef = useRef(null)
    const syncStateRef = useRef(syncState)
    const rollbackRef = useRef(rollbackChangedIndices)
    const [selectedRowIdx, setSelectedRowIdx] = useState(null)
    const [allowedVendors, setAllowedVendors] = useState([])
    const [allowedStatuses, setAllowedStatuses] = useState([])
    const [allowedTypes, setAllowedTypes] = useState([])
    const [allowedCollectionHandles, setAllowedCollectionHandles] = useState([])

    // storeCollectionHandles = authoritative list from API (all store collections)
    // allowedCollectionHandles = derived from grid rows (fallback if API not loaded)
    // Prefer store handles when available
    const mergedCollectionHandles = useMemo(() => {
        if (storeCollectionHandles.length) return storeCollectionHandles
        return allowedCollectionHandles
    }, [storeCollectionHandles, allowedCollectionHandles])

    const handleInsertRow = useCallback((mode) => {
        if (!rows.length) return

        const sourceRow = selectedRowIdx !== null ? rows[selectedRowIdx] : null
        const PRODUCT_LEVEL = ['Product ID', 'Title', 'Body (HTML)', 'Vendor', 'Type',
            'Tags', 'Status', 'Handle', 'SEO Title', 'SEO Description',
            'Image URLs', 'Image Alt Text', 'Collection Handles']

        const blank = Object.fromEntries(Object.keys(rows[0]).map(k => {
            if (mode === 'variant' && sourceRow) {
                return [k, PRODUCT_LEVEL.includes(k) ? (sourceRow[k] ?? '') : '']
            }
            return [k, '']
        }))

        const insertAt = mode === 'product' ? rows.length : (selectedRowIdx !== null ? selectedRowIdx + 1 : rows.length)
        setRows(prev => {
            const next = [...prev]
            next.splice(insertAt, 0, blank)
            return next
        })
        setTimeout(() => {
            gridRef.current?.api?.ensureIndexVisible(insertAt, 'middle')
        }, 50)
    }, [rows, selectedRowIdx, setRows])

    const onRowClicked = useCallback((params) => {
        setSelectedRowIdx(params.node.rowIndex)
    }, [])

    useEffect(() => {
        setSelectedRowIdx(null)
    }, [loadKey])

    useEffect(() => {
        const seen = new Set()
        for (const row of rows) {
            const vendor = String(row?.['Vendor'] || '').trim()
            if (vendor) seen.add(vendor)
        }
        setAllowedVendors(Array.from(seen).sort((a, b) => a.localeCompare(b)))
    }, [loadKey])

    useEffect(() => {
        const seen = new Set()
        for (const row of rows) {
            const status = String(row?.['Status'] || '').trim()
            if (status) seen.add(status)
        }
        setAllowedStatuses(Array.from(seen).sort((a, b) => a.localeCompare(b)))
    }, [loadKey])

    useEffect(() => {
        const seen = new Set()
        for (const row of rows) {
            const type = String(row?.['Type'] || '').trim()
            if (type) seen.add(type)
        }
        setAllowedTypes(Array.from(seen).sort((a, b) => a.localeCompare(b)))
    }, [loadKey])

    useEffect(() => {
        const seen = new Set()
        for (const row of rows) {
            const raw = String(row?.['Collection Handles'] || '')
            for (const token of raw.split(',')) {
                const handle = token.trim().toLowerCase()
                if (handle) seen.add(handle)
            }
        }
        setAllowedCollectionHandles(Array.from(seen).sort((a, b) => a.localeCompare(b)))
    }, [loadKey])

    useEffect(() => {
        syncStateRef.current = syncState
    }, [syncState])

    useEffect(() => {
        rollbackRef.current = rollbackChangedIndices
    }, [rollbackChangedIndices])

    useEffect(() => {
        if (!gridRef.current?.api) return
        gridRef.current.api.refreshCells({ force: true })  // for cellClassRules
        gridRef.current.api.redrawRows()                    // for getRowStyle
    }, [syncState?.results, rollbackChangedIndices])

    const columnDefs = useMemo(() => {
        if (!rows.length) return []

        // Row number column — always first, pinned left
        const rowNumberCol = {
            headerName: '#',
            colId: '_rowNumber',
            width: 55,
            minWidth: 45,
            editable: false,
            sortable: false,
            filter: false,
            resizable: false,
            pinned: 'left',
            valueGetter: (p) => p.node.rowIndex + 1,
            cellStyle: {
                fontFamily: "'IBM Plex Mono', monospace",
                fontSize: '10px',
                color: '#9b8a73',
                textAlign: 'right',
                padding: '0 8px',
                userSelect: 'none',
                cursor: 'pointer',  // Add this
            },
            headerClass: styles.readOnlyHeader,
            onCellClicked: (params) => {  // Add this
                params.node.setSelected(!params.node.isSelected())
            }
        }

        // First column: image preview (always first, not from data keys)
        const imagePreviewCol = {
            headerName: 'IMG',
            colId: '_imagePreview',
            width: 120,
            minWidth: 50,
            editable: false,
            sortable: false,
            filter: false,
            resizable: true,
            pinned: 'left',
            cellRenderer: ImagePreviewCell,
            cellStyle: {
                padding: '3px 4px',
                display: 'flex',
                alignItems: 'center',
            },
            headerClass: styles.readOnlyHeader,
        }

        const dataCols = Object.keys(rows[0]).map(key => {
            const ro = isReadOnly(key)
            const isInvQty = key.startsWith('Inventory Qty -')
            const isDelete = key === 'Delete'
            const isVendor = key === 'Vendor'
            const isStatus = key === 'Status'
            const isType = key === 'Type'
            const isTags = key === 'Tags'
            const isCollectionHandles = key === 'Collection Handles'
            const isSyncStatus = key === 'Sync Status'
            // Enum-backed columns: values come from Shopify schema introspection via fieldSchema
            const isEnumField = Array.isArray(fieldSchema.enums?.[key]) && fieldSchema.enums[key].length > 0
            const enumValues = fieldSchema.enums?.[key] || []

            // Metafield column config (ns.key pattern, excluding inventory and SEO metafields)
            const SEO_META_KEYS = new Set(['global.title_tag', 'global.description_tag'])
            const isMetafield = key.includes('.') && !key.startsWith('Inventory Qty -') && !SEO_META_KEYS.has(key)
            const mfOwner = isMetafield ? (metafieldOwners[key] || null) : null
            const mfDef = isMetafield ? getScopedMetafieldDef(key, metafieldDefs, metafieldOwners) : null
            const mfType = mfDef?.type || null
            const mfChoices = (Array.isArray(mfDef?.choices) && mfDef.choices.length)
                ? Array.from(new Set(mfDef.choices.map((v) => String(v).trim()).filter(Boolean)))
                : null
            const isMetafieldBoolean = mfType === 'boolean'
            const isMetafieldChoice = !isMetafieldBoolean && !!mfChoices
            const metafieldTooltip = (isMetafield && mfDef)
                ? (() => {
                    const typeLine = `Type: ${mfType}`
                    const ownerLine = mfOwner ? ` | Owner: ${mfOwner}` : ''
                    const choiceLine = mfChoices ? ` | Choices: ${mfChoices.join(', ')}` : ''
                    const minLine = mfDef.min != null ? ` | Min: ${mfDef.min}` : ''
                    const maxLine = mfDef.max != null ? ` | Max: ${mfDef.max}` : ''
                    return typeLine + ownerLine + choiceLine + minLine + maxLine
                })()
                : undefined

            return {
                headerName: key,
                colId: key,
                headerTooltip: metafieldTooltip,
                valueGetter: (p) => p.data?.[key] ?? '',
                valueSetter: (p) => {
                    if (isCollectionHandles) {
                        const seen = new Set()
                        const normalized = String(p.newValue || '')
                            .split(',')
                            .map(x => x.trim().toLowerCase())
                            .filter(Boolean)
                            .filter(x => {
                                if (seen.has(x)) return false
                                seen.add(x)
                                return true
                            })
                            .sort((a, b) => a.localeCompare(b))
                            .join(', ')
                        p.data[key] = normalized
                        return true
                    }

                    if (isTags) {
                        const seen = new Set()
                        const normalized = String(p.newValue || '')
                            .split(',')
                            .map(x => x.trim())
                            .filter(Boolean)
                            .filter(x => {
                                const low = x.toLowerCase()
                                if (seen.has(low)) return false
                                seen.add(low)
                                return true
                            })
                            .sort((a, b) => a.localeCompare(b))
                            .join(', ')
                        p.data[key] = normalized
                        return true
                    }

                    p.data[key] = p.newValue
                    return true
                },
                editable: !ro,
                tooltipValueGetter: (params) => {
                    const err = getCellValidationError(key, params.value, fieldSchema, params.data, mergedCollectionHandles)
                    if (err) return `⚠ ${err}`
                    if (isCollectionHandles) return `Available handles: ${mergedCollectionHandles.join(', ') || '(none loaded yet)'}`
                    if (metafieldTooltip) return metafieldTooltip
                    return undefined
                },
                ...(isDelete ? {
                    cellEditor: 'agSelectCellEditor',
                    cellEditorParams: { values: ['', 'YES'] },
                } : {}),
                ...(isVendor ? {
                    cellEditor: 'agSelectCellEditor',
                    cellEditorParams: { values: ['', ...allowedVendors] },
                } : {}),
                ...(isStatus ? {
                    cellEditor: 'agSelectCellEditor',
                    cellEditorParams: { values: ['', ...allowedStatuses] },
                } : {}),
                ...(isType ? {
                    cellEditor: 'agSelectCellEditor',
                    cellEditorParams: { values: ['', ...allowedTypes] },
                } : {}),
                ...(isCollectionHandles ? {
                    cellEditor: CollectionHandlesEditor,
                    cellEditorPopup: true,
                    cellEditorParams: { options: mergedCollectionHandles },
                } : {}),
                ...(isMetafieldBoolean ? {
                    cellEditor: 'agSelectCellEditor',
                    cellEditorParams: { values: ['', 'true', 'false'] },
                } : {}),
                ...(isMetafieldChoice ? {
                    cellEditor: 'agSelectCellEditor',
                    cellEditorParams: { values: ['', ...mfChoices] },
                } : {}),
                ...(isEnumField ? {
                    cellEditor: 'agSelectCellEditor',
                    cellEditorParams: { values: ['', ...enumValues] },
                } : {}),
                sortable: true,
                filter: true,
                resizable: true,
                pinned: key === 'Title' ? 'left' : undefined,
                headerClass: ro ? styles.readOnlyHeader : '',
                cellStyle: (params) => {
                    const style = {
                        fontFamily: "'IBM Plex Mono', monospace",
                        fontSize: '11px',
                        color: ro ? '#8b7a62' : '#2f2417',
                        padding: '0 8px',
                    }
                    if (isDelete && params.value === 'YES') {
                        style.color = '#ef4444'
                        style.fontWeight = '600'
                    }
                    if (isInvQty && Number(params.value) > 0) {
                        style.color = '#10b981'
                    }
                    if (isSyncStatus) {
                        const v = params.value
                        if (v === 'UPDATED') { style.color = '#10b981'; style.fontWeight = '600' }
                        else if (v === 'CREATED') { style.color = '#6366f1'; style.fontWeight = '600' }
                        else if (v === 'ERROR') { style.color = '#ef4444'; style.fontWeight = '600' }
                        else if (v === 'CONFLICT') { style.color = '#f59e0b'; style.fontWeight = '600' }
                        else if (v === 'SKIPPED') { style.color = '#444' }
                    }
                    return style
                },

                cellClassRules: {
                    [styles.cellError]: (params) => {
                        if (ro) return false
                        return !!getCellValidationError(key, params.value, fieldSchema, params.data, mergedCollectionHandles)
                    }
                },
            }
        })

        return [rowNumberCol, imagePreviewCol, ...dataCols]
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        rows.length > 0 ? Object.keys(rows[0]).join('|') : '',
        allowedVendors.join('|'),
        allowedStatuses.join('|'),
        allowedTypes.join('|'),
        mergedCollectionHandles.join('|'),
        metafieldDefs,
        metafieldOwners,
        fieldSchema,
    ])

    const defaultColDef = useMemo(() => ({
        minWidth: 80,
        cellClass: styles.cell,
        headerClass: styles.header,
        filter: true,
        floatingFilter: false,  // Change this to false to remove the filter row
        menuTabs: ['filterMenuTab'],  // Show filter menu in header
    }), [])

    const onCellValueChanged = useCallback((params) => {
        setRows(prev => {
            const next = [...prev]
            next[params.node.rowIndex] = { ...params.data }
            return next
        })
        // Force the cell to re-render so cellStyle validation runs with the new value
        params.api.refreshCells({ rowNodes: [params.node], columns: [params.column], force: true })
    }, [setRows])

    const getRowStyle = useCallback((params) => {
        // Pre-sync: highlight rows marked for deletion
        const deleteVal = String(params.data?.['Delete'] ?? '').trim().toUpperCase()
        if (deleteVal === 'YES') {
            return { background: STATUS_COLORS.DELETED.bg }
        }
        // Rollback preview: highlight changed rows yellow
        if (rollbackRef.current?.has(params.node.rowIndex)) {
            return { background: '#fff6cc' }
        }
        // Post-sync: read Sync Status from row data directly
        const syncStatus = String(params.data?.['Sync Status'] ?? '').trim().toUpperCase()
        if (syncStatus && STATUS_COLORS[syncStatus]?.bg) {
            return { background: STATUS_COLORS[syncStatus].bg }
        }
        // Fallback: check syncStateRef results (for websocket/per-row updates)
        const results = syncStateRef.current?.results
        if (!results) return {}
        const status = results[params.node.rowIndex]
        if (!status || !STATUS_COLORS[status]?.bg) return {}
        return { background: STATUS_COLORS[status].bg }
    }, [])

    if (!selectedStore) {
        return (
            <div className={styles.empty}>
                <div className={styles.emptyIcon}>⬡</div>
                <div className={styles.emptyTitle}>No store selected</div>
                <div className={styles.emptySubtitle}>Select a store from the dropdown to begin</div>
            </div>
        )
    }

    if (rows.length === 0) {
        return (
            <div className={styles.empty}>
                <div className={styles.emptyIcon}>↓</div>
                <div className={styles.emptyTitle}>No data loaded</div>
                <div className={styles.emptySubtitle}>Click FETCH to pull products from Shopify</div>
            </div>
        )
    }

    return (
        <div className={styles.gridContainer}>
            <div className={styles.toolbar}>
                <button
                    className={styles.addRowBtn}
                    onClick={() => handleInsertRow('product')}
                    disabled={isSyncing}
                    title={selectedRowIdx !== null ? `Insert after row ${selectedRowIdx + 1}` : 'Append at end'}
                >
                    + New Product
                </button>
                {selectedRowIdx !== null && (rows[selectedRowIdx]?.['Product ID'] || rows[selectedRowIdx]?.['Title']) && (
                    <button
                        className={styles.addRowBtn}
                        onClick={() => handleInsertRow('variant')}
                        disabled={isSyncing}
                        title={`Add variant to same product as row ${selectedRowIdx + 1}`}
                    >
                        + Add Variant (after #{selectedRowIdx + 1})
                    </button>
                )}
                {selectedRowIdx !== null && !rows[selectedRowIdx]?.['Variant ID'] && (
                    <button
                        className={styles.removeRowBtn}
                        onClick={() => {
                            setRows(prev => prev.filter((_, i) => i !== selectedRowIdx))
                            setSelectedRowIdx(null)
                        }}
                        disabled={isSyncing}
                        title="Remove this unsaved row"
                    >
                        ✕ Remove Row
                    </button>
                )}
            </div>
            <div className={`ag-theme-alpine ${styles.grid}`}>
                <AgGridReact
                    ref={gridRef}
                    theme="legacy"
                    rowData={rows}
                    columnDefs={columnDefs}
                    defaultColDef={defaultColDef}
                    onCellValueChanged={onCellValueChanged}
                    getRowStyle={getRowStyle}
                    onRowClicked={onRowClicked}
                    rowSelection={{
                        mode: 'multiRow',
                        enableClickSelection: false,  // Disable click on data cells
                        checkboxes: false,  // No checkboxes
                        headerCheckbox: false  // No header checkbox
                    }}
                    suppressScrollOnNewData={true}
                    suppressColumnVirtualisation={false}
                    animateRows={false}
                    rowHeight={44}
                    headerHeight={32}
                    enableBrowserTooltips={true}
                    rowBuffer={10}
                />
            </div>
        </div>
    )
}