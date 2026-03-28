import { useState, useEffect, useRef } from 'react'
import { getStores, triggerFetch, getProducts, saveProducts, startSync, addStore } from '../api'
import styles from './Header.module.css'

export default function Header({
    selectedStore, onStoreSelect, onRowsLoaded, onAddStore, onRollback,
    isFetching, setIsFetching, isSyncing, setIsSyncing,
    rows, onSyncSummary, onSyncStart, storesRefreshKey, activeView, onViewChange
}) {
    const [stores, setStores] = useState([])
    const [fetchMsg, setFetchMsg] = useState('')
    const [showReauth, setShowReauth] = useState(false)
    const [showExportMenu, setShowExportMenu] = useState(false)
    const exportMenuRef = useRef(null)
    const importInputRef = useRef(null)

    // Load stores list, restore previously selected store (or fall back to first)
    useEffect(() => {
        let cancelled = false
        getStores()
            .then(async list => {
                if (cancelled) return
                setStores(list)
                if (list.length === 0) return
                const savedName = localStorage.getItem('selectedStore')
                const match = savedName && list.find(s => s.store_name === savedName)
                onStoreSelect(match || list[0])
            })
            .catch(e => console.error('Failed to load stores', e))
        return () => { cancelled = true }
    }, [storesRefreshKey])

    // Auto-load products when user manually changes store
    useEffect(() => {
        if (!selectedStore) return
        let cancelled = false
        getProducts(selectedStore.store_name)
            .then(newRows => {
                if (cancelled) return
                if (newRows.length > 0) {
                    onRowsLoaded(newRows)
                    setFetchMsg(`${newRows.length} rows loaded`)
                }
            })
            .catch(() => { })
        return () => { cancelled = true }
    }, [selectedStore?.store_name])

    // ── Fetch flow ────────────────────────────────────────────────────────────
    async function handleFetch() {
        if (!selectedStore || isFetching) return
        setIsFetching(true)
        setFetchMsg('Starting bulk export...')
        try {
            await triggerFetch(selectedStore.store_name)
            const newRows = await getProducts(selectedStore.store_name)
            onRowsLoaded(newRows)
            setFetchMsg(`${newRows.length} rows loaded`)
        } catch (e) {
            // Detect 401 / token expired
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

    // ── Refresh flow — reloads local products_master.csv, NO Shopify API call
    async function handleRefresh() {
        if (!selectedStore || isFetching || isSyncing) return
        setFetchMsg('Loading local data...')
        try {
            const newRows = await getProducts(selectedStore.store_name)
            onRowsLoaded(newRows)
            setFetchMsg(`${newRows.length} rows loaded from local CSV`)
        } catch {
            setFetchMsg('No local data — click FETCH first')
        }
    }

    // ── Sync flow ─────────────────────────────────────────────────────────────
    async function handleSync() {
        if (!selectedStore || isSyncing || rows.length === 0) return
        onSyncStart()
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
            onSyncSummary({ done: true, ...result, duration_seconds })
            setFetchMsg(`Done — ${result.updated} updated, ${result.skipped} skipped, ${result.errors} errors`)
        } catch (e) {
            setFetchMsg('Sync failed — check console')
            const duration_seconds = Math.round((Date.now() - startTime) / 1000)
            console.error(e)
            onSyncSummary({ done: true, total: rows.length, updated: 0, created: 0, skipped: 0, deleted: 0, errors: 0, conflicts: 0, duration_seconds})
        } finally {
            setIsSyncing(false)
        }
    }

    // ── Export CSV ────────────────────────────────────────────────────────────
    function handleExportCSV() {
        if (rows.length === 0) return
        setShowExportMenu(false)
        const headers = Object.keys(rows[0])
        const escape = val => {
            const s = val == null ? '' : String(val)
            return s.includes(',') || s.includes('"') || s.includes('\n')
                ? `"${s.replace(/"/g, '""')}"`
                : s
        }
        const csv = [
            headers.join(','),
            ...rows.map(row => headers.map(h => escape(row[h])).join(','))
        ].join('\n')
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${selectedStore.store_name}_products.csv`
        a.click()
        URL.revokeObjectURL(url)
        setFetchMsg(`Exported ${rows.length} rows as CSV`)
    }


    // ── Export Excel ──────────────────────────────────────────────────────────
    async function handleExportExcel() {
        if (rows.length === 0) return
        setShowExportMenu(false)
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
            setFetchMsg('Excel export failed — check console')
        }
    }

    // ── Import CSV/Excel ──────────────────────────────────────────────────────
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
                setFetchMsg('Unsupported file type — use CSV or Excel')
                return
            }

            if (importedRows.length === 0) {
                setFetchMsg('File is empty')
                return
            }

            onRowsLoaded(importedRows)
            setFetchMsg(`Imported ${importedRows.length} rows — review and click SYNC`)
        } catch (err) {
            console.error('Import error:', err)
            setFetchMsg('Import failed — check file format')
        }
    }

    // Parse a single CSV line respecting quoted fields
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

    const selectedName = selectedStore?.store_name ?? ''

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
        <>
            {showReauth && (
                <ReauthModal
                    storeName={selectedStore?.store_name}
                    onClose={() => setShowReauth(false)}
                    onSubmit={handleReauth}
                />
            )}
            <header className={styles.header}>
                {/* Logo / Brand */}
                <div className={styles.brand}>
                    <span className={styles.brandDot} />
                    <span className={styles.brandText}>SYNC</span>
                </div>

                <div className={styles.divider} />

                {/* Store selector */}
                <div className={styles.storeSection}>
                    <span className={styles.label}>STORE</span>
                    <select
                        className={styles.select}
                        value={selectedName}
                        onChange={e => {
                            const s = stores.find(s => s.store_name === e.target.value)
                            onStoreSelect(s ?? null)
                        }}
                    >
                        <option value="">— select store —</option>
                        {stores.map(s => (
                            <option key={s.store_name} value={s.store_name}>
                                {s.store_name}
                                {s.variant_count > 0 ? ` (${s.variant_count} variants)` : ''}
                            </option>
                        ))}
                    </select>
                    <button className={styles.addBtn} onClick={onAddStore} title="Add store">+</button>
                </div>

                <div className={styles.divider} />

                {/* Fetch button */}
                <button
                    className={`${styles.btn} ${isFetching ? styles.btnActive : ''}`}
                    onClick={handleFetch}
                    disabled={!selectedStore || isFetching || isSyncing}
                >
                    {isFetching ? (
                        <><span className={styles.spinner} /> FETCHING</>
                    ) : (
                        <><span className={styles.icon}>↓</span> FETCH</>
                    )}
                </button>

                {/* Refresh button */}
                <button
                    className={styles.btn}
                    onClick={handleRefresh}
                    disabled={!selectedStore || isFetching || isSyncing}
                    title="Reload from local CSV (no Shopify call)"
                >
                    <span className={styles.icon}>↺</span> RELOAD
                </button>

                {/* Sync button */}
                <button
                    className={`${styles.btn} ${styles.btnSync} ${isSyncing ? styles.btnActive : ''}`}
                    onClick={handleSync}
                    disabled={!selectedStore || isSyncing || isFetching || rows.length === 0}
                >
                    {isSyncing ? (
                        <><span className={styles.spinner} /> SYNCING</>
                    ) : (
                        <><span className={styles.icon}>⇅</span> SYNC</>
                    )}
                </button>

                {/* Rollback button */}
                <button
                    className={styles.btn}
                    onClick={onRollback}
                    disabled={!selectedStore || isFetching || isSyncing}
                    title="Load a previous snapshot into the grid"
                >
                    <span className={styles.icon}>↩</span> ROLLBACK
                </button>

                <div className={styles.divider} />

                {/* View toggle */}
                <div className={styles.viewToggle}>
                    <button
                        className={`${styles.viewBtn} ${activeView === 'excel' ? styles.viewBtnActive : ''}`}
                        onClick={() => onViewChange('excel')}
                        title="Excel View"
                    >
                        ⊞ EXCEL
                    </button>
                    <button
                        className={`${styles.viewBtn} ${activeView === 'shopify' ? styles.viewBtnActive : ''}`}
                        onClick={() => onViewChange('shopify')}
                        title="Shopify View"
                    >
                        ◈ SHOPIFY
                    </button>
                </div>

                <div className={styles.divider} />

                {/* Export dropdown */}
                <div className={styles.exportWrap} ref={exportMenuRef}>
                    <button
                        className={styles.btn}
                        onClick={() => setShowExportMenu(v => !v)}
                        disabled={!selectedStore || rows.length === 0}
                        title="Export grid data"
                    >
                        <span className={styles.icon}>↑</span> EXPORT
                        <span className={styles.caret}>▾</span>
                    </button>
                    {showExportMenu && (
                        <div className={styles.exportMenu}>
                            <button className={styles.exportMenuItem} onClick={handleExportCSV}>
                                <span>📄</span> Export as CSV
                            </button>
                            <button className={styles.exportMenuItem} onClick={handleExportExcel}>
                                <span>📊</span> Export as Excel
                            </button>
                        </div>
                    )}
                </div>

                {/* Import button */}
                <button
                    className={styles.btn}
                    onClick={() => importInputRef.current?.click()}
                    disabled={!selectedStore}
                    title="Import CSV or Excel file into grid"
                >
                    <span className={styles.icon}>↓</span> IMPORT
                </button>
                <input
                    ref={importInputRef}
                    type="file"
                    accept=".csv,.xlsx,.xls"
                    style={{ display: 'none' }}
                    onChange={handleImport}
                />

                {/* Status message */}
                <div className={styles.status}>
                    {fetchMsg && <span className={styles.statusMsg}>{fetchMsg}</span>}
                </div>

                {/* Row count */}
                {rows.length > 0 && (
                    <div className={styles.rowCount}>
                        <span className={styles.rowCountNum}>{rows.length}</span>
                        <span className={styles.rowCountLabel}>ROWS</span>
                    </div>
                )}
            </header>
        </>
    )
}

// ── Inline reauth modal ───────────────────────────────────────────────────
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
                <div style={{
                    fontSize: 12, fontWeight: 600, letterSpacing: '0.2em', color: '#ef4444',
                    borderBottom: '1px solid #1e1e1e', paddingBottom: 12
                }}>
                    ⚠ CREDENTIALS EXPIRED
                </div>
                <div style={{ fontSize: 11, color: '#888' }}>
                    The credentials for <span style={{ color: '#e2e2e2' }}>{storeName}</span> are
                    expired or invalid. Enter new credentials to continue.
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <label style={{ fontSize: 10, letterSpacing: '0.12em', color: '#555' }}>CLIENT ID</label>
                    <input
                        autoFocus
                        type="text"
                        placeholder="Enter client ID"
                        value={clientId}
                        onChange={e => setClientId(e.target.value)}
                        style={{
                            background: '#141414', border: '1px solid #ef444433',
                            borderRadius: 3, padding: '8px 10px', color: '#e2e2e2',
                            fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, outline: 'none', width: '100%'
                        }}
                    />
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <label style={{ fontSize: 10, letterSpacing: '0.12em', color: '#555' }}>CLIENT SECRET</label>
                    <input
                        type="password"
                        placeholder="Enter client secret"
                        value={clientSecret}
                        onChange={e => setClientSecret(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleSubmit()}
                        style={{
                            background: '#141414', border: '1px solid #ef444433',
                            borderRadius: 3, padding: '8px 10px', color: '#e2e2e2',
                            fontFamily: "'IBM Plex Mono', monospace", fontSize: 12, outline: 'none', width: '100%'
                        }}
                    />
                </div>
                <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                    <button onClick={onClose} style={{
                        background: 'none', border: '1px solid #2a2a2a', borderRadius: 3,
                        padding: '6px 16px', color: '#555', fontFamily: "'IBM Plex Mono', monospace",
                        fontSize: 11, cursor: 'pointer', letterSpacing: '0.1em'
                    }}>CANCEL</button>
                    <button onClick={handleSubmit} disabled={loading || !clientId || !clientSecret} style={{
                        background: '#2b0d0d', border: '1px solid #ef444455', borderRadius: 3,
                        padding: '6px 16px', color: '#ef4444', fontFamily: "'IBM Plex Mono', monospace",
                        fontSize: 11, fontWeight: 600, cursor: 'pointer', letterSpacing: '0.1em',
                        opacity: (!clientId || !clientSecret || loading) ? 0.4 : 1
                    }}>{loading ? 'SAVING...' : 'UPDATE'}</button>
                </div>
            </div>
        </div>
    )
}