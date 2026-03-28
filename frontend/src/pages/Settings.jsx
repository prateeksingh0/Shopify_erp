import { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { getStores, deleteStore, addStore, clearStoreData } from '../api'
import styles from './Settings.module.css'

export default function Settings() {
    const { selectedStore } = useOutletContext()
    const [stores, setStores] = useState([])
    const [loading, setLoading] = useState(false)
    const [msg, setMsg] = useState('')

    // Change password
    const [currentPw, setCurrentPw] = useState('')
    const [newPw, setNewPw] = useState('')
    const [confirmPw, setConfirmPw] = useState('')
    const [pwMsg, setPwMsg] = useState('')
    const [pwLoading, setPwLoading] = useState(false)

    useEffect(() => {
        loadStores()
    }, [])

    async function loadStores() {
        setLoading(true)
        try {
            const list = await getStores()
            setStores(list)
        } catch (e) {
            setMsg(e.message)
        } finally {
            setLoading(false)
        }
    }

    async function handleDelete(storeName) {
        if (!confirm(`Delete store "${storeName}"? This cannot be undone.`)) return
        try {
            await deleteStore(storeName)
            setMsg(`Store "${storeName}" deleted`)
            loadStores()
        } catch (e) {
            setMsg(e.message)
        }
    }

    async function handleClearData(storeName) {
        if (!confirm(`Clear all local data for "${storeName}"? This cannot be undone.`)) return
        try {
            await clearStoreData(storeName)
            setMsg(`Data cleared for "${storeName}"`)
        } catch (e) {
            setMsg(e.message)
        }
    }

    async function handleChangePassword() {
        if (!currentPw || !newPw || !confirmPw) { setPwMsg('All fields required'); return }
        if (newPw !== confirmPw) { setPwMsg('Passwords do not match'); return }
        if (newPw.length < 6) { setPwMsg('Password must be at least 6 characters'); return }

        setPwLoading(true)
        setPwMsg('')
        try {
            const token = localStorage.getItem('access_token')
            const r = await fetch('/api/auth/change-password/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    Authorization: `Bearer ${token}`,
                },
                body: JSON.stringify({ current_password: currentPw, new_password: newPw }),
            })
            if (!r.ok) {
                const data = await r.json()
                setPwMsg(data.error || 'Failed to change password')
                return
            }
            setPwMsg('Password changed successfully')
            setCurrentPw('')
            setNewPw('')
            setConfirmPw('')
        } catch (e) {
            setPwMsg(e.message)
        } finally {
            setPwLoading(false)
        }
    }

    return (
        <div className={styles.page}>
            <div className={styles.toolbar}>
                <span className={styles.pageTitle}>SETTINGS</span>
            </div>

            <div className={styles.body}>

                {/* ── Stores ── */}
                <div className={styles.section}>
                    <div className={styles.sectionTitle}>CONNECTED STORES</div>
                    {loading && <div className={styles.hint}>Loading...</div>}
                    {msg && <div className={styles.msg}>{msg}</div>}

                    {stores.length === 0 && !loading && (
                        <div className={styles.hint}>No stores connected yet</div>
                    )}

                    {stores.map(store => (
                        <div key={store.store_name} className={styles.storeRow}>
                            <div className={styles.storeInfo}>
                                <span className={styles.storeName}>{store.store_name}</span>
                                <span className={styles.storeDomain}>{store.domain}</span>
                            </div>
                            <div className={styles.storeActions}>
                                <span className={styles.storeDate}>
                                    Added {new Date(store.created_at).toLocaleDateString()}
                                </span>
                                <button
                                    className={styles.clearBtn}
                                    onClick={() => handleClearData(store.store_name)}
                                >
                                    CLEAR DATA
                                </button>
                                <button
                                    className={styles.deleteBtn}
                                    onClick={() => handleDelete(store.store_name)}
                                >
                                    DELETE
                                </button>
                            </div>
                        </div>
                    ))}
                </div>

                {/* ── Change password ── */}
                <div className={styles.section}>
                    <div className={styles.sectionTitle}>CHANGE PASSWORD</div>

                    <div className={styles.form}>
                        <div className={styles.field}>
                            <label className={styles.label}>CURRENT PASSWORD</label>
                            <input
                                className={styles.input}
                                type="password"
                                value={currentPw}
                                onChange={e => setCurrentPw(e.target.value)}
                                placeholder="Enter current password"
                            />
                        </div>
                        <div className={styles.field}>
                            <label className={styles.label}>NEW PASSWORD</label>
                            <input
                                className={styles.input}
                                type="password"
                                value={newPw}
                                onChange={e => setNewPw(e.target.value)}
                                placeholder="Enter new password"
                            />
                        </div>
                        <div className={styles.field}>
                            <label className={styles.label}>CONFIRM NEW PASSWORD</label>
                            <input
                                className={styles.input}
                                type="password"
                                value={confirmPw}
                                onChange={e => setConfirmPw(e.target.value)}
                                onKeyDown={e => e.key === 'Enter' && handleChangePassword()}
                                placeholder="Confirm new password"
                            />
                        </div>

                        {pwMsg && (
                            <div className={pwMsg.includes('success') ? styles.msgOk : styles.msgErr}>
                                {pwMsg}
                            </div>
                        )}

                        <button
                            className={styles.saveBtn}
                            onClick={handleChangePassword}
                            disabled={pwLoading}
                        >
                            {pwLoading ? 'SAVING...' : 'CHANGE PASSWORD'}
                        </button>
                    </div>
                </div>

            </div>
        </div>
    )
}