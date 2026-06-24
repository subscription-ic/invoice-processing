import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User, Notification } from '../types'

interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  setAuth: (user: User, token: string) => void
  logout: () => void
}

interface UIState {
  sidebarOpen: boolean
  toggleSidebar: () => void
  notifications: Notification[]
  unreadCount: number
  setNotifications: (notifs: Notification[]) => void
  markRead: (id: string) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      setAuth: (user, token) => {
        localStorage.setItem('access_token', token)
        localStorage.setItem('user', JSON.stringify(user))
        set({ user, token, isAuthenticated: true })
      },
      logout: () => {
        localStorage.removeItem('access_token')
        localStorage.removeItem('user')
        set({ user: null, token: null, isAuthenticated: false })
      },
    }),
    {
      name: 'ap-auth',
      partialize: (state) => ({ user: state.user, token: state.token, isAuthenticated: state.isAuthenticated }),
    }
  )
)

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  notifications: [],
  unreadCount: 0,
  setNotifications: (notifs) =>
    set({ notifications: notifs, unreadCount: notifs.filter((n) => !n.is_read).length }),
  markRead: (id) =>
    set((state) => ({
      notifications: state.notifications.map((n) => (n.id === id ? { ...n, is_read: true } : n)),
      unreadCount: Math.max(0, state.unreadCount - 1),
    })),
}))