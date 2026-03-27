import { useState, useEffect } from 'react'
import { getSnapshots, rollbackPreview } from '../api'
import styles from './RollbackPanel.module.css'

function formatDate(isoStr) {
    const d = new Date(isoStr)
    const pad = n => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}  ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export default function RollbackPanel({ store, onClose, onApply }) {
    const [snapshots, setSnapshots] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const [previewing, setPreviewing] = useState(null)   // timestamp being previewed
    const [previewResult, setPreviewResult] = useState(null)   // { rows, changed_indices, changed_count }

    useEffect(() => {
        if (!store) return
        setLoading(true)
        setError('')
        getSnapshots(store.store_name)
            .then(data => {
                // Django returns { snapshots: [...] }
                setSnapshots(data.snapshots || [])
            })
            .catch(e => setError(e.message))
            .finally(() => setLoading(false))
    }, [store?.store_name])

    async function handlePreview(snap) {
        if (previewing === snap.timestamp) {
            // Toggle off
            setPreviewing(null)
            setPreviewResult(null)
            return
        }
        setPreviewing(snap.timestamp)
        setPreviewResult(null)
        setError('')
        try {
            // Django returns { rows, changed_indices, changed_count, total_rows, snapshot_timestamp }
            const result = await rollbackPreview(store.store_name, snap.timestamp)
            setPreviewResult(result)
        } catch (e) {
            setError(e.message)
            setPreviewing(null)
        }
    }

    function handleApply() {
        if (!previewResult) return
        const changedSet = new Set(previewResult.changed_indices)
        onApply(previewResult.rows, changedSet)
        onClose()
    }

    return (
        <div className={styles.overlay} onClick={onClose}>
            <div className={styles.panel} onClick={e => e.stopPropagation()}>
                <div className={styles.header}>
                    <span className={styles.title}>ROLLBACK</span>
                    <span className={styles.subtitle}>{store?.store_name}</span>
                    <button className={styles.closeBtn} onClick={onClose}>✕</button>
                </div>

                <div className={styles.body}>
                    {loading && <div className={styles.info}>Loading snapshots...</div>}
                    {error && <div className={styles.error}>{error}</div>}

                    {!loading && snapshots.length === 0 && (
                        <div className={styles.info}>No snapshots found. Run a FETCH first.</div>
                    )}

                    {snapshots.map(snap => {
                        const isActive = previewing === snap.timestamp
                        return (
                            <div
                                key={snap.timestamp}
                                className={`${styles.snapRow} ${isActive ? styles.snapRowActive : ''}`}
                            >
                                <div className={styles.snapInfo}>
                                    <span className={styles.snapDate}>{formatDate(snap.timestamp)}</span>
                                    <span className={styles.snapCount}>
                                        {snap.products_count != null ? `${snap.products_count} products` : ''}
                                    </span>
                                </div>
                                <button
                                    className={`${styles.previewBtn} ${isActive ? styles.previewBtnActive : ''}`}
                                    onClick={() => handlePreview(snap)}
                                    disabled={previewing !== null && previewing !== snap.timestamp}
                                >
                                    {isActive && !previewResult ? 'LOADING...' : isActive ? 'DESELECT' : 'SELECT'}
                                </button>
                            </div>
                        )
                    })}

                    {previewResult && (
                        <div className={styles.previewSummary}>
                            <span className={styles.affectedLabel}>
                                {previewResult.changed_count} row{previewResult.changed_count !== 1 ? 's' : ''} will change
                            </span>
                            <span className={styles.previewHint}>
                                Changed rows will be highlighted yellow in the grid.
                                Click SYNC after loading to push changes to Shopify.
                            </span>
                        </div>
                    )}
                </div>

                <div className={styles.footer}>
                    <button className={styles.cancelBtn} onClick={onClose}>CANCEL</button>
                    <button
                        className={styles.applyBtn}
                        onClick={handleApply}
                        disabled={!previewResult}
                    >
                        LOAD INTO GRID
                    </button>
                </div>
            </div>
        </div>
    )
}