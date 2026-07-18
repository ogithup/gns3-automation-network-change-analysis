import { Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/AppLayout";
import {
  AddressingPageV2,
  ApprovalPage,
  AuditPage,
  ChangeBuilderPage,
  ComparisonPage,
  ConfigurationPageV2,
  ConnectionPage,
  DeploymentPage,
  LiveTopologyPage,
  OverviewPageV2,
  ProjectsPageV2,
  RiskPage,
  RollbackPage,
  TopologyBuilderPageV2,
  ValidationPage,
} from "./pages/WorkflowPages";

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<OverviewPageV2 />} />
        <Route path="/connection" element={<ConnectionPage />} />
        <Route path="/projects" element={<ProjectsPageV2 />} />
        <Route path="/topology" element={<TopologyBuilderPageV2 />} />
        <Route path="/addressing" element={<AddressingPageV2 />} />
        <Route path="/configuration" element={<ConfigurationPageV2 />} />
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
