import { create } from 'zustand'

interface AuthState {
  isAuthenticated: boolean
  username: string | null
  login: (accessToken: string, refreshToken: string, username: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: !!localStorage.getItem('access_token'),
  username: null,
  login: (accessToken, refreshToken, username) => {
    localStorage.setItem('access_token', accessToken)
    localStorage.setItem('refresh_token', refreshToken)
    set({ isAuthenticated: true, username })
  },
  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    set({ isAuthenticated: false, username: null })
  },
}))
