import { NavLink, Route, Routes } from 'react-router-dom'
import { MarketPulseBar } from './components/MarketPulseBar'
import { HistoryDetailPage } from './pages/HistoryDetailPage'
import { HistoryPage } from './pages/HistoryPage'
import { SportsBoardPage } from './pages/SportsBoardPage'
import { TodayPage } from './pages/TodayPage'

const navClass = ({ isActive }: { isActive: boolean }) =>
  isActive
    ? 'text-research-ink after:absolute after:inset-x-0 after:-bottom-[13px] after:h-0.5 after:rounded-full after:bg-research-green'
    : 'text-research-muted hover:text-research-ink'

export function App() {
  return (
    <div className="min-h-screen font-sans text-research-ink">
      <header className="sticky top-0 z-40 border-b border-research-line/80 bg-research-surface/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-3.5">
          <NavLink to="/" className="group">
            <span className="text-lg font-semibold tracking-tight text-research-ink transition group-hover:text-research-green">
              Catalyst
            </span>
            <span className="ml-2 text-sm font-medium text-research-muted">Research</span>
          </NavLink>
          <nav className="flex gap-6 text-sm font-medium">
            <NavLink to="/" className={({ isActive }) => `relative ${navClass({ isActive })}`} end>
              Today
            </NavLink>
            <NavLink to="/sports" className={navClass}>
              Sports
            </NavLink>
            <NavLink to="/history" className={navClass}>
              Archive
            </NavLink>
          </nav>
        </div>
      </header>

      <MarketPulseBar />

      <main className="mx-auto max-w-5xl px-5 py-8">
        <Routes>
          <Route path="/" element={<TodayPage />} />
          <Route path="/sports" element={<SportsBoardPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/history/:date" element={<HistoryDetailPage />} />
        </Routes>
      </main>

      <footer className="mx-auto max-w-5xl px-5 pb-10 pt-4 text-center text-xs text-research-muted">
        For research and entertainment only. Not financial advice. Data may be delayed.
      </footer>
    </div>
  )
}
