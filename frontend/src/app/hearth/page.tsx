/**
 * HearthPage — authenticated entry point for the HEARTH DocScrubber.
 * Thin page wrapper that delegates all state and UI to ScrubWorkspace,
 * mirroring the OracleWorkspacePage pattern.
 */

import { ScrubWorkspace } from "@/components/hearth/ScrubWorkspace";

export default function HearthPage() {
  return <ScrubWorkspace />;
}
