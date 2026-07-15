import { NavLink, Route, Routes } from 'react-router-dom'
import { MarketPulseBar } from './components/MarketPulseBar'
import { HistoryDetailPage } from './pages/HistoryDetailPage'
import { HistoryPage } from './pages/HistoryPage'
import { SportsBoardPage } from './pages/SportsBoardPage'
import { TodayPage } from './pages/TodayPage'

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? 'rounded-md bg-terminal-green/10 px-3 py-1.5 font-semibold text-terminal-green'
    : 'rounded-md px-3 py-1.5 text-slate-300 transition hover:bg-white/5 hover:text-white'

export function App() {
  return (
    <div className="min-h-screen bg-transparent font-sans text-slate-100">
      <header className="border-b border-terminal-border bg-terminal-panel/90 shadow-lg shadow-black/20 backdrop-blur">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between px-5 py-4">
          <div>
            <NavLink to="/" className="font-mono text-lg font-bold tracking-wide text-terminal-green">
              DEGEN CATALYST
            </NavLink>
            <p className="mt-0.5 text-[10px] text-terminal-muted">
              signal-first intelligence · options · sports · not financial advice
            </p>
          </div>
          <nav className="flex gap-1 text-xs">
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

      <main className="mx-auto max-w-[1600px] px-5 py-6">
        <Routes>
          <Route path="/" element={<TodayPage />} />
          <Route path="/sports" element={<SportsBoardPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/history/:date" element={<HistoryDetailPage />} />
        </Routes>
      </main>

      <footer className="mt-6 border-t border-terminal-border py-4 text-center text-[10px] text-terminal-muted">
        Entertainment only. Observations separated from trade ideas. Data may be delayed.
      </footer>
    </div>
  )
}
