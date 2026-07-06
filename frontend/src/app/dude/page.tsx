/**
 * DudePage — authenticated entry point for DUDE (decision support under
 * uncertainty). Thin page wrapper that delegates all state and UI to
 * DudeWorkspace, mirroring the HearthPage pattern.
 */

import { DudeWorkspace } from "@/components/dude/DudeWorkspace";

export default function DudePage() {
  return <DudeWorkspace />;
}
