import { NavLink, Outlet } from "react-router-dom";

import { useWorkflowStore } from "../app/workflowStore";
import { StatusPill } from "./Cards";

const navItems = [
  { to: "/", label: "Overview" },
  { to: "/connection", label: "GNS3 Connection" },
  { to: "/projects", label: "Project List" },
  { to: "/topology", label: "Topology Builder" },
  { to: "/addressing", label: "IP Plan" },
  { to: "/configuration", label: "Configuration Preview" },
  { to: "/deployment", label: "Deployment Progress" },
  { to: "/live-topology", label: "Live Topology" },
  { to: "/validation", label: "Validation Results" },
  { to: "/changes", label: "Change Builder" },
  { to: "/comparison", label: "Before / After" },
  { to: "/risk", label: "Impact and Risk" },
  { to: "/approval", label: "Approval" },
  { to: "/rollback", label: "Rollback" },
  { to: "/audit", label: "Audit History" },
];

export function AppLayout() {
  const {
    topologyDraft,
    activeDeployment,
    activeChange,
    deployments,
    changes,
  } = useWorkflowStore();

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <p>NetTwin AI</p>
          <h1>Visual Network and Change Management</h1>
          <span>React workflow UI for GNS3 automation and impact analysis.</span>
        </div>

        <nav className="sidebar__nav">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `sidebar__link ${isActive ? "sidebar__link--active" : ""}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__status">
          <div>
            <span>Draft project</span>
            <strong>{topologyDraft.project.name}</strong>
          </div>
          <StatusPill value={`${topologyDraft.devices.length} devices`} tone="info" />
          <StatusPill value={`${deployments.length} deployments`} tone="neutral" />
          <StatusPill value={`${changes.length} changes`} tone="neutral" />
          {activeDeployment ? <StatusPill value={`Deploy: ${activeDeployment.status}`} tone="warning" /> : null}
          {activeChange ? <StatusPill value={`Change: ${activeChange.status}`} tone="success" /> : null}
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div>
            <p className="eyebrow">Sprint 15</p>
            <h2>End-to-end operator workflow</h2>
          </div>
          <div className="topbar__summary">
            <span>{topologyDraft.vlans.length} VLANs</span>
            <span>{topologyDraft.links.length} links</span>
            <span>{topologyDraft.endpoints.length} endpoints</span>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
