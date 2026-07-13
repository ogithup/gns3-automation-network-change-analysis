import { Link, Route, Routes } from "react-router-dom";

import { PlaceholderPage } from "./pages/PlaceholderPage";

export default function App() {
  return (
    <main className="app-shell">
      <header className="hero">
        <p className="eyebrow">NetTwin AI</p>
        <h1>GNS3 Automation and Network Change Impact Analysis</h1>
        <p className="lede">
          Sprint 0 UI placeholder for the future operator workflow.
        </p>
        <nav className="nav">
          <Link to="/">Overview</Link>
          <Link to="/connection">GNS3 Connection</Link>
          <Link to="/topology">Topology Builder</Link>
        </nav>
      </header>

      <Routes>
        <Route
          path="/"
          element={
            <PlaceholderPage
              title="Platform Overview"
              description="This screen will evolve into the main workflow dashboard."
            />
          }
        />
        <Route
          path="/connection"
          element={
            <PlaceholderPage
              title="GNS3 Connection"
              description="This screen will validate GNS3 REST and WebSocket connectivity."
            />
          }
        />
        <Route
          path="/topology"
          element={
            <PlaceholderPage
              title="Visual Topology Builder"
              description="This screen will host React Flow based topology editing."
            />
          }
        />
      </Routes>
    </main>
  );
}

