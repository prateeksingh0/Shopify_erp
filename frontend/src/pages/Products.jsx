import { useState, useCallback, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import ProductGrid from '../components/ProductGrid'
import SyncProgress from '../components/SyncProgress'
import RollbackPanel from '../components/RollbackPanel'
import ShopifyView from '../components/ShopifyView'
import styles from './Products.module.css'
import {
    getProducts, triggerFetch, startSync, saveProducts,
    getMetafieldDefs, getMetafieldOwners, getFieldSchema, getCollectionHandles,
    addStore
} from '../api'

function parseCSVLine(line) {
    const result = []
    let current = ''
    let inQuotes = false
    for (let i = 0; i < line.length; i++) {
        const ch = line[i]
        if (ch === '"') {
            if (inQuotes && line[i + 1] === '"') { current += '"'; i++ }
            else inQuotes = !inQuotes
        } else if (ch === ',' && !inQuotes) {
            result.push(current.trim())
            current = ''
        } else {
            current += ch
        }
    }
    result.push(current.trim())
    return result
}

function ReauthModal({ storeName, onClose, onSubmit }) {
    const [clientId, setClientId] = useState('')
    const [clientSecret, setClientSecret] = useState('')
    const [loading, setLoading] = useState(false)

    async function handleSubmit() {
        if (!clientId || !clientSecret) return
        setLoading(true)
        await onSubmit(clientId.trim(), clientSecret.trim())
        setLoading(false)
    }

    return (
        <div style={{
            position: 'fixed', inset: 0, background: '#000000cc',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 1000, backdropFilter: 'blur(2px)'
        }}>
            <div style={{
                background: '#0e0e0e', border: '1px solid #ef444455',
                borderRadius: 4, padding: 24, width: 400,
                display: 'flex', flexDirection: 'column', gap: 16,
                fontFamily: "'IBM Plex Mono', monospace"
            }}>
                <div style={{ fontSize: 12, fontWeight: 600, letterSpacing: '0.2em', color: '#ef4444', borderBottom: '1px solid #1e1e1e', paddingBottom: 12 }}>
                    ⚠ CREDENTIALS EXPIRED
                </div>
                <div style={{ fontSize: 11, color: '#888' }}>
                    The credentials for <span style={{ color: '#e2e2e2' }}>{storeName}</span> are expired or invalid.
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <label style={{ fontSize: 10, letterSpacing: '0.12em', color: '#555' }}>CLIENT ID</label>
                    <input autoFocus type="text" placeholder="Enter client ID" value={clientId}
                        onChange={e => setClientId(e.target.value)}
                        style={{ background: '#141414', border: '1px solid #ef444433', borderRadius: 3, padding: '8px 10px', color: '#e2e2e2', fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, outline: 'none', width: '100%' }}
                    />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <label style={{ fontSize: 10, letterSpacing: '0.12em', color: '#555' }}>CLIENT SECRET</label>
                    <input type="password" placeholder="Enter client secret" value={clientSecret}
                        onChange={e => setClientSecret(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleSubmit()}
                        style={{ background: '#141414', border: '1px solid #ef444433', borderRadius: 3, padding: '8px 10px', color: '#e2e2e2', fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, outline: 'none', width: '100%' }}
                    />
                </div>
                <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                    <button onClick={onClose} style={{ background: 'none', border: '1px solid #2a2a2a', borderRadius: 3, padding: '6px 16px', color: '#555', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, cursor: 'pointer' }}>CANCEL</button>
                    <button onClick={handleSubmit} disabled={loading || !clientId || !clientSecret}
                        style={{ background: '#2b0d0d', border: '1px solid #ef444455', borderRadius: 3, padding: '6px 16px', color: '#ef4444', fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 600, cursor: 'pointer', opacity: (!clientId || !clientSecret || loading) ? 0.4 : 1 }}>
                        {loading ? 'SAVING...' : 'UPDATE'}
                    </button>
                </div>
            </div>
        </div>
    )
}

export default function Products() {
    const { selectedStore } = useOutletContext()

    const [rows, setRows] = useState([])
    const [isFetching, setIsFetching] = useState(false)
    const [isSyncing, setIsSyncing] = useState(false)
    const [syncState, setSyncState] = useState(null)
    const [showRollback, setShowRollback] = useState(false)
    const [rollbackChangedIndices, setRollbackChangedIndices] = useState(null)
    const [loadKey, setLoadKey] = useState(0)
    const [metafieldDefs, setMetafieldDefs] = useState({ product: {}, variant: {} })
    const [metafieldOwners, setMetafieldOwners] = useState({})
    const [fieldSchema, setFieldSchema] = useState({ enums: {}, validations: {} })
    const [collectionHandles, setCollectionHandles] = useState([])
    const [activeView, setActiveView] = useState('excel')
    const [fetchMsg, setFetchMsg] = useState('')
    const [showReauth, setShowReauth] = useState(false)

    // Auto-load products when store changes
    useEffect(() => {
        if (!selectedStore) return
        let cancelled = false
        getProducts(selectedStore.store_name)
            .then(newRows => {
                if (cancelled) return
                if (newRows.length > 0) {
                    setRows(newRows)
                    setSyncState(null)
                    setRollbackChangedIndices(null)
                    setLoadKey(k => k + 1)
                    setFetchMsg(`${newRows.length} rows loaded`)
                }
            })
            .catch(() => { })
        return () => { cancelled = true }
    }, [selectedStore?.store_name])

    // Load metafield defs when store or rows change
    useEffect(() => {
        if (!selectedStore?.store_name) return
        let cancelled = false
        Promise.all([
            getMetafieldDefs(selectedStore.store_name),
            getMetafieldOwners(selectedStore.store_name),
            getFieldSchema(selectedStore.store_name),
            getCollectionHandles(selectedStore.store_name),
        ])
            .then(([defs, owners, schema, colHandles]) => {
                if (cancelled) return
                setMetafieldDefs(defs || { product: {}, variant: {} })
                setMetafieldOwners(owners || {})
                setFieldSchema(schema || { enums: {}, validations: {} })
                setCollectionHandles(colHandles?.handles || [])
            })
            .catch(err => {
                if (cancelled) return
                console.warn('[MetafieldMeta] Could not load:', err)
                setMetafieldDefs({ product: {}, variant: {} })
                setMetafieldOwners({})
                setFieldSchema({ enums: {}, validations: {} })
                setCollectionHandles([])
            })
        return () => { cancelled = true }
    }, [selectedStore?.store_name, loadKey])

    const handleRowsLoaded = useCallback((newRows) => {
        setRows(newRows)
        setSyncState(null)
        setRollbackChangedIndices(null)
        setLoadKey(k => k + 1)
    }, [])

    const handleSyncSummary = useCallback((summary) => {
        setSyncState(prev => ({ ...prev, summary }))
        setIsSyncing(false)
    }, [])

    const handleRollbackApply = useCallback((rollbackRows, changedIndices) => {
        setRows(rollbackRows)
        setSyncState(null)
        setRollbackChangedIndices(new Set(changedIndices))
    }, [])

    async function handleFetch() {
        if (!selectedStore || isFetching) return
        setIsFetching(true)
        setFetchMsg('Starting bulk export...')
        try {
            await triggerFetch(selectedStore.store_name)
            const newRows = await getProducts(selectedStore.store_name)
            handleRowsLoaded(newRows)
            setFetchMsg(`${newRows.length} rows loaded`)
        } catch (e) {
            if (e.message && (e.message.includes('401') || e.message.includes('Unauthorized'))) {
                setFetchMsg('Credentials expired')
                setShowReauth(true)
            } else {
                setFetchMsg('Fetch failed — check console')
                console.error(e)
            }
        } finally {
            setIsFetching(false)
        }
    }

    async function handleRefresh() {
        if (!selectedStore || isFetching || isSyncing) return
        setFetchMsg('Loading local data...')
        try {
            const newRows = await getProducts(selectedStore.store_name)
            // Clear Sync Status so row colors reset
            const cleanRows = newRows.map(r => ({ ...r, 'Sync Status': '' }))
            handleRowsLoaded(cleanRows)
            setFetchMsg(`${cleanRows.length} rows loaded from local CSV`)
        } catch {
            setFetchMsg('No local data — click FETCH first')
        }
    }

    async function handleSync() {
        if (!selectedStore || isSyncing || rows.length === 0) return
        setSyncState({ results: {} })
        setRollbackChangedIndices(null)
        setIsSyncing(true)
        setFetchMsg('Saving changes...')
        try {
            await saveProducts(selectedStore.store_name, rows)
        } catch (e) {
            setFetchMsg('Save failed — cannot sync: ',e)
            setIsSyncing(false)
            return
        }
        setFetchMsg('Syncing...')
        const startTime = Date.now()
        try {
            const result = await startSync(selectedStore.store_name)
            const duration_seconds = Math.round((Date.now() - startTime) / 1000)
            handleSyncSummary({ done: true, ...result, duration_seconds })
            setFetchMsg(`Done — ${result.updated} updated, ${result.skipped} skipped, ${result.errors} errors`)
            
        } catch (e) {
            setFetchMsg('Sync failed — check console')
            const duration_seconds = Math.round((Date.now() - startTime) / 1000)
            console.error(e)
            handleSyncSummary({ done: true, total: rows.length, updated: 0, created: 0, skipped: 0, deleted: 0, errors: 0, conflicts: 0, duration_seconds })
        } finally {
            setIsSyncing(false)
        }
    }

    function handleExportCSV() {
        if (rows.length === 0) return
        const headers = Object.keys(rows[0])
        const escape = val => {
            const s = val == null ? '' : String(val)
            return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s
        }
        const csv = [headers.join(','), ...rows.map(row => headers.map(h => escape(row[h])).join(','))].join('\n')
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${selectedStore.store_name}_products.csv`
        a.click()
        URL.revokeObjectURL(url)
        setFetchMsg(`Exported ${rows.length} rows as CSV`)
    }

    async function handleExportExcel() {
        if (rows.length === 0) return
        try {
            const ExcelJS = (await import('exceljs')).default
            const wb = new ExcelJS.Workbook()
            const ws = wb.addWorksheet('Products')
            const headers = Object.keys(rows[0])
            ws.addRow(headers)
            rows.forEach(row => ws.addRow(headers.map(h => row[h] ?? '')))
            const buffer = await wb.xlsx.writeBuffer()
            const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `${selectedStore.store_name}_products.xlsx`
            a.click()
            URL.revokeObjectURL(url)
            setFetchMsg(`Exported ${rows.length} rows as Excel`)
        } catch (err) {
            console.error(err)
            setFetchMsg('Excel export failed')
        }
    }

    async function handleImport(e) {
        const file = e.target.files?.[0]
        if (!file) return
        e.target.value = ''
        const ext = file.name.split('.').pop().toLowerCase()
        setFetchMsg('Importing...')
        try {
            let importedRows = []
            if (ext === 'csv') {
                const text = await file.text()
                const lines = text.split('\n').filter(l => l.trim())
                const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''))
                importedRows = lines.slice(1).map(line => {
                    const vals = parseCSVLine(line)
                    const row = {}
                    headers.forEach((h, i) => { row[h] = vals[i] ?? '' })
                    return row
                })
            } else if (ext === 'xlsx' || ext === 'xls') {
                const ExcelJS = (await import('exceljs')).default
                const buffer = await file.arrayBuffer()
                const wb = new ExcelJS.Workbook()
                await wb.xlsx.load(buffer)
                const ws = wb.worksheets[0]
                const headers = ws.getRow(1).values.slice(1)
                ws.eachRow((row, rowNum) => {
                    if (rowNum === 1) return
                    const obj = {}
                    headers.forEach((h, i) => { obj[h] = row.values[i + 1] ?? '' })
                    importedRows.push(obj)
                })
            } else {
                setFetchMsg('Unsupported file type')
                return
            }
            if (importedRows.length === 0) { setFetchMsg('File is empty'); return }
            handleRowsLoaded(importedRows)
            setFetchMsg(`Imported ${importedRows.length} rows — review and click SYNC`)
        } catch (err) {
            console.error(err)
            setFetchMsg('Import failed — check file format')
        }
    }

    async function handleReauth(clientId, clientSecret) {
        try {
            await addStore(selectedStore.domain, clientId, clientSecret)
            setShowReauth(false)
            setFetchMsg('Credentials updated — try again')
        } catch (e) {
            console.error(e)
        }
    }

    return (
        <div className={styles.page}>
            {showReauth && (
                <ReauthModal
                    storeName={selectedStore?.store_name}
                    onClose={() => setShowReauth(false)}
                    onSubmit={handleReauth}
                />
            )}

            {/* Page toolbar */}
            <div className={styles.toolbar}>
                <span className={styles.pageTitle}>PRODUCTS</span>

                <div className={styles.divider} />

                <button className={`${styles.btn} ${isFetching ? styles.btnActive : ''}`}
                    onClick={handleFetch} disabled={!selectedStore || isFetching || isSyncing}>
                    {isFetching ? <><span className={styles.spinner} /> FETCHING</> : <>↓ FETCH</>}
                </button>

                <button className={styles.btn} onClick={handleRefresh}
                    disabled={!selectedStore || isFetching || isSyncing} title="Reload from local CSV">
                    ↺ RELOAD
                </button>

                <button className={`${styles.btn} ${styles.btnSync} ${isSyncing ? styles.btnActive : ''}`}
                    onClick={handleSync} disabled={!selectedStore || isSyncing || isFetching || rows.length === 0}>
                    {isSyncing ? <><span className={styles.spinner} /> SYNCING</> : <>⇅ SYNC</>}
                </button>

                <button className={styles.btn} onClick={() => setShowRollback(true)}
                    disabled={!selectedStore || isFetching || isSyncing}>
                    ↩ ROLLBACK
                </button>

                <div className={styles.divider} />

                <div className={styles.viewToggle}>
                    <button className={`${styles.viewBtn} ${activeView === 'excel' ? styles.viewBtnActive : ''}`}
                        onClick={() => setActiveView('excel')}>⊞ EXCEL</button>
                    <button className={`${styles.viewBtn} ${activeView === 'shopify' ? styles.viewBtnActive : ''}`}
                        onClick={() => setActiveView('shopify')}>◈ SHOPIFY</button>
                </div>

                <div className={styles.divider} />

                <button className={styles.btn} onClick={handleExportCSV} disabled={rows.length === 0}>↑ CSV</button>
                <button className={styles.btn} onClick={handleExportExcel} disabled={rows.length === 0}>↑ EXCEL</button>

                <label className={styles.btn} style={{ cursor: 'pointer' }}>
                    ↓ IMPORT
                    <input type="file" accept=".csv,.xlsx,.xls" style={{ display: 'none' }} onChange={handleImport} />
                </label>

                <div className={styles.spacer} />

                {fetchMsg && <span className={styles.statusMsg}>{fetchMsg}</span>}
                {rows.length > 0 && (
                    <div className={styles.rowCount}>
                        <span className={styles.rowCountNum}>{rows.length}</span>
                        <span className={styles.rowCountLabel}>ROWS</span>
                    </div>
                )}
            </div>

            <SyncProgress syncState={syncState} totalRows={rows.length} />

            <div className={styles.content}>
                {activeView === 'excel' ? (
                    <ProductGrid
                        rows={rows}
                        setRows={setRows}
                        syncState={syncState}
                        isSyncing={isSyncing}
                        selectedStore={selectedStore}
                        rollbackChangedIndices={rollbackChangedIndices}
                        loadKey={loadKey}
                        metafieldDefs={metafieldDefs}
                        metafieldOwners={metafieldOwners}
                        fieldSchema={fieldSchema}
                        storeCollectionHandles={collectionHandles}
                    />
                ) : (
                    <ShopifyView
                        rows={rows}
                        setRows={setRows}
                        selectedStore={selectedStore}
                        isSyncing={isSyncing}
                        setIsSyncing={setIsSyncing}
                        fieldSchema={fieldSchema}
                        storeCollectionHandles={collectionHandles}
                        metafieldDefs={metafieldDefs}
                        metafieldOwners={metafieldOwners}
                        onReload={handleRowsLoaded}
                    />
                )}
            </div>

            {showRollback && (
                <RollbackPanel
                    store={selectedStore}
                    onClose={() => setShowRollback(false)}
                    onApply={handleRollbackApply}
                />
            )}
        </div>
    )
}