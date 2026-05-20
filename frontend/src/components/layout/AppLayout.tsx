import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Menu, Bot } from 'lucide-react'
import Sidebar from './Sidebar'

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  useEffect(() => {
    if (!sidebarOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSidebarOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sidebarOpen])

  return (
    <div className="min-h-screen bg-dark-950">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="relative min-h-screen lg:ml-64 transition-all duration-300">
        {/* Mobile topbar */}
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-dark-700/60 bg-dark-900/80 px-4 py-3 backdrop-blur-xl lg:hidden">
          <button
            onClick={() => setSidebarOpen(true)}
            className="flex h-9 w-9 items-center justify-center rounded-lg text-dark-300 hover:bg-dark-800 hover:text-gray-100"
            aria-label="打开菜单"
          >
            <Menu size={20} />
          </button>
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-primary shadow-glow">
              <Bot size={16} className="text-white" />
            </div>
            <span className="text-sm font-bold text-gray-50">XianyuAutoAgent</span>
          </div>
        </header>

        <main className="p-4 md:p-6 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
