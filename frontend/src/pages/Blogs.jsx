import { useState, useCallback, useEffect, useMemo } from 'react'
import { useOutletContext } from 'react-router-dom'
import { fetchArticles, getArticles, saveArticles, syncArticles, getBlogList, getBlogMetafieldDefs, refreshBlogMetafieldDefs, createBlog, getArticleMetafieldDefs } from '../api'
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

const READ_ONLY_COLS = ['Article ID', 'Blog ID', 'Blog Handle', 'Published At', 'Created At', 'Updated At', 'Sync Status']

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
    const [blogMetafieldDefs, setBlogMetafieldDefs] = useState({})
    const [articleMetafieldDefs, setArticleMetafieldDefs] = useState({})
    const [showNewBlog, setShowNewBlog] = useState(false)

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

        getBlogMetafieldDefs(selectedStore.store_name)
            .then(defs => { if (!cancelled) setBlogMetafieldDefs(defs) })
            .catch(() => { })
        getArticleMetafieldDefs(selectedStore.store_name)
            .then(defs => { if (!cancelled) setArticleMetafieldDefs(defs) })
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

    const authorOptions = ['', ...Array.from(new Set(rows.map(r => r['Author']).filter(a => a && a.trim())))]

    const blogLinkedCols = useMemo(() => ({
        'Blog Title': blogs.map(b => ({
            value: b['Blog Title'],
            set: {
                'Blog ID': b['Blog ID'],
                'Blog Handle': b['Blog Handle'],
            }
        }))
    }), [blogs])

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

    const validateCell = useCallback((key, value, rowData) => {
        const v = String(value ?? '').trim()
        const empty = !v || v.toLowerCase() === 'nan' || v.toLowerCase() === 'none'

        // Title is required on new rows (no Article ID)
        if (key === 'Title') {
            if (empty && !rowData?.['Article ID']) return 'Title is required'
        }

        // Image URL must be a valid URL if provided
        if (key === 'Image URL' && !empty) {
            if (!/^https?:\/\//i.test(v)) return 'Must be a valid URL (https://...)'
        }

        // SEO Title max length
        if (key === 'SEO Title' && !empty) {
            if (v.length > 70) return `Too long (${v.length}/70 chars)`
        }

        // SEO Description max length
        if (key === 'SEO Description' && !empty) {
            if (v.length > 320) return `Too long (${v.length}/320 chars)`
        }

        // Blog Title required on new rows
        if (key === 'Blog Title') {
            if (empty && !rowData?.['Article ID']) return 'Blog Title is required for new articles'
        }

        const defn = articleMetafieldDefs[key]
        if (defn && !empty) return validateMetafieldFrontend(key, v, defn)

        return null
    }, [articleMetafieldDefs])

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

                <div className={styles.divider} />
                <button className={styles.btn} onClick={() => setShowNewBlog(true)}
                    disabled={!selectedStore || isSyncing}>
                    + NEW BLOG
                </button>

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
                            'Author': authorOptions,
                        }}
                        isSyncing={isSyncing}
                        selectedStore={selectedStore}
                        loadKey={rows.length}
                        validateCell={validateCell}
                        metafieldDefs={articleMetafieldDefs}
                        linkedCols={blogLinkedCols}
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
                    authorOptions={authorOptions}
                    articleMetafieldDefs={articleMetafieldDefs}
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
            {showNewBlog && (
                <NewBlogModal
                    store={selectedStore}
                    metafieldDefs={blogMetafieldDefs}
                    onClose={() => setShowNewBlog(false)}
                    onCreated={(newBlog) => {
                        setShowNewBlog(false)
                        setMsg(`Blog "${newBlog.title}" created — click FETCH to reload`)
                    }}
                    onRefreshDefs={() =>
                        refreshBlogMetafieldDefs(selectedStore.store_name)
                            .then(setBlogMetafieldDefs)
                            .catch(() => { })
                    }
                />
            )}
        </div>
    )
}

function ArticleModal({ article, blogs, authorOptions = [], articleMetafieldDefs = {}, onClose, onSave }) {
    const [form, setForm] = useState({ ...article })
    const set = (key, val) => setForm(prev => ({ ...prev, [key]: val }))

    // Core fields to always show — order matters, nothing hardcoded beyond structure
    const READ_ONLY_IN_MODAL = new Set(['Article ID', 'Blog ID', 'Blog Handle', 'Published At', 'Created At', 'Updated At', 'Sync Status', 'Delete'])
    const TEXTAREA_FIELDS = new Set(['Body (HTML)', 'Summary (HTML)'])
    const SKIP_IN_MODAL = new Set(['Article ID', 'Blog ID', 'Blog Handle', 'Blog Title', 'Published At', 'Created At', 'Updated At', 'Sync Status', 'Delete', 'Status', 'Author'])

    // All keys from the article row that are not metafields and not skipped
    const coreKeys = Object.keys(form).filter(k =>
        !SKIP_IN_MODAL.has(k) && !Object.keys(articleMetafieldDefs).includes(k)
    )

    // Metafield keys present in this row
    const metaKeys = Object.keys(articleMetafieldDefs)

    return (
        <div className={styles.modalOverlay} onClick={onClose}>
            <div className={styles.modal} style={{ maxHeight: '90vh', overflowY: 'auto' }}
                onClick={e => e.stopPropagation()}>
                <div className={styles.modalHeader}>
                    <span className={styles.modalTitle}>{form['Article ID'] ? 'Edit Article' : 'New Article'}</span>
                    <button className={styles.modalClose} onClick={onClose}>✕</button>
                </div>

                <div className={styles.modalBody}>
                    {/* Blog selector */}
                    <div className={styles.modalField}>
                        <label>Blog</label>
                        <select value={form['Blog ID'] || ''} onChange={e => {
                            const blog = blogs.find(b => b['Blog ID'] === e.target.value)
                            setForm(prev => ({
                                ...prev,
                                'Blog ID': e.target.value,
                                'Blog Title': blog?.['Blog Title'] || '',
                                'Blog Handle': blog?.['Blog Handle'] || '',
                            }))
                        }}>
                            <option value="">— select blog —</option>
                            {blogs.map(b => <option key={b['Blog ID']} value={b['Blog ID']}>{b['Blog Title']}</option>)}
                        </select>
                    </div>

                    {/* Status */}
                    <div className={styles.modalField}>
                        <label>Status</label>
                        <select value={form['Status'] || 'draft'} onChange={e => set('Status', e.target.value)}>
                            <option value="published">Published</option>
                            <option value="draft">Draft</option>
                        </select>
                    </div>

                    {/* Author */}
                    <div className={styles.modalField}>
                        <label>Author</label>
                        <select value={String(form['Author'] ?? '')} onChange={e => set('Author', e.target.value)}>
                            <option value="">— select author —</option>
                            {authorOptions.filter(a => a).map(a => (
                                <option key={a} value={a}>{a}</option>
                            ))}
                        </select>
                    </div>

                    {/* All other core fields dynamically */}
                    {coreKeys.map(key => (
                        <div key={key} className={styles.modalField}>
                            <label>{key}</label>
                            {TEXTAREA_FIELDS.has(key)
                                ? <textarea rows={key === 'Body (HTML)' ? 8 : 4}
                                    value={String(form[key] ?? '')}
                                    onChange={e => set(key, e.target.value)} />
                                : <input value={String(form[key] ?? '')}
                                    onChange={e => set(key, e.target.value)} />
                            }
                        </div>
                    ))}

                    {/* Delete */}
                    <div className={styles.modalField}>
                        <label>Delete</label>
                        <select value={form['Delete'] || ''} onChange={e => set('Delete', e.target.value)}>
                            <option value="">—</option>
                            <option value="YES">YES</option>
                        </select>
                    </div>

                    {/* Metafields — fully dynamic */}
                    {metaKeys.length > 0 && (
                        <div style={{ borderTop: '1px solid #eee', margin: '12px 0', paddingTop: 12 }}>
                            <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', color: '#555', marginBottom: 8 }}>
                                METAFIELDS ({metaKeys.length})
                            </div>
                            {metaKeys.map(ns_key => (
                                <MetafieldInput
                                    key={ns_key}
                                    ns_key={ns_key}
                                    defn={articleMetafieldDefs[ns_key]}
                                    value={String(form[ns_key] ?? '')}
                                    onChange={val => set(ns_key, val)}
                                    error={null}
                                />
                            ))}
                        </div>
                    )}
                </div>

                <div className={styles.modalFooter}>
                    <button className={styles.cancelBtn} onClick={onClose}>CANCEL</button>
                    <button className={styles.saveBtn} onClick={() => onSave(form)}>SAVE TO GRID</button>
                </div>
            </div>
        </div>
    )
}


function NewBlogModal({ store, metafieldDefs, onClose, onCreated, onRefreshDefs }) {
    const [form, setForm] = useState({
        title: '', handle: '', comment_policy: 'CLOSED',
        seo_title: '', seo_description: '',
    })
    const [metaValues, setMetaValues] = useState({})
    const [errors, setErrors] = useState({})
    const [metaErrors, setMetaErrors] = useState({})
    const [saving, setSaving] = useState(false)
    const [refreshing, setRefreshing] = useState(false)
    

    const set = (key, val) => {
        setForm(prev => ({ ...prev, [key]: val }))
        // Auto-generate handle from title
        if (key === 'title') {
            setForm(prev => ({
                ...prev,
                title: val,
                handle: val.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
            }))
        }
        setErrors(prev => ({ ...prev, [key]: null }))
    }

    const setMeta = (ns_key, val) => {
        setMetaValues(prev => ({ ...prev, [ns_key]: val }))
        setMetaErrors(prev => ({ ...prev, [ns_key]: null }))
    }

    
    async function handleSave() {
        if (!validateFrontend()) return
        setSaving(true)
        try {
            const result = await createBlog(store.store_name, {
                title: form.title.trim(),
                handle: form.handle.trim() || undefined,
                comment_policy: form.comment_policy,
                seo_title: form.seo_title.trim(),
                seo_description: form.seo_description.trim(),
                metafields: metaValues,
            })
            onCreated(result)
        } catch (e) {
            try {
                const body = JSON.parse(e.message)
                if (body.metafield_errors) setMetaErrors(body.metafield_errors)
                else setErrors({ _general: body.error || 'Create failed' })
            } catch {
                setErrors({ _general: 'Create failed — check console' })
            }
        } finally {
            setSaving(false)
        }
    }

    async function handleRefreshDefs() {
        setRefreshing(true)
        await onRefreshDefs()
        setRefreshing(false)
    }

    function validateFrontend() {
        const errs = {}
        if (!form.title.trim()) errs.title = 'Title is required'
        if (form.seo_title.length > 70) errs.seo_title = `Too long (${form.seo_title.length}/70 chars)`
        if (form.seo_description.length > 160) errs.seo_description = `Too long (${form.seo_description.length}/160 chars)`

        const mErrs = {}
        for (const [ns_key, defn] of Object.entries(metafieldDefs)) {
            const val = String(metaValues[ns_key] || '').trim()
            if (!val || val.toLowerCase() === 'none') continue
            const err = validateMetafieldFrontend(ns_key, val, defn)
            if (err) mErrs[ns_key] = err
        }

        setErrors(errs)
        setMetaErrors(mErrs)
        return Object.keys(errs).length === 0 && Object.keys(mErrs).length === 0
    }

    const COMMENT_OPTIONS = [
        { value: 'CLOSED', label: 'Disabled' },
        { value: 'MODERATED', label: 'Allowed, pending moderation' },
        { value: 'AUTO_PUBLISHED', label: 'Allowed' },
    ]

    const hasDefs = Object.keys(metafieldDefs).length > 0

    return (
        <div className={styles.modalOverlay} onClick={onClose}>
            <div className={styles.modal} style={{ maxWidth: 600, maxHeight: '90vh', overflowY: 'auto' }}
                onClick={e => e.stopPropagation()}>

                <div className={styles.modalHeader}>
                    <span className={styles.modalTitle}>New Blog</span>
                    <button className={styles.modalClose} onClick={onClose}>✕</button>
                </div>

                <div className={styles.modalBody}>
                    {errors._general && (
                        <div style={{ color: '#ef4444', fontSize: 12, marginBottom: 8 }}>{errors._general}</div>
                    )}

                    {/* Title */}
                    <div className={styles.modalField}>
                        <label>Title * <span style={{ color: '#888', fontWeight: 400 }}>{form.title.length}/255</span></label>
                        <input value={form.title} onChange={e => set('title', e.target.value)}
                            placeholder="e.g. News, Updates, Blog"
                            style={errors.title ? { borderColor: '#ef4444' } : {}} />
                        {errors.title && <span style={{ color: '#ef4444', fontSize: 11 }}>{errors.title}</span>}
                    </div>

                    {/* Handle — read only, auto-generated */}
                    <div className={styles.modalField}>
                        <label style={{ color: '#888' }}>Handle (auto-generated)</label>
                        <input value={form.handle} readOnly
                            style={{ color: '#888', background: '#f5f5f5', cursor: 'not-allowed' }} />
                    </div>

                    {/* Comment policy */}
                    <div className={styles.modalField}>
                        <label>Comments</label>
                        <select value={form.comment_policy} onChange={e => set('comment_policy', e.target.value)}>
                            {COMMENT_OPTIONS.map(o => (
                                <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                        </select>
                    </div>

                    {/* SEO */}
                    <div style={{ borderTop: '1px solid #eee', margin: '12px 0', paddingTop: 12 }}>
                        <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', color: '#555', marginBottom: 8 }}>
                            SEARCH ENGINE LISTING
                        </div>
                        <div className={styles.modalField}>
                            <label>Page title <span style={{ color: '#888', fontWeight: 400 }}>{form.seo_title.length}/70</span></label>
                            <input value={form.seo_title} onChange={e => set('seo_title', e.target.value)}
                                style={errors.seo_title ? { borderColor: '#ef4444' } : {}} />
                            {errors.seo_title && <span style={{ color: '#ef4444', fontSize: 11 }}>{errors.seo_title}</span>}
                        </div>
                        <div className={styles.modalField}>
                            <label>Meta description <span style={{ color: '#888', fontWeight: 400 }}>{form.seo_description.length}/160</span></label>
                            <textarea rows={3} value={form.seo_description}
                                onChange={e => set('seo_description', e.target.value)}
                                style={errors.seo_description ? { borderColor: '#ef4444' } : {}} />
                            {errors.seo_description && <span style={{ color: '#ef4444', fontSize: 11 }}>{errors.seo_description}</span>}
                        </div>
                    </div>

                    {/* Metafields */}
                    <div style={{ borderTop: '1px solid #eee', margin: '12px 0', paddingTop: 12 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                            <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: '0.1em', color: '#555' }}>
                                METAFIELDS {hasDefs ? `(${Object.keys(metafieldDefs).length})` : ''}
                            </div>
                            <button className={styles.btn} onClick={handleRefreshDefs} disabled={refreshing}
                                style={{ fontSize: 10, padding: '2px 8px' }}>
                                {refreshing ? '...' : '↻ Refresh'}
                            </button>
                        </div>

                        {!hasDefs && (
                            <div style={{ fontSize: 12, color: '#888' }}>
                                No blog metafield definitions found. Click ↻ Refresh to fetch from Shopify.
                            </div>
                        )}

                        {Object.entries(metafieldDefs).map(([ns_key, defn]) => (
                            <MetafieldInput
                                key={ns_key}
                                ns_key={ns_key}
                                defn={defn}
                                value={metaValues[ns_key] || ''}
                                onChange={val => setMeta(ns_key, val)}
                                error={metaErrors[ns_key]}
                            />
                        ))}
                    </div>
                </div>

                <div className={styles.modalFooter}>
                    <button className={styles.cancelBtn} onClick={onClose}>CANCEL</button>
                    <button className={styles.saveBtn} onClick={handleSave} disabled={saving}>
                        {saving ? 'CREATING...' : 'CREATE BLOG'}
                    </button>
                </div>
            </div>
        </div>
    )
}

// Renders the right input for each metafield type — fully dynamic
function MetafieldInput({ ns_key, defn, value, onChange, error }) {
    const type = defn.type || 'single_line_text_field'
    const choices = defn.choices
    const label = defn.name || ns_key
    const min = defn.min
    const max = defn.max

    const borderStyle = error ? { borderColor: '#ef4444' } : {}

    let input
    if (choices && choices.length) {
        if (type.startsWith('list.')) {
            // Multi-select via comma separated
            input = (
                <input value={value} onChange={e => onChange(e.target.value)}
                    placeholder={`e.g. ${choices.slice(0, 2).join(', ')}`}
                    style={borderStyle} />
            )
        } else {
            input = (
                <select value={value} onChange={e => onChange(e.target.value)} style={borderStyle}>
                    <option value="">— select —</option>
                    {choices.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
            )
        }
    } else if (type === 'boolean') {
        input = (
            <select value={value} onChange={e => onChange(e.target.value)} style={borderStyle}>
                <option value="">—</option>
                <option value="true">True</option>
                <option value="false">False</option>
            </select>
        )
    } else if (type === 'multi_line_text_field') {
        input = (
            <textarea rows={3} value={value} onChange={e => onChange(e.target.value)} style={borderStyle} />
        )
    } else if (type === 'color') {
        input = (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input type="color" value={value || '#000000'}
                    onChange={e => onChange(e.target.value)}
                    style={{ width: 40, height: 32, padding: 2, cursor: 'pointer' }} />
                <input value={value} onChange={e => onChange(e.target.value)}
                    placeholder="#rrggbb" style={{ flex: 1, ...borderStyle }} />
            </div>
        )
    } else if (type === 'date') {
        input = <input type="date" value={value} onChange={e => onChange(e.target.value)} style={borderStyle} />
    } else if (type === 'date_time') {
        input = <input type="datetime-local" value={value} onChange={e => onChange(e.target.value)} style={borderStyle} />
    } else if (type === 'number_integer' || type === 'number_decimal' || type === 'rating') {
        input = (
            <input type="number" value={value} onChange={e => onChange(e.target.value)}
                min={min} max={max} step={type === 'number_integer' ? '1' : 'any'}
                style={borderStyle} />
        )
    } else {
        // single_line_text_field, url, json, weight, dimension, volume, etc.
        input = (
            <input value={value} onChange={e => onChange(e.target.value)}
                placeholder={type === 'url' ? 'https://' : ''}
                style={borderStyle} />
        )
    }

    return (
        <div className={styles.modalField}>
            <label>
                {label}
                <span style={{ color: '#aaa', fontWeight: 400, marginLeft: 6, fontSize: 10 }}>
                    {ns_key} · {type}
                    {max ? ` · max ${max}` : ''}
                </span>
            </label>
            {input}
            {error && <span style={{ color: '#ef4444', fontSize: 11 }}>⚠ {error}</span>}
        </div>
    )
}

// Frontend metafield validation — mirrors blog_validator.py
function validateMetafieldFrontend(ns_key, value, defn) {
    const type = defn.type || 'single_line_text_field'
    const choices = defn.choices
    const min = defn.min
    const max = defn.max
    const v = String(value || '').trim()
    if (!v) return null

    if (choices && choices.length) {
        if (type.startsWith('list.')) {
            const items = v.split(',').map(x => x.trim()).filter(Boolean)
            const invalid = items.filter(i => !choices.includes(i))
            if (invalid.length) return `Invalid choice(s): ${invalid.join(', ')}`
        } else {
            if (!choices.includes(v)) return `Must be one of: ${choices.join(', ')}`
        }
    }
    if (type === 'number_integer') {
        if (isNaN(parseInt(v)) || !Number.isInteger(Number(v))) return 'Must be a whole number'
        if (min !== null && Number(v) < Number(min)) return `Must be ≥ ${min}`
        if (max !== null && Number(v) > Number(max)) return `Must be ≤ ${max}`
    }
    if (type === 'number_decimal' || type === 'rating') {
        if (isNaN(Number(v))) return 'Must be a valid number'
        if (min !== null && Number(v) < Number(min)) return `Must be ≥ ${min}`
        if (max !== null && Number(v) > Number(max)) return `Must be ≤ ${max}`
    }
    if (type === 'boolean' && !['true', 'false'].includes(v.toLowerCase())) return 'Must be true or false'
    if (type === 'url' && !/^https?:\/\//i.test(v)) return 'Must be a valid URL (https://...)'
    if (type === 'color' && !/^#[0-9a-fA-F]{6}$/.test(v)) return 'Must be a valid hex color (e.g. #ff0000)'
    if (type === 'date' && isNaN(Date.parse(v))) return 'Must be a valid date (YYYY-MM-DD)'
    if ((type === 'single_line_text_field' || type === 'multi_line_text_field') && max && v.length > Number(max))
        return `Too long (${v.length}/${max} chars)`

    return null
}