import { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { getSyncLogs, getProducts } from '../api'
import styles from './Home.module.css'

function formatDate(iso) {
    if (!iso) return '—'
    const d = new Date(iso)
    const pad = n => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}  ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function formatDuration(seconds) {
    if (!seconds && seconds !== 0) return '—'
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${String(s).padStart(2, '0')}`
}

export default function Home() {
    const { selectedStore } = useOutletContext()
    const [logs, setLogs] = useState([])
    const [rowCount, setRowCount] = useState(null)
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        if (!selectedStore?.store_name) {
            setLogs([])
            setRowCount(null)
            return
        }
        let cancelled = false
        setLoading(true)

        Promise.all([
            getSyncLogs(selectedStore.store_name),
            getProducts(selectedStore.store_name).catch(() => []),
        ]).then(([logData, rows]) => {
            if (cancelled) return
            setLogs(logData.logs || [])
            setRowCount(Array.isArray(rows) ? rows.length : null)
        }).catch(() => {
            if (cancelled) return
        }).finally(() => {
            if (!cancelled) setLoading(false)
        })

        return () => { cancelled = true }
    }, [selectedStore?.store_name])

    const lastSync = logs.find(l => l.log_type === 'sync')
    const lastFetch = logs.find(l => l.log_type === 'fetch')
    const syncErrors = lastSync?.errors ?? 0
    const health = !lastSync ? 'NO DATA'
        : syncErrors > 0 ? 'ERRORS'
            : lastSync.status === 'error' ? 'FAILED'
                : 'HEALTHY'
    const healthColor = health === 'HEALTHY' ? '#0f8a5f'
        : health === 'NO DATA' ? '#9b8a73'
            : '#ef4444'

    const totalSyncs = logs.filter(l => l.log_type === 'sync').length
    const totalFetches = logs.filter(l => l.log_type === 'fetch').length

    return (
        <div className={styles.page}>
            <div className={styles.toolbar}>
                <span className={styles.pageTitle}>HOME</span>
                {selectedStore && (
                    <span className={styles.storeName}>{selectedStore.store_name}</span>
                )}
            </div>

            <div className={styles.body}>
                {!selectedStore && (
                    <div className={styles.empty}>Select a store to view dashboard</div>
                )}

                {selectedStore && loading && (
                    <div className={styles.empty}>Loading...</div>
                )}

                {selectedStore && !loading && (
                    <>
                        {/* Stat cards */}
                        <div className={styles.cards}>
                            <StatCard
                                label="TOTAL ROWS"
                                value={rowCount ?? '—'}
                                sub="in local CSV"
                                color="#c27a1a"
                            />
                            <StatCard
                                label="LAST FETCH"
                                value={formatDate(lastFetch?.started_at)}
                                sub={lastFetch ? `${lastFetch.total} rows · ${formatDuration(lastFetch.duration_seconds)}` : 'Never fetched'}
                                color="#6366f1"
                            />
                            <StatCard
                                label="LAST SYNC"
                                value={formatDate(lastSync?.started_at)}
                                sub={lastSync ? `${lastSync.updated} updated · ${lastSync.errors} errors` : 'Never synced'}
                                color="#0f8a5f"
                            />
                            <StatCard
                                label="STORE HEALTH"
                                value={health}
                                sub={lastSync ? `${totalSyncs} syncs · ${totalFetches} fetches` : 'Run a sync first'}
                                color={healthColor}
                            />
                        </div>

                        {/* Recent logs */}
                        <div className={styles.section}>
                            <div className={styles.sectionTitle}>RECENT ACTIVITY</div>
                            {logs.length === 0 ? (
                                <div className={styles.empty}>No activity yet — fetch and sync to get started</div>
                            ) : (
                                <table className={styles.table}>
                                    <thead>
                                        <tr>
                                            <th>TYPE</th>
                                            <th>TIME</th>
                                            <th>STATUS</th>
                                            <th>DURATION</th>
                                            <th>TOTAL</th>
                                            <th>UPDATED</th>
                                            <th>ERRORS</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {logs.slice(0, 10).map(log => (
                                            <tr key={log.id} className={log.status === 'error' ? styles.rowError : ''}>
                                                <td>
                                                    <span className={log.log_type === 'fetch' ? styles.typeFetch : styles.typeSync}>
                                                        {(log.log_type || 'sync').toUpperCase()}
                                                    </span>
                                                </td>
                                                <td className={styles.time}>{formatDate(log.started_at)}</td>
                                                <td>
                                                    <span className={log.status === 'success' ? styles.statusOk : styles.statusErr}>
                                                        {log.status.toUpperCase()}
                                                    </span>
                                                </td>
                                                <td>{formatDuration(log.duration_seconds)}</td>
                                                <td>{log.total}</td>
                                                <td className={log.updated > 0 ? styles.green : ''}>{log.updated}</td>
                                                <td className={log.errors > 0 ? styles.red : ''}>{log.errors}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

function StatCard({ label, value, sub, color }) {
    return (
        <div className={styles.card}>
            <div className={styles.cardLabel}>{label}</div>
            <div className={styles.cardValue} style={{ color }}>{value}</div>
            <div className={styles.cardSub}>{sub}</div>
        </div>
    )
}