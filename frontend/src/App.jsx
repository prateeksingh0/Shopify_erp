import { useState, useCallback, useEffect } from 'react'
import Header from './components/Header'
import ProductGrid from './components/ProductGrid'
import SyncProgress from './components/SyncProgress'
import AddStoreModal from './components/AddStoreModal'
import RollbackPanel from './components/RollbackPanel'
import ShopifyView from './components/ShopifyView'
import styles from './App.module.css'
import { getMetafieldDefs, getMetafieldOwners, getFieldSchema, getCollectionHandles } from './api'

export default function App() {
  const [selectedStore, setSelectedStore] = useState(null)
  const [rows, setRows] = useState([])
  const [isFetching, setIsFetching] = useState(false)
  const [isSyncing, setIsSyncing] = useState(false)
  const [syncState, setSyncState] = useState(null)   // null | { results, summary }
  const [showAddStore, setShowAddStore] = useState(false)
  const [storesRefreshKey, setStoresRefreshKey] = useState(0)
  const [showRollback, setShowRollback] = useState(false)
  const [rollbackChangedIndices, setRollbackChangedIndices] = useState(null)
  const [loadKey, setLoadKey] = useState(0)
  const [metafieldDefs, setMetafieldDefs] = useState({ product: {}, variant: {} })
  const [metafieldOwners, setMetafieldOwners] = useState({})
  const [fieldSchema, setFieldSchema] = useState({ enums: {}, validations: {} })
  const [collectionHandles, setCollectionHandles] = useState([])
  const [activeView, setActiveView] = useState('excel') // 'excel' | 'shopify'

  const handleStoreSelected = useCallback((store) => {
    setSelectedStore(store)
    setRows([])
    setSyncState(null)
    setRollbackChangedIndices(null)
    setMetafieldDefs({ product: {}, variant: {} })
    setMetafieldOwners({})
    setFieldSchema({ enums: {}, validations: {} })
    setCollectionHandles([])
    if (store) localStorage.setItem('selectedStore', store.store_name)
  }, [])

  const handleRowsLoaded = useCallback((newRows) => {
    setRows(newRows)
    setSyncState(null)
    setRollbackChangedIndices(null)
    setLoadKey(k => k + 1)
  }, [])

  const handleSyncResult = useCallback((rowIndex, status) => {
    setSyncState(prev => {
      const results = prev?.results ? { ...prev.results } : {}
      results[rowIndex] = status
      return { ...prev, results }
    })
    // Update row Sync Status directly here
    setRows(prev => prev.map((row, i) => {
      if (i !== rowIndex) return row
      return { ...row, 'Sync Status': status }
    }))
  }, [])

  const handleSyncSummary = useCallback((summary) => {
    setSyncState(prev => ({ ...prev, summary }))
    setIsSyncing(false)
  }, [])

  const handleSyncStart = useCallback(() => {
    setSyncState({ results: {} })
    setRollbackChangedIndices(null)
  }, [])

  const handleStoreAdded = useCallback(() => {
    setShowAddStore(false)
    setStoresRefreshKey(k => k + 1)
  }, [])

  // Reload metafield definitions when store changes OR new rows are fetched.
  // This keeps dropdowns dynamic after every FETCH without a hard refresh.
  useEffect(() => {
    if (!selectedStore?.store_name) return

    let cancelled = false

    Promise.all([
      getMetafieldDefs(selectedStore.store_name),
      getMetafieldOwners(selectedStore.store_name),
      getFieldSchema(selectedStore.store_name),
      getCollectionHandles(selectedStore.store_name),
    ])
      .then(([defs, owners, schema, colHandles]) => {
        if (cancelled) return
        setMetafieldDefs(defs || { product: {}, variant: {} })
        setMetafieldOwners(owners || {})
        setFieldSchema(schema || { enums: {}, validations: {} })
        setCollectionHandles(colHandles?.handles || [])
      })
      .catch((err) => {
        if (cancelled) return
        console.warn('[MetafieldMeta] Could not load:', err)
        setMetafieldDefs({ product: {}, variant: {} })
        setMetafieldOwners({})
        setFieldSchema({ enums: {}, validations: {} })
        setCollectionHandles([])
      })

    return () => { cancelled = true }
  }, [selectedStore?.store_name, loadKey])

  const handleRollbackApply = useCallback((rollbackRows, changedIndices) => {
    setRows(rollbackRows)
    setSyncState(null)
    setRollbackChangedIndices(new Set(changedIndices))
  }, [])

  return (
    <div className={styles.app}>
      <Header
        selectedStore={selectedStore}
        onStoreSelect={handleStoreSelected}
        onRowsLoaded={handleRowsLoaded}
        onAddStore={() => setShowAddStore(true)}
        onRollback={() => setShowRollback(true)}
        isFetching={isFetching}
        setIsFetching={setIsFetching}
        isSyncing={isSyncing}
        setIsSyncing={setIsSyncing}
        rows={rows}
        onSyncResult={handleSyncResult}
        onSyncSummary={handleSyncSummary}
        onSyncStart={handleSyncStart}
        storesRefreshKey={storesRefreshKey}
        activeView={activeView}
        onViewChange={setActiveView}
      />

      <SyncProgress syncState={syncState} totalRows={rows.length} />

      <div className={styles.gridWrapper}>
        {activeView === 'excel' ? (
          <ProductGrid
            rows={rows}
            setRows={setRows}
            syncState={syncState}
            isSyncing={isSyncing}
            selectedStore={selectedStore}
            rollbackChangedIndices={rollbackChangedIndices}
            loadKey={loadKey}
            metafieldDefs={metafieldDefs}
            metafieldOwners={metafieldOwners}
            fieldSchema={fieldSchema}
            storeCollectionHandles={collectionHandles}
          />
        ) : (
          <ShopifyView
            rows={rows}
            setRows={setRows}
            selectedStore={selectedStore}
            isSyncing={isSyncing}
            setIsSyncing={setIsSyncing}
            fieldSchema={fieldSchema}
            storeCollectionHandles={collectionHandles}
            metafieldDefs={metafieldDefs}
            metafieldOwners={metafieldOwners}  
            onReload={handleRowsLoaded}
          />
        )}
      </div>

      {showAddStore && (
        <AddStoreModal
          onClose={() => setShowAddStore(false)}
          onAdded={handleStoreAdded}
        />
      )}

      {showRollback && (
        <RollbackPanel
          store={selectedStore}
          onClose={() => setShowRollback(false)}
          onApply={handleRollbackApply}
        />
      )}
    </div>
  )
}