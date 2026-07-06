/**
 * DudePage — entry point for DUDE: the "something happened" capture
 * screen (mobile vision v0.1). Thin page wrapper that delegates all
 * state and UI to DudeWorkspace, mirroring the HearthPage pattern.
 */

import { DudeWorkspace } from "@/components/dude/DudeWorkspace";

export default function DudePage() {
  return <DudeWorkspace />;
}
