import { useState } from 'react'
import { useGoogleLogin } from '@react-oauth/google'
import { LogOut, Key } from 'lucide-react'
import { useAuth } from '../../context/AuthContext'

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID

interface Props {
  title: string
  subtitle?: string
}

function GoogleSignInButton() {
  const { setAuth } = useAuth()

  const login = useGoogleLogin({
    scope: 'https://www.googleapis.com/auth/bigquery.readonly',
    onSuccess: async (tokenResponse) => {
      const accessToken = tokenResponse.access_token
      try {
        const res = await fetch('https://www.googleapis.com/oauth2/v2/userinfo', {
          headers: { Authorization: `Bearer ${accessToken}` },
        })
        const profile = await res.json()
        setAuth(accessToken, {
          name: profile.name ?? profile.email ?? 'User',
          email: profile.email ?? '',
          picture: profile.picture ?? '',
        })
      } catch {
        setAuth(accessToken, { name: 'User', email: '', picture: '' })
      }
    },
    onError: () => console.warn('Google login failed'),
  })

  return (
    <button
      onClick={() => login()}
      className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-white bg-brand-600 hover:bg-brand-700 rounded-lg transition-colors"
    >
      <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
        <path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
        <path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" opacity=".7" />
        <path fill="currentColor" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" opacity=".5" />
        <path fill="currentColor" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" opacity=".3" />
      </svg>
      Sign in with Google
    </button>
  )
}

function ManualTokenInput() {
  const { token, setAuth, clearToken } = useAuth()
  const [showInput, setShowInput] = useState(false)
  const [tokenInput, setTokenInput] = useState('')

  function handleSave() {
    if (tokenInput.trim()) {
      setAuth(tokenInput.trim(), { name: 'API Token', email: '', picture: '' })
      setTokenInput('')
    }
    setShowInput(false)
  }

  if (showInput) {
    return (
      <div className="flex items-center gap-2">
        <input
          type="password"
          placeholder="Paste Google OAuth token…"
          value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleSave() }}
          className="text-xs border border-gray-300 rounded px-3 py-1.5 w-64 focus:outline-none focus:ring-2 focus:ring-brand-500"
          autoFocus
        />
        <button onClick={handleSave} className="text-xs bg-brand-600 text-white px-3 py-1.5 rounded hover:bg-brand-700">Save</button>
        <button onClick={() => setShowInput(false)} className="text-xs text-gray-500 hover:text-gray-700">Cancel</button>
      </div>
    )
  }

  return (
    <>
      {token ? (
        <>
          <span className="text-xs text-green-600 font-medium bg-green-50 px-2 py-1 rounded hidden sm:inline">● Token set</span>
          <button onClick={clearToken} title="Clear token" className="p-1.5 text-gray-400 hover:text-brand-600 hover:bg-brand-50 rounded transition-colors">
            <LogOut size={16} />
          </button>
        </>
      ) : (
        <>
          <span className="text-xs text-amber-600 font-medium bg-amber-50 px-2 py-1 rounded hidden sm:inline">Using env credentials</span>
          <button
            onClick={() => setShowInput(true)}
            title="Set OAuth token manually"
            className="p-1.5 text-gray-400 hover:text-brand-600 hover:bg-brand-50 rounded transition-colors"
          >
            <Key size={16} />
          </button>
        </>
      )}
    </>
  )
}

export function Header({ title, subtitle }: Props) {
  const { token, user, clearToken } = useAuth()

  return (
    <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between shadow-sm">
      <div className="flex items-center gap-3">
        <img src="/logo.png" alt="Logo" className="h-9 w-auto" />
        <div>
          <h1 className="text-base font-bold text-gray-900 leading-tight">{title}</h1>
          {subtitle && <p className="text-xs text-gray-500">{subtitle}</p>}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {CLIENT_ID ? (
          /* Google OAuth flow */
          token && user && user.email ? (
            <>
              <div className="flex items-center gap-2">
                {user.picture && (
                  <img src={user.picture} alt={user.name} className="h-7 w-7 rounded-full border border-gray-200" referrerPolicy="no-referrer" />
                )}
                <div className="hidden sm:block text-right">
                  <p className="text-xs font-medium text-gray-800 leading-tight">{user.name}</p>
                  <p className="text-[10px] text-gray-400 leading-tight">{user.email}</p>
                </div>
              </div>
              <span className="text-xs text-green-600 font-medium bg-green-50 px-2 py-1 rounded hidden sm:inline">● Connected</span>
              <button onClick={clearToken} title="Sign out" className="p-1.5 text-gray-400 hover:text-brand-600 hover:bg-brand-50 rounded transition-colors">
                <LogOut size={16} />
              </button>
            </>
          ) : (
            <GoogleSignInButton />
          )
        ) : (
          /* No client ID — fallback to env credentials + manual token paste */
          <ManualTokenInput />
        )}
      </div>
    </header>
  )
}
