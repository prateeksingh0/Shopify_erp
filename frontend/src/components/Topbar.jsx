import { useNavigate } from 'react-router-dom'
import { logout } from '../api'
import styles from './Topbar.module.css'

export default function Topbar({ selectedStore, stores, onStoreSelect, onAddStore }) {
    const navigate = useNavigate()

    async function handleLogout() {
        const refresh = localStorage.getItem('refresh_token')
        await logout(refresh)
        navigate('/login')
    }

    return (
        <header className={styles.topbar}>
            <div className={styles.brand}>
                <span className={styles.brandDot} />
                <span className={styles.brandText}>SYNC</span>
            </div>

            <div className={styles.divider} />

            <div className={styles.storeSection}>
                <span className={styles.label}>STORE</span>
                <select
                    className={styles.select}
                    value={selectedStore?.store_name ?? ''}
                    onChange={e => {
                        const s = stores.find(s => s.store_name === e.target.value)
                        onStoreSelect(s ?? null)
                    }}
                >
                    <option value="">— select store —</option>
                    {stores.map(s => (
                        <option key={s.store_name} value={s.store_name}>
                            {s.store_name}
                        </option>
                    ))}
                </select>
                <button className={styles.addBtn} onClick={onAddStore} title="Add store">+</button>
            </div>

            <div className={styles.spacer} />

            <button className={styles.logoutBtn} onClick={handleLogout} title="Logout">
                ⏻ LOGOUT
            </button>
        </header>
    )
}