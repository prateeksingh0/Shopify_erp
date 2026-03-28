import { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { getSyncLogs } from '../api'
import styles from './Logs.module.css'

function formatDate(iso) {
    const d = new Date(iso)
    const pad = n => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}  ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function formatDuration(seconds) {
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return `${m}:${String(s).padStart(2, '0')}`
}

export default function Logs() {
    const { selectedStore } = useOutletContext()
    const [logs, setLogs] = useState([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')

    useEffect(() => {
        if (!selectedStore?.store_name) return
        let cancelled = false
        setLoading(true)
        setError('')
        getSyncLogs(selectedStore.store_name)
            .then(data => {
                if (cancelled) return
                setLogs(data.logs || [])
            })
            .catch(e => {
                if (cancelled) return
                setError(e.message)
            })
            .finally(() => setLoading(false))
        return () => { cancelled = true }
    }, [selectedStore?.store_name])

    // console.log('logs data:', logs)

    return (
        <div className={styles.page}>
            <div className={styles.toolbar}>
                <span className={styles.pageTitle}>SYNC LOGS</span>
                {selectedStore && (
                    <span className={styles.storeName}>{selectedStore.store_name}</span>
                )}
            </div>

            <div className={styles.body}>
                {!selectedStore && <div className={styles.empty}>Select a store to view logs</div>}
                {loading && <div className={styles.empty}>Loading...</div>}
                {error && <div className={styles.error}>{error}</div>}

                {!loading && selectedStore && logs.length === 0 && (
                    <div className={styles.empty}>No sync logs yet — run a sync first</div>
                )}

                {logs.length > 0 && (
                    <table className={styles.table}>
                        <thead>
                            <tr>
                                <th>TYPE</th>
                                <th>TIME</th>
                                <th>STATUS</th>
                                <th>DURATION</th>
                                <th>TOTAL</th>
                                <th>UPDATED</th>
                                <th>CREATED</th>
                                <th>SKIPPED</th>
                                <th>ERRORS</th>
                                <th>CONFLICTS</th>
                            </tr>
                        </thead>
                        <tbody>
                            {logs.map(log => (
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
                                    <td className={log.created > 0 ? styles.purple : ''}>{log.created}</td>
                                    <td>{log.skipped}</td>
                                    <td className={log.errors > 0 ? styles.red : ''}>{log.errors}</td>
                                    <td className={log.conflicts > 0 ? styles.yellow : ''}>{log.conflicts}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>
        </div>
    )
}