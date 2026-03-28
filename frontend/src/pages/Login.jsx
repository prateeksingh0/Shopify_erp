import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register } from '../api'
import styles from './Login.module.css'

export default function Login() {
    const navigate = useNavigate()
    const [mode, setMode] = useState('login')   // 'login' | 'register'
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [email, setEmail] = useState('')
    const [error, setError] = useState('')
    const [loading, setLoading] = useState(false)

    async function handleSubmit() {
        if (!username || !password) { setError('Username and password required'); return }
        setLoading(true)
        setError('')
        try {
            if (mode === 'login') {
                await login(username, password)
            } else {
                await register(username, password, email)
            }
            navigate('/')
        } catch (e) {
            setError(e.message)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className={styles.wrapper}>
            <div className={styles.card}>
                <h1 className={styles.title}>Shopify ERP</h1>

                <div className={styles.tabs}>
                    <button
                        className={mode === 'login' ? styles.activeTab : styles.tab}
                        onClick={() => { setMode('login'); setError('') }}
                    >Login</button>
                    <button
                        className={mode === 'register' ? styles.activeTab : styles.tab}
                        onClick={() => { setMode('register'); setError('') }}
                    >Register</button>
                </div>

                <input
                    className={styles.input}
                    placeholder="Username"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleSubmit()}
                />

                {mode === 'register' && (
                    <input
                        className={styles.input}
                        placeholder="Email (optional)"
                        value={email}
                        onChange={e => setEmail(e.target.value)}
                    />
                )}

                <input
                    className={styles.input}
                    type="password"
                    placeholder="Password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleSubmit()}
                />

                {error && <p className={styles.error}>{error}</p>}

                <button
                    className={styles.btn}
                    onClick={handleSubmit}
                    disabled={loading}
                >
                    {loading ? 'Please wait...' : mode === 'login' ? 'Login' : 'Register'}
                </button>
            </div>
        </div>
    )
}