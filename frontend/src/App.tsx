import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store/authStore'
import LoginPage from '@/pages/auth/LoginPage'
import DashboardPage from '@/pages/dashboard/DashboardPage'
import SettingsPage from '@/pages/settings/SettingsPage'
import LogsPage from '@/pages/logs/LogsPage'
import RuntimeLogsPage from '@/pages/logs/RuntimeLogsPage'
import ItemsPage from '@/pages/items/ItemsPage'
import AppLayout from '@/components/layout/AppLayout'

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<PrivateRoute><AppLayout /></PrivateRoute>}>
        <Route index element={<DashboardPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="items" element={<ItemsPage />} />
        <Route path="logs" element={<LogsPage />} />
        <Route path="runtime-logs" element={<RuntimeLogsPage />} />
      </Route>
    </Routes>
  )
}
