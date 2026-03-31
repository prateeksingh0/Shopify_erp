import { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import {
    getBlogList, getBlogDetail, updateBlog, getBlogMetafieldDefs,
    createBlog, deleteBlog, fetchBlogList, refreshBlogMetafieldDefs
} from '../api'

import { NewBlogModal } from './Blogs'

import styles from './Blogs.module.css'

const COMMENT_OPTIONS = [
    { value: 'CLOSED', label: 'Disabled' },
    { value: 'MODERATED', label: 'Allowed, pending moderation' },
    { value: 'AUTO_PUBLISHED', label: 'Allowed' },
]

export default function BlogSettings() {
    const { selectedStore } = useOutletContext()
    const [blogs, setBlogs] = useState([])
    const [selectedBlogId, setSelectedBlogId] = useState('')
    const [detail, setDetail] = useState(null)
    const [form, setForm] = useState(null)
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [fetching, setFetching] = useState(false)
    const [msg, setMsg] = useState('')
    const [showNewBlog, setShowNewBlog] = useState(false)
    const [confirmDelete, setConfirmDelete] = useState(false)
    const [deleting, setDeleting] = useState(false)
    const [blogMetafieldDefs, setBlogMetafieldDefs] = useState({})

    // Load blog list + metafield defs when store changes
    useEffect(() => {
        if (!selectedStore?.store_name) { setBlogs([]); setDetail(null); setForm(null); return }

        Promise.all([
            getBlogList(selectedStore.store_name),
            getBlogMetafieldDefs(selectedStore.store_name),
        ]).then(([blogData, defs]) => {
            const list = blogData.blogs || []
            setBlogs(list)
            setBlogMetafieldDefs(defs)
            if (list.length) setSelectedBlogId(list[0]['Blog ID'])
        }).catch(() => { })
    }, [selectedStore?.store_name])

    // Load blog detail when selection changes
    useEffect(() => {
        if (!selectedStore?.store_name || !selectedBlogId) return
        setLoading(true)
        setMsg('')
        setConfirmDelete(false)
        getBlogDetail(selectedStore.store_name, selectedBlogId)
            .then(data => {
                setDetail(data)
                setForm({
                    title: data.title,
                    handle: data.handle,
                    comment_policy: data.comment_policy,
                    seo_title: data.seo_title || '',
                    seo_description: data.seo_description || '',
                    metafields: { ...data.metafields },
                })
            })
            .catch(() => setMsg('Failed to load blog details'))
            .finally(() => setLoading(false))
    }, [selectedBlogId, selectedStore?.store_name])

    const set = (key, val) => setForm(prev => ({ ...prev, [key]: val }))
    const setMeta = (ns_key, val) => setForm(prev => ({
        ...prev, metafields: { ...prev.metafields, [ns_key]: val }
    }))

    async function handleFetch() {
        if (!selectedStore || fetching) return
        setFetching(true)
        setMsg('Fetching blog list...')
        try {
            const data = await fetchBlogList(selectedStore.store_name)
            const list = data.blogs || []
            setBlogs(list)
            if (list.length && !selectedBlogId) setSelectedBlogId(list[0]['Blog ID'])
            // Reload metafield defs — they were refreshed on backend during fetch
            const defs = await getBlogMetafieldDefs(selectedStore.store_name)
            setBlogMetafieldDefs(defs)
            setMsg(`${list.length} blogs loaded`)
        } catch (e) {
            setMsg('Fetch failed')
            console.error(e)
        } finally {
            setFetching(false)
        }
    }

    async function handleSave() {
        if (!form || !selectedStore) return
        setSaving(true)
        setMsg('')
        try {
            await updateBlog(selectedStore.store_name, selectedBlogId, form)
            setMsg('Blog updated successfully')
            // Refresh detail and blog list
            const fresh = await getBlogDetail(selectedStore.store_name, selectedBlogId)
            setDetail(fresh)
            setForm({
                title: fresh.title,
                handle: fresh.handle,
                comment_policy: fresh.comment_policy,
                seo_title: fresh.seo_title || '',
                seo_description: fresh.seo_description || '',
                metafields: { ...fresh.metafields },
            })
            // Update title in sidebar list
            setBlogs(prev => prev.map(b =>
                b['Blog ID'] === selectedBlogId
                    ? { ...b, 'Blog Title': fresh.title, 'Blog Handle': fresh.handle }
                    : b
            ))
        } catch (e) {
            setMsg('Update failed — check console')
            console.error(e)
        } finally {
            setSaving(false)
        }
    }

    async function handleDelete() {
        if (!selectedStore || !selectedBlogId) return
        setDeleting(true)
        setMsg('')
        try {
            await deleteBlog(selectedStore.store_name, selectedBlogId)
            const remaining = blogs.filter(b => b['Blog ID'] !== selectedBlogId)
            setBlogs(remaining)
            setDetail(null)
            setForm(null)
            setConfirmDelete(false)
            if (remaining.length) {
                setSelectedBlogId(remaining[0]['Blog ID'])
            } else {
                setSelectedBlogId('')
            }
            setMsg('Blog deleted')
        } catch (e) {
            setMsg('Delete failed — check console')
            console.error(e)
        } finally {
            setDeleting(false)
        }
    }

    function handleBlogCreated(newBlog) {
        setShowNewBlog(false)
        const entry = {
            'Blog ID': newBlog.id,
            'Blog Title': newBlog.title,
            'Blog Handle': newBlog.handle,
        }
        setBlogs(prev => [...prev, entry])
        setSelectedBlogId(newBlog.id)
        setMsg(`Blog "${newBlog.title}" created`)
    }

    const defs = detail?.metafield_defs || {}

    return (
        <div className={styles.page}>
            {/* Toolbar */}
            <div className={styles.toolbar}>
                <span className={styles.pageTitle}>BLOG SETTINGS</span>
                <div className={styles.divider} />
                <button className={`${styles.btn} ${fetching ? styles.btnActive : ''}`}
                    onClick={handleFetch} disabled={!selectedStore || fetching}>
                    {fetching ? <><span className={styles.spinner} /> FETCHING</> : <>↓ FETCH</>}
                </button>
                <button className={styles.btn}
                    onClick={() => setShowNewBlog(true)}
                    disabled={!selectedStore}>
                    + NEW BLOG
                </button>
                <div className={styles.spacer} />
                {msg && <span className={styles.statusMsg}>{msg}</span>}
            </div>

            <div style={{ display: 'flex', gap: 0, height: 'calc(100% - 48px)', overflow: 'hidden' }}>
                {/* Blog selector sidebar */}
                <div style={{
                    width: 220, flexShrink: 0,
                    borderRight: '1px solid #e5e0d8',
                    overflowY: 'auto',
                    padding: '12px 8px',
                    display: 'flex', flexDirection: 'column', gap: 4,
                }}>
                    <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.12em', color: '#888', marginBottom: 8, padding: '0 4px' }}>
                        BLOGS ({blogs.length})
                    </div>
                    {blogs.length === 0 && (
                        <div style={{ fontSize: 11, color: '#aaa', padding: '4px' }}>
                            No blogs — click FETCH
                        </div>
                    )}
                    {blogs.map(b => (
                        <button key={b['Blog ID']}
                            onClick={() => setSelectedBlogId(b['Blog ID'])}
                            style={{
                                textAlign: 'left', padding: '8px 10px',
                                background: selectedBlogId === b['Blog ID'] ? '#fff3dc' : 'transparent',
                                border: '1px solid',
                                borderColor: selectedBlogId === b['Blog ID'] ? '#c27a1a44' : 'transparent',
                                borderRadius: 4, cursor: 'pointer',
                                fontFamily: "'IBM Plex Mono', monospace",
                                fontSize: 11, color: '#2f2417', fontWeight: 600,
                                width: '100%',
                            }}>
                            {b['Blog Title']}
                            <div style={{ fontSize: 10, color: '#999', fontWeight: 400, marginTop: 2 }}>
                                /{b['Blog Handle']}
                            </div>
                        </button>
                    ))}
                </div>

                {/* Blog detail panel */}
                <div style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
                    {loading && <div style={{ color: '#888', fontSize: 12 }}>Loading...</div>}

                    {!loading && !form && selectedStore && (
                        <div style={{ color: '#888', fontSize: 12 }}>
                            {blogs.length === 0
                                ? 'No blogs found — click FETCH first.'
                                : 'Select a blog from the list.'}
                        </div>
                    )}

                    {!loading && form && (
                        <div style={{ maxWidth: 600, display: 'flex', flexDirection: 'column', gap: 0 }}>

                            {/* Read-only info */}
                            <div style={{ marginBottom: 20, padding: 12, background: '#faf5ec', border: '1px solid #e5e0d8', borderRadius: 4 }}>
                                <div style={{ fontSize: 10, color: '#888', marginBottom: 4 }}>BLOG ID</div>
                                <div style={{ fontSize: 11, color: '#555', fontFamily: "'IBM Plex Mono', monospace" }}>
                                    {detail.id}
                                </div>
                            </div>

                            {/* Title */}
                            <div className={styles.modalField}>
                                <label>Title</label>
                                <input value={form.title} onChange={e => set('title', e.target.value)} />
                            </div>

                            {/* Handle */}
                            <div className={styles.modalField}>
                                <label>Handle</label>
                                <input value={form.handle} onChange={e => set('handle', e.target.value)}
                                    style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 12 }} />
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
                            <div style={{ borderTop: '1px solid #eee', margin: '16px 0 12px', paddingTop: 12 }}>
                                <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.12em', color: '#888', marginBottom: 10 }}>
                                    SEARCH ENGINE LISTING
                                </div>
                                <div className={styles.modalField}>
                                    <label>
                                        Page title
                                        <span style={{ color: '#aaa', fontWeight: 400 }}> {form.seo_title.length}/70</span>
                                    </label>
                                    <input value={form.seo_title} onChange={e => set('seo_title', e.target.value)} />
                                </div>
                                <div className={styles.modalField}>
                                    <label>
                                        Meta description
                                        <span style={{ color: '#aaa', fontWeight: 400 }}> {form.seo_description.length}/160</span>
                                    </label>
                                    <textarea rows={3} value={form.seo_description}
                                        onChange={e => set('seo_description', e.target.value)} />
                                </div>
                            </div>

                            {/* Metafields — fully dynamic */}
                            {Object.keys(defs).length > 0 && (
                                <div style={{ borderTop: '1px solid #eee', margin: '16px 0 12px', paddingTop: 12 }}>
                                    <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.12em', color: '#888', marginBottom: 10 }}>
                                        METAFIELDS ({Object.keys(defs).length})
                                    </div>
                                    {Object.entries(defs).map(([ns_key, defn]) => (
                                        <BlogMetafieldInput
                                            key={ns_key}
                                            ns_key={ns_key}
                                            defn={defn}
                                            value={form.metafields[ns_key] || ''}
                                            onChange={val => setMeta(ns_key, val)}
                                        />
                                    ))}
                                </div>
                            )}

                            {/* Actions */}
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 24, paddingTop: 16, borderTop: '1px solid #eee' }}>
                                {/* Delete */}
                                {!confirmDelete ? (
                                    <button onClick={() => setConfirmDelete(true)}
                                        style={{
                                            background: 'none', border: '1px solid #e5e0d8',
                                            borderRadius: 4, padding: '6px 14px',
                                            fontSize: 11, color: '#c0392b', cursor: 'pointer',
                                            fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600,
                                        }}>
                                        ✕ DELETE BLOG
                                    </button>
                                ) : (
                                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                                        <span style={{ fontSize: 11, color: '#c0392b' }}>Delete permanently?</span>
                                        <button onClick={handleDelete} disabled={deleting}
                                            style={{
                                                background: '#c0392b', border: 'none',
                                                borderRadius: 4, padding: '6px 14px',
                                                fontSize: 11, color: '#fff', cursor: 'pointer',
                                                fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600,
                                            }}>
                                            {deleting ? 'DELETING...' : 'YES, DELETE'}
                                        </button>
                                        <button onClick={() => setConfirmDelete(false)}
                                            style={{
                                                background: 'none', border: '1px solid #e5e0d8',
                                                borderRadius: 4, padding: '6px 14px',
                                                fontSize: 11, color: '#666', cursor: 'pointer',
                                                fontFamily: "'IBM Plex Mono', monospace",
                                            }}>
                                            CANCEL
                                        </button>
                                    </div>
                                )}

                                {/* Save */}
                                <button className={styles.saveBtn} onClick={handleSave} disabled={saving}>
                                    {saving ? 'SAVING...' : '⇅ SAVE TO SHOPIFY'}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* New Blog Modal */}
            {showNewBlog && (
                <NewBlogModal
                    store={selectedStore}
                    metafieldDefs={blogMetafieldDefs}
                    onClose={() => setShowNewBlog(false)}
                    onCreated={handleBlogCreated}
                    onRefreshDefs={async () => {
                        const defs = await refreshBlogMetafieldDefs(selectedStore.store_name)
                        setBlogMetafieldDefs(defs)
                    }}
                />
            )}
        </div>
    )
}

function BlogMetafieldInput({ ns_key, defn, value, onChange }) {
    const type = defn.type || 'single_line_text_field'
    const choices = defn.choices
    const label = defn.name || ns_key
    const min = defn.min
    const max = defn.max

    let input
    if (choices && choices.length) {
        if (type.startsWith('list.')) {
            input = <input value={value} onChange={e => onChange(e.target.value)}
                placeholder={`e.g. ${choices.slice(0, 2).join(', ')}`} />
        } else {
            input = (
                <select value={value} onChange={e => onChange(e.target.value)}>
                    <option value="">— select —</option>
                    {choices.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
            )
        }
    } else if (type === 'boolean') {
        input = (
            <select value={value} onChange={e => onChange(e.target.value)}>
                <option value="">—</option>
                <option value="true">True</option>
                <option value="false">False</option>
            </select>
        )
    } else if (type === 'multi_line_text_field') {
        input = <textarea rows={3} value={value} onChange={e => onChange(e.target.value)} />
    } else if (type === 'color') {
        input = (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input type="color" value={value || '#000000'} onChange={e => onChange(e.target.value)}
                    style={{ width: 40, height: 32, padding: 2, cursor: 'pointer' }} />
                <input value={value} onChange={e => onChange(e.target.value)} placeholder="#rrggbb" style={{ flex: 1 }} />
            </div>
        )
    } else if (type === 'date') {
        input = <input type="date" value={value} onChange={e => onChange(e.target.value)} />
    } else if (type === 'date_time') {
        input = <input type="datetime-local" value={value} onChange={e => onChange(e.target.value)} />
    } else if (type === 'number_integer' || type === 'number_decimal' || type === 'rating') {
        input = <input type="number" value={value} onChange={e => onChange(e.target.value)}
            min={min} max={max} step={type === 'number_integer' ? '1' : 'any'} />
    } else {
        input = <input value={value} onChange={e => onChange(e.target.value)}
            placeholder={type === 'url' ? 'https://' : ''} />
    }

    return (
        <div className={styles.modalField}>
            <label>
                {label}
                <span style={{ color: '#aaa', fontWeight: 400, marginLeft: 6, fontSize: 10 }}>
                    {ns_key} · {type}{max ? ` · max ${max}` : ''}
                </span>
            </label>
            {input}
        </div>
    )
}