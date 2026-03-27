import { useState } from 'react'
import { addStore } from '../api'
import styles from './AddStoreModal.module.css'

export default function AddStoreModal({ onClose, onAdded }) {
    const [domain, setDomain] = useState('')
    const [clientId, setClientId] = useState('')
    const [clientSecret, setClientSecret] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')

    async function handleSubmit() {
        if (!domain || !clientId || !clientSecret) {
            setError('All fields required');
            return
        }
        setLoading(true)
        setError('')
        try {
            await addStore(domain.trim(), clientId.trim(), clientSecret.trim())
            onAdded()
        } catch (e) {
            setError(e.message)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className={styles.overlay} onClick={onClose}>
            <div className={styles.modal} onClick={e => e.stopPropagation()}>
                <div className={styles.title}>ADD STORE</div>

                <div className={styles.field}>
                    <label className={styles.label}>DOMAIN</label>
                    <input
                        className={styles.input}
                        placeholder="your-store.myshopify.com"
                        value={domain}
                        onChange={e => setDomain(e.target.value)}
                        autoFocus
                    />
                </div>

                <div className={styles.field}>
                    <label className={styles.label}>CLIENT ID</label>
                    <input
                        className={styles.input}
                        type="text"
                        placeholder="Enter client ID"
                        value={clientId}
                        onChange={e => setClientId(e.target.value)}
                    />
                </div>

                <div className={styles.field}>
                    <label className={styles.label}>CLIENT SECRET</label>
                    <input
                        className={styles.input}
                        type="password"
                        placeholder="Enter client secret"
                        value={clientSecret}
                        onChange={e => setClientSecret(e.target.value)}
                    />
                </div>

                {error && <div className={styles.error}>{error}</div>}

                <div className={styles.actions}>
                    <button className={styles.cancelBtn} onClick={onClose}>CANCEL</button>
                    <button className={styles.addBtn} onClick={handleSubmit} disabled={loading}>
                        {loading ? 'ADDING...' : 'ADD STORE'}
                    </button>
                </div>
            </div>
        </div>
    )
}