import { getAccessToken } from '../api'
import { Navigate } from 'react-router-dom'

export default function AuthGuard({ children }) {
    const token = getAccessToken()
    if (!token) return <Navigate to="/login" replace />
    return children
}