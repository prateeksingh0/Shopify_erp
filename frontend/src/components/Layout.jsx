import { useState, useEffect, useCallback } from 'react'
import { Outlet } from 'react-router-dom'
import Topbar from './Topbar'
import Sidebar from './Sidebar'
import AddStoreModal from './AddStoreModal'
import styles from './Layout.module.css'
import { getStores } from '../api'

export default function Layout() {
    const [stores, setStores] = useState([])
    const [selectedStore, setSelectedStore] = useState(null)
    const [showAddStore, setShowAddStore] = useState(false)
    const [storesRefreshKey, setStoresRefreshKey] = useState(0)

    useEffect(() => {
        let cancelled = false
        getStores()
            .then(list => {
                if (cancelled) return
                setStores(list)
                if (list.length === 0) return
                const savedName = localStorage.getItem('selectedStore')
                const match = savedName && list.find(s => s.store_name === savedName)
                setSelectedStore(match || list[0])
            })
            .catch(e => console.error('Failed to load stores', e))
        return () => { cancelled = true }
    }, [storesRefreshKey])

    const handleStoreSelect = useCallback((store) => {
        setSelectedStore(store)
        if (store) localStorage.setItem('selectedStore', store.store_name)
    }, [])

    const handleStoreAdded = useCallback(() => {
        setShowAddStore(false)
        setStoresRefreshKey(k => k + 1)
    }, [])

    return (
        <div className={styles.root}>
            <Topbar
                selectedStore={selectedStore}
                stores={stores}
                onStoreSelect={handleStoreSelect}
                onAddStore={() => setShowAddStore(true)}
            />

            <div className={styles.body}>
                <Sidebar />
                <main className={styles.main}>
                    <Outlet context={{ selectedStore, stores }} />
                </main>
            </div>

            {showAddStore && (
                <AddStoreModal
                    onClose={() => setShowAddStore(false)}
                    onAdded={handleStoreAdded}
                />
            )}
        </div>
    )
}