import { NavLink } from 'react-router-dom'
import styles from './Sidebar.module.css'

const NAV = [
    { to: '/', icon: '🏠', label: 'Home' },
    { to: '/products', icon: '📦', label: 'Products' },
    { to: '/collections', icon: '🗂', label: 'Collections' },
    { to: '/blogs', icon: '📝', label: 'Blogs' },
    { to: '/customers', icon: '👥', label: 'Customers' },
    { to: '/orders', icon: '📋', label: 'Orders' },
    { to: '/inventory', icon: '📊', label: 'Inventory' },
    { to: '/logs', icon: '🕓', label: 'Logs' },
    { to: '/settings', icon: '⚙️', label: 'Settings' },
]

export default function Sidebar() {
    return (
        <nav className={styles.sidebar}>
            {NAV.map(({ to, icon, label }) => (
                <NavLink
                    key={to}
                    to={to}
                    end={to === '/'}
                    className={({ isActive }) =>
                        `${styles.item} ${isActive ? styles.itemActive : ''}`
                    }
                >
                    <span className={styles.icon}>{icon}</span>
                    <span className={styles.label}>{label}</span>
                </NavLink>
            ))}
        </nav>
    )
}