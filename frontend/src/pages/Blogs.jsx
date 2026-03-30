import { useState, useCallback, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import {
    fetchArticles, getArticles, saveArticles, syncArticles, getBlogList
} from '../api'
import ExcelGrid from '../components/ExcelGrid'
import ArticleCardView from '../components/ArticleCardView'
import styles from './Blogs.module.css'

function parseCSVLine(line) {
    const result = []
    let current = '', inQuotes = false
    for (let i = 0; i < line.length; i++) {
        const ch = line[i]
        if (ch === '"') {
            if (inQuotes && line[i + 1] === '"') { current += '"'; i++ }
            else inQuotes = !inQuotes
        } else if (ch === ',' && !inQuotes) {
            result.push(current.trim()); current = ''
        } else { current += ch }
    }
    result.push(current.trim())
    return result
}

const READ_ONLY_COLS = ['Article ID', 'Blog ID', 'Created At', 'Updated At', 'Sync Status']

export default function Blogs() {
    const { selectedStore } = useOutletContext()
    const [rows, setRows] = useState([])
    const [blogs, setBlogs] = useState([])
    const [selectedBlog, setSelectedBlog] = useState('')
    const [activeView, setActiveView] = useState('excel')
    const [isFetching, setIsFetching] = useState(false)
    const [isSyncing, setIsSyncing] = useState(false)
    const [msg, setMsg] = useState('')
    const [search, setSearch] = useState('')
    const [openArticle, setOpenArticle] = useState(null)

    useEffect(() => {
        if (!selectedStore?.store_name) { setRows([]); setBlogs([]); return }
        let cancelled = false
        getArticles(selectedStore.store_name)
            .then(data => {
                if (cancelled) return
                setRows(Array.isArray(data) ? data : [])
                setMsg(data.length ? `${data.length} articles loaded` : '')
            })
            .catch(() => { })
        getBlogList(selectedStore.store_name)
            .then(data => { if (!cancelled) setBlogs(data.blogs || []) })
            .catch(() => { })
        return () => { cancelled = true }
    }, [selectedStore?.store_name])

    const handleFetch = useCallback(async () => {
        if (!selectedStore || isFetching) return
        setIsFetching(true)
        setMsg('Fetching articles...')
        try {
            await fetchArticles(selectedStore.store_name)
            const data = await getArticles(selectedStore.store_name)
            const blogData = await getBlogList(selectedStore.store_name)
            setRows(Array.isArray(data) ? data : [])
            setBlogs(blogData.blogs || [])
            setMsg(`${data.length} articles loaded`)
        } catch (e) {
            setMsg('Fetch failed — check console')
            console.error(e)
        } finally {
            setIsFetching(false)
        }
    }, [selectedStore, isFetching])

    const handleRefresh = useCallback(async () => {
        if (!selectedStore) return
        try {
            const data = await getArticles(selectedStore.store_name)
            const cleanRows = (Array.isArray(data) ? data : []).map(r => ({ ...r, 'Sync Status': '' }))
            setRows(cleanRows)
            setMsg(`${cleanRows.length} articles loaded`)
        } catch {
            setMsg('No local data — click FETCH first')
        }
    }, [selectedStore])

    const handleSync = useCallback(async () => {
        if (!selectedStore || isSyncing || rows.length === 0) return
        setIsSyncing(true)
        setMsg('Saving...')
        try {
            await saveArticles(selectedStore.store_name, rows)
        } catch {
            setMsg('Save failed')
            setIsSyncing(false)
            return
        }
        setMsg('Syncing...')
        try {
            const result = await syncArticles(selectedStore.store_name)
            setMsg(`Done — ${result.updated} updated, ${result.skipped} skipped, ${result.errors} errors`)
            const fresh = await getArticles(selectedStore.store_name)
            setRows(Array.isArray(fresh) ? fresh : [])
        } catch (e) {
            setMsg('Sync failed — check console')
            console.error(e)
        } finally {
            setIsSyncing(false)
        }
    }, [selectedStore, isSyncing, rows])

    function handleExportCSV() {
        if (!rows.length) return
        const headers = Object.keys(rows[0])
        const escape = v => {
            const s = v == null ? '' : String(v)
            return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s
        }
        const csv = [headers.join(','), ...rows.map(r => headers.map(h => escape(r[h])).join(','))].join('\n')
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = `${selectedStore.store_name}_articles.csv`; a.click()
        URL.revokeObjectURL(url)
    }

    async function handleExportExcel() {
        if (!rows.length) return
        try {
            const ExcelJS = (await import('exceljs')).default
            const wb = new ExcelJS.Workbook()
            const ws = wb.addWorksheet('Articles')
            const headers = Object.keys(rows[0])
            ws.addRow(headers)
            rows.forEach(row => ws.addRow(headers.map(h => row[h] ?? '')))
            const buffer = await wb.xlsx.writeBuffer()
            const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `${selectedStore.store_name}_articles.xlsx`
            a.click()
            URL.revokeObjectURL(url)
            setMsg(`Exported ${rows.length} rows as Excel`)
        } catch (err) {
            console.error(err)
            setMsg('Excel export failed')
        }
    }

    async function handleImport(e) {
        const file = e.target.files?.[0]
        if (!file) return
        e.target.value = ''
        const ext = file.name.split('.').pop().toLowerCase()
        setMsg('Importing...')
        try {
            let imported = []
            if (ext === 'csv') {
                const text = await file.text()
                const lines = text.split('\n').filter(l => l.trim())
                const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''))
                imported = lines.slice(1).map(line => {
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
                    imported.push(obj)
                })
            } else {
                setMsg('Unsupported file type')
                return
            }
            if (!imported.length) { setMsg('File is empty'); return }
            setRows(imported)
            setMsg(`Imported ${imported.length} rows`)
        } catch {
            setMsg('Import failed — check file format')
        }
    }

    function addNewArticle() {
        if (!rows.length) return
        const blank = Object.fromEntries(Object.keys(rows[0]).map(k => [k, '']))
        setOpenArticle({ ...blank, 'Blog ID': selectedBlog || blogs[0]?.['Blog ID'] || '' })
    }

    const filtered = rows.filter(r => {
        const matchBlog = !selectedBlog || r['Blog ID'] === selectedBlog
        const q = search.toLowerCase()
        const matchSearch = !q ||
            String(r['Title'] || '').toLowerCase().includes(q) ||
            String(r['Author'] || '').toLowerCase().includes(q) ||
            String(r['Tags'] || '').toLowerCase().includes(q) ||
            String(r['Blog Title'] || '').toLowerCase().includes(q)
        return matchBlog && matchSearch
    })

    // Map filtered edits back to full rows by Article ID
    const setFilteredRows = useCallback((updater) => {
        setRows(prev => {
            const updated = typeof updater === 'function' ? updater(filtered) : updater

            // Build a map of existing rows by Article ID or Title
            const updatedMap = new Map()
            const newRows = []

            updated.forEach(r => {
                const key = r['Article ID'] || r['Title']
                if (key) {
                    updatedMap.set(key, r)
                } else {
                    newRows.push(r)  // blank rows — collect separately
                }
            })

            // Update existing rows
            const merged = prev.map(r => {
                const key = r['Article ID'] || r['Title']
                return updatedMap.has(key) ? updatedMap.get(key) : r
            })

            // Append blank new rows at the end
            return [...merged, ...newRows]
        })
    }, [filtered])

    return (
        <div className={styles.page}>
            {/* Toolbar */}
            <div className={styles.toolbar}>
                <span className={styles.pageTitle}>BLOGS</span>
                <div className={styles.divider} />

                <button className={`${styles.btn} ${isFetching ? styles.btnActive : ''}`}
                    onClick={handleFetch} disabled={!selectedStore || isFetching || isSyncing}>
                    {isFetching ? <><span className={styles.spinner} /> FETCHING</> : <>↓ FETCH</>}
                </button>

                <button className={styles.btn} onClick={handleRefresh}
                    disabled={!selectedStore || isFetching || isSyncing}>
                    ↺ RELOAD
                </button>

                <button className={`${styles.btn} ${styles.btnSync} ${isSyncing ? styles.btnActive : ''}`}
                    onClick={handleSync} disabled={!selectedStore || isSyncing || isFetching || rows.length === 0}>
                    {isSyncing ? <><span className={styles.spinner} /> SYNCING</> : <>⇅ SYNC</>}
                </button>

                <div className={styles.divider} />

                <div className={styles.viewToggle}>
                    <button className={`${styles.viewBtn} ${activeView === 'excel' ? styles.viewBtnActive : ''}`}
                        onClick={() => setActiveView('excel')}>⊞ EXCEL</button>
                    <button className={`${styles.viewBtn} ${activeView === 'cards' ? styles.viewBtnActive : ''}`}
                        onClick={() => setActiveView('cards')}>◈ CARDS</button>
                </div>

                <div className={styles.divider} />

                <button className={styles.btn} onClick={handleExportCSV} disabled={!rows.length}>↑ CSV</button>
                <button className={styles.btn} onClick={handleExportExcel} disabled={!rows.length}>↑ EXCEL</button>
                <label className={styles.btn} style={{ cursor: 'pointer' }}>
                    ↓ IMPORT
                    <input type="file" accept=".csv,.xlsx,.xls" style={{ display: 'none' }} onChange={handleImport} />
                </label>

                <div className={styles.spacer} />
                {msg && <span className={styles.statusMsg}>{msg}</span>}
                {rows.length > 0 && (
                    <div className={styles.rowCount}>
                        <span className={styles.rowCountNum}>{rows.length}</span>
                        <span className={styles.rowCountLabel}>ARTICLES</span>
                    </div>
                )}
            </div>

            {/* Sub-toolbar */}
            {rows.length > 0 && (
                <div className={styles.subToolbar}>
                    <select className={styles.blogSelect} value={selectedBlog}
                        onChange={e => setSelectedBlog(e.target.value)}>
                        <option value="">All blogs ({rows.length})</option>
                        {blogs.map(b => (
                            <option key={b['Blog ID']} value={b['Blog ID']}>
                                {b['Blog Title']} ({rows.filter(r => r['Blog ID'] === b['Blog ID']).length})
                            </option>
                        ))}
                    </select>
                    <input className={styles.search} placeholder="Search title, author, tags…"
                        value={search} onChange={e => setSearch(e.target.value)} />
                    <button className={styles.addBtn} onClick={addNewArticle}
                        disabled={!rows.length || isSyncing}>+ New Article</button>
                    <span className={styles.filterCount}>{filtered.length} articles</span>
                </div>
            )}

            {/* Content */}
            <div className={styles.content}>
                {!selectedStore && <div className={styles.empty}>Select a store to view blogs</div>}
                {selectedStore && rows.length === 0 && !isFetching && (
                    <div className={styles.empty}>No data — click FETCH to pull articles from Shopify</div>
                )}

                {rows.length > 0 && activeView === 'excel' && (
                    <ExcelGrid
                        rows={filtered}
                        setRows={setFilteredRows}
                        readOnlyCols={READ_ONLY_COLS}
                        dropdownCols={{
                            'Status': ['', 'published', 'draft'],
                            'Delete': ['', 'YES'],
                            'Blog Title': ['', ...blogs.map(b => b['Blog Title'])],
                        }}
                        isSyncing={isSyncing}
                        selectedStore={selectedStore}
                        loadKey={rows.length}
                    />
                )}

                {rows.length > 0 && activeView === 'cards' && (
                    <ArticleCardView
                        rows={filtered}
                        onCardClick={setOpenArticle}
                    />
                )}
            </div>

            {/* Article modal */}
            {openArticle && (
                <ArticleModal
                    article={openArticle}
                    blogs={blogs}
                    onClose={() => setOpenArticle(null)}
                    onSave={(updated) => {
                        setRows(prev => {
                            const id = updated['Article ID']
                            if (!id) return [...prev, updated]
                            const idx = prev.findIndex(r => r['Article ID'] === id)
                            if (idx === -1) return [...prev, updated]
                            const next = [...prev]
                            next[idx] = updated
                            return next
                        })
                        setOpenArticle(null)
                    }}
                />
            )}
        </div>
    )
}

function ArticleModal({ article, blogs, onClose, onSave }) {
    const [form, setForm] = useState({ ...article })
    const set = (key, val) => setForm(prev => ({ ...prev, [key]: val }))

    return (
        <div className={styles.modalOverlay} onClick={onClose}>
            <div className={styles.modal} onClick={e => e.stopPropagation()}>
                <div className={styles.modalHeader}>
                    <span className={styles.modalTitle}>{form['Article ID'] ? 'Edit Article' : 'New Article'}</span>
                    <button className={styles.modalClose} onClick={onClose}>✕</button>
                </div>

                <div className={styles.modalBody}>
                    <div className={styles.modalField}>
                        <label>Blog</label>
                        <select value={form['Blog ID'] || ''} onChange={e => set('Blog ID', e.target.value)}>
                            <option value="">— select blog —</option>
                            {blogs.map(b => <option key={b['Blog ID']} value={b['Blog ID']}>{b['Blog Title']}</option>)}
                        </select>
                    </div>

                    {['Title', 'Handle', 'Author', 'Tags', 'Image URL', 'Image Alt', 'SEO Title', 'SEO Description'].map(key => (
                        <div key={key} className={styles.modalField}>
                            <label>{key}</label>
                            <input value={String(form[key] ?? '')} onChange={e => set(key, e.target.value)} />
                        </div>
                    ))}

                    <div className={styles.modalField}>
                        <label>Status</label>
                        <select value={form['Status'] || 'draft'} onChange={e => set('Status', e.target.value)}>
                            <option value="published">Published</option>
                            <option value="draft">Draft</option>
                        </select>
                    </div>

                    <div className={styles.modalField}>
                        <label>Body (HTML)</label>
                        <textarea rows={8} value={String(form['Body (HTML)'] ?? '')}
                            onChange={e => set('Body (HTML)', e.target.value)} />
                    </div>

                    <div className={styles.modalField}>
                        <label>Summary (HTML)</label>
                        <textarea rows={4} value={String(form['Summary (HTML)'] ?? '')}
                            onChange={e => set('Summary (HTML)', e.target.value)} />
                    </div>

                    <div className={styles.modalField}>
                        <label>Delete</label>
                        <select value={form['Delete'] || ''} onChange={e => set('Delete', e.target.value)}>
                            <option value="">—</option>
                            <option value="YES">YES</option>
                        </select>
                    </div>
                </div>

                <div className={styles.modalFooter}>
                    <button className={styles.cancelBtn} onClick={onClose}>CANCEL</button>
                    <button className={styles.saveBtn} onClick={() => onSave(form)}>SAVE TO GRID</button>
                </div>
            </div>
        </div>
    )
}