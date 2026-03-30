import { BrowserRouter, Routes, Route } from 'react-router-dom'
import AuthGuard from './components/AuthGuard'
import Layout from './components/Layout'
import Login from './pages/Login'
import Home from './pages/Home'
import Products from './pages/Products'
import Logs from './pages/Logs'
import Settings from './pages/Settings'
import Blogs from './pages/Blogs'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<AuthGuard><Layout /></AuthGuard>}>
          <Route index element={<Home />} />
          <Route path="products" element={<Products />} />
          <Route path="blogs" element={<Blogs />} />
          <Route path="logs" element={<Logs />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}