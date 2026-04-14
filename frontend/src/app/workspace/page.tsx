/**
 * OracleWorkspacePage — authenticated workspace entry point.
 * Thin page wrapper that delegates all state and UI to the OracleWorkspace component.
 */

import { OracleWorkspace } from "@/components/OracleWorkspace";

export default function OracleWorkspacePage() {
  return <OracleWorkspace />;
}
