import { NavLink, useLocation } from 'react-router-dom'
import { useState } from 'react'
import styles from './Sidebar.module.css'

const NAV = [
    { to: '/', icon: '🏠', label: 'Home' },
    { to: '/products', icon: '📦', label: 'Products' },
    { to: '/collections', icon: '🗂', label: 'Collections' },
    {
        icon: '📝', label: 'Blogs',
        children: [
            { to: '/blogs', label: 'Articles' },
            { to: '/blogs/settings', label: 'Blog Settings' },
        ]
    },
    { to: '/customers', icon: '👥', label: 'Customers' },
    { to: '/orders', icon: '📋', label: 'Orders' },
    { to: '/inventory', icon: '📊', label: 'Inventory' },
    { to: '/logs', icon: '🕓', label: 'Logs' },
    { to: '/settings', icon: '⚙️', label: 'Settings' },
]

export default function Sidebar() {
    const location = useLocation()
    const isBlogsActive = location.pathname.startsWith('/blogs')
    const [blogsOpen, setBlogsOpen] = useState(isBlogsActive)

    return (
        <nav className={styles.sidebar}>
            {NAV.map((item) => {
                if (item.children) {
                    const isGroupActive = location.pathname.startsWith('/blogs')
                    return (
                        <div key={item.label}>
                            <button
                                className={`${styles.item} ${styles.groupItem} ${isGroupActive ? styles.itemActive : ''}`}
                                onClick={() => setBlogsOpen(o => !o)}
                            >
                                <span className={styles.icon}>{item.icon}</span>
                                <span className={styles.label}>{item.label}</span>
                                <span className={styles.chevron}>{blogsOpen ? '▾' : '▸'}</span>
                            </button>
                            {blogsOpen && (
                                <div className={styles.subItems}>
                                    {item.children.map(({ to, label }) => (
                                        <NavLink
                                            key={to}
                                            to={to}
                                            end
                                            className={({ isActive }) =>
                                                `${styles.subItem} ${isActive ? styles.subItemActive : ''}`
                                            }
                                        >
                                            {label}
                                        </NavLink>
                                    ))}
                                </div>
                            )}
                        </div>
                    )
                }

                return (
                    <NavLink
                        key={item.to}
                        to={item.to}
                        end={item.to === '/'}
                        className={({ isActive }) =>
                            `${styles.item} ${isActive ? styles.itemActive : ''}`
                        }
                    >
                        <span className={styles.icon}>{item.icon}</span>
                        <span className={styles.label}>{item.label}</span>
                    </NavLink>
                )
            })}
        </nav>
    )
}