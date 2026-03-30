import { useState, useMemo, useRef, useCallback, useEffect } from 'react'
import { AgGridReact } from 'ag-grid-react'
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community'
import styles from './ExcelGrid.module.css'

ModuleRegistry.registerModules([AllCommunityModule])

const STATUS_COLORS = {
    UPDATED: { bg: '#eaf8ee' },
    CREATED: { bg: '#eef3ff' },
    ERROR: { bg: '#fdecec' },
    CONFLICT: { bg: '#fff4de' },
    DELETED: { bg: '#fbe7e7' },
    SKIPPED: { bg: '' },
}

export default function ExcelGrid({
    rows,
    setRows,
    readOnlyCols = [],
    dropdownCols = {},
    syncState = null,
    isSyncing = false,
    selectedStore = null,
    loadKey = 0,
    validateCell = null,
    metafieldDefs = {},
    linkedCols = {},
}) {
    const gridRef = useRef(null)
    const syncStateRef = useRef(syncState)
    const readOnlySet = useMemo(() => new Set(readOnlyCols), [readOnlyCols.join('|')])
    const [selectedRowIdx, setSelectedRowIdx] = useState(null)

    useEffect(() => { syncStateRef.current = syncState }, [syncState])

    useEffect(() => {
        if (!gridRef.current?.api) return
        gridRef.current.api.refreshCells({ force: true })
        gridRef.current.api.redrawRows()
    }, [syncState])

    useEffect(() => {
        setSelectedRowIdx(null)
    }, [loadKey])

    const onRowClicked = useCallback((params) => {
        setSelectedRowIdx(params.node.rowIndex)
    }, [])

    const onCellValueChanged = useCallback((params) => {
        setRows(prev => {
            const next = [...prev]
            const updated = { ...params.data }

            // Apply cascading linked column updates
            if (linkedCols[params.column.colId]) {
                const newVal = params.newValue
                const linked = linkedCols[params.column.colId]
                const match = linked.find(opt => opt.value === newVal)
                if (match) {
                    Object.entries(match.set).forEach(([k, v]) => { updated[k] = v })
                }
            }

            next[params.node.rowIndex] = updated
            return next
        })
        params.api.refreshCells({ rowNodes: [params.node], force: true })
    }, [setRows, linkedCols])

    const getRowStyle = useCallback((params) => {
        const deleteVal = String(params.data?.['Delete'] ?? '').trim().toUpperCase()
        if (deleteVal === 'YES') return { background: STATUS_COLORS.DELETED.bg }

        const syncStatus = String(params.data?.['Sync Status'] ?? '').trim().toUpperCase()
        if (syncStatus && STATUS_COLORS[syncStatus]?.bg) {
            return { background: STATUS_COLORS[syncStatus].bg }
        }
        return {}
    }, [])

    const columnDefs = useMemo(() => {
        if (!rows.length) return []

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
            },
            headerClass: styles.readOnlyHeader,
        }

        const dataCols = Object.keys(rows[0]).map(key => {
            const ro = readOnlySet.has(key)
            const isDelete = key === 'Delete'
            const isSync = key === 'Sync Status'
            const dropdown = dropdownCols[key] || null
            const defn = metafieldDefs[key]
            const metafieldTooltip = defn
                ? `${defn.name} · ${defn.type}${defn.choices ? ` · choices: ${defn.choices.join(', ')}` : ''}${defn.max ? ` · max: ${defn.max}` : ''}`
                : undefined

            return {
                headerName: key,
                headerTooltip: metafieldTooltip,
                colId: key,
                valueGetter: (p) => p.data?.[key] ?? '',
                valueSetter: (p) => { p.data[key] = p.newValue; return true },
                editable: !ro,
                sortable: true,
                filter: true,
                resizable: true,
                pinned: key === 'Title' ? 'left' : undefined,
                headerClass: ro ? styles.readOnlyHeader : '',
                ...(dropdown ? {
                    cellEditor: 'agSelectCellEditor',
                    cellEditorParams: { values: dropdown },
                } : {}),
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
                    if (isSync) {
                        const v = String(params.value || '').toUpperCase()
                        if (v === 'UPDATED') { style.color = '#10b981'; style.fontWeight = '600' }
                        if (v === 'CREATED') { style.color = '#6366f1'; style.fontWeight = '600' }
                        if (v === 'ERROR') { style.color = '#ef4444'; style.fontWeight = '600' }
                        if (v === 'CONFLICT') { style.color = '#f59e0b'; style.fontWeight = '600' }
                        if (v === 'SKIPPED') { style.color = '#444' }
                    }
                    return style
                },
                ...(validateCell ? {
                    tooltipValueGetter: (params) => {
                        if (ro) return undefined
                        const err = validateCell(key, params.value, params.data)
                        return err ? `⚠ ${err}` : undefined
                    },
                    cellClassRules: {
                        [styles.cellError]: (params) => {
                            if (ro) return false
                            return !!validateCell(key, params.value, params.data)
                        }
                    },
                } : {}),
            }
        })

        return [rowNumberCol, ...dataCols]
    }, [
        rows.length > 0 ? Object.keys(rows[0]).join('|') : '',
        readOnlyCols.join('|'),
        JSON.stringify(dropdownCols),
    ])

    const defaultColDef = useMemo(() => ({
        minWidth: 80,
        cellClass: styles.cell,
        headerClass: styles.header,
        filter: true,
        menuTabs: ['filterMenuTab'],
    }), [])

    // ── Insert row ────────────────────────────────────────────────────────────
    function handleInsertRow() {
        if (!rows.length) return
        const blank = Object.fromEntries(Object.keys(rows[0]).map(k => [k, '']))
        const insertAt = selectedRowIdx !== null ? selectedRowIdx + 1 : rows.length
        setRows(prev => {
            const next = [...prev]
            next.splice(insertAt, 0, blank)
            return next
        })
        setTimeout(() => gridRef.current?.api?.ensureIndexVisible(insertAt, 'middle'), 50)
    }

    function handleRemoveRow() {
        if (selectedRowIdx === null) return
        setRows(prev => prev.filter((_, i) => i !== selectedRowIdx))
        setSelectedRowIdx(null)
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
            <div className={styles.emptySubtitle}>Click FETCH to pull data from Shopify</div>
        </div>
    )

    return (
        <div className={styles.gridContainer}>
            <div className={styles.toolbar}>
                <button className={styles.addRowBtn} onClick={handleInsertRow} disabled={isSyncing}>
                    + New Row
                </button>
                {selectedRowIdx !== null && (
                    <button className={styles.removeRowBtn} onClick={handleRemoveRow} disabled={isSyncing}>
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
                    suppressScrollOnNewData={true}
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