import React, { createContext, useContext, useState, useCallback } from 'react'

interface UserProfile {
  name: string
  email: string
  picture: string
}

interface AuthContextValue {
  token: string
  user: UserProfile | null
  setAuth: (token: string, user: UserProfile) => void
  clearToken: () => void
}

const AuthContext = createContext<AuthContextValue>({
  token: '',
  user: null,
  setAuth: () => {},
  clearToken: () => {},
})

// Bump this when OAuth scopes change — clears any cached token that was
// issued with the old (insufficient) scopes so users aren't silently broken.
const SCOPE_VERSION = '2'

function migrateStoredAuth() {
  if (localStorage.getItem('oauth_scope_version') !== SCOPE_VERSION) {
    localStorage.removeItem('google_oauth_token')
    localStorage.removeItem('google_user')
    localStorage.setItem('oauth_scope_version', SCOPE_VERSION)
  }
}

function loadStoredUser(): UserProfile | null {
  try {
    const raw = localStorage.getItem('google_user')
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  // Run once on module load — clears stale tokens from old scope versions.
  migrateStoredAuth()

  const [token, setTokenState] = useState<string>(() => localStorage.getItem('google_oauth_token') ?? '')
  const [user, setUserState] = useState<UserProfile | null>(loadStoredUser)

  const setAuth = useCallback((t: string, u: UserProfile) => {
    localStorage.setItem('google_oauth_token', t)
    localStorage.setItem('google_user', JSON.stringify(u))
    setTokenState(t)
    setUserState(u)
  }, [])

  const clearToken = useCallback(() => {
    localStorage.removeItem('google_oauth_token')
    localStorage.removeItem('google_user')
    setTokenState('')
    setUserState(null)
  }, [])

  return (
    <AuthContext.Provider value={{ token, user, setAuth, clearToken }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
