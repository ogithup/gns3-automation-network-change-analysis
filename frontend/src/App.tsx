import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import {
  AddressingPage,
  ApprovalPage,
  AuditPage,
  ChangeBuilderPage,
  ComparisonPage,
  ConfigurationPage,
  ConnectionPage,
  DeploymentPage,
  LiveTopologyPage,
  OverviewPage,
  ProjectsPage,
  RiskPage,
  RollbackPage,
  TopologyBuilderPage,
  ValidationPage,
} from "./pages/WorkflowPages";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/connection" element={<ConnectionPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/topology" element={<TopologyBuilderPage />} />
        <Route path="/addressing" element={<AddressingPage />} />
        <Route path="/configuration" element={<ConfigurationPage />} />
        <Route path="/deployment" element={<DeploymentPage />} />
        <Route path="/live-topology" element={<LiveTopologyPage />} />
        <Route path="/validation" element={<ValidationPage />} />
        <Route path="/changes" element={<ChangeBuilderPage />} />
        <Route path="/comparison" element={<ComparisonPage />} />
        <Route path="/risk" element={<RiskPage />} />
        <Route path="/approval" element={<ApprovalPage />} />
        <Route path="/rollback" element={<RollbackPage />} />
        <Route path="/audit" element={<AuditPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
