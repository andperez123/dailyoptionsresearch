import { NavLink, Route, Routes } from 'react-router-dom'
import { MarketPulseBar } from './components/MarketPulseBar'
import { HistoryDetailPage } from './pages/HistoryDetailPage'
import { HistoryPage } from './pages/HistoryPage'
import { SportsBoardPage } from './pages/SportsBoardPage'
import { TodayPage } from './pages/TodayPage'

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive ? 'text-terminal-green' : 'text-gray-300 hover:text-terminal-green'

export function App() {
  return (
    <div className="min-h-screen bg-terminal-bg font-mono">
      <header className="border-b border-terminal-border bg-terminal-panel">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between px-4 py-3">
          <div>
            <NavLink to="/" className="text-lg font-bold text-terminal-green">
              DEGEN CATALYST
            </NavLink>
            <p className="text-[10px] text-terminal-muted">
              signal-first intelligence · options · sports · not financial advice
            </p>
          </div>
          <nav className="flex gap-4 text-xs">
            <NavLink to="/" className={navClass} end>
              Terminal
            </NavLink>
            <NavLink to="/sports" className={navClass}>
              Sports
            </NavLink>
            <NavLink to="/history" className={navClass}>
              History
            </NavLink>
          </nav>
        </div>
      </header>

      <MarketPulseBar />

      <main className="mx-auto max-w-[1600px] px-4 py-4">
        <Routes>
          <Route path="/" element={<TodayPage />} />
          <Route path="/sports" element={<SportsBoardPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/history/:date" element={<HistoryDetailPage />} />
        </Routes>
      </main>

      <footer className="border-t border-terminal-border py-3 text-center text-[10px] text-terminal-muted">
        Entertainment only. Observations separated from trade ideas. Data may be delayed.
      </footer>
    </div>
  )
}
