/**
 * DudeCasePage — one DUDE case: capture, analyze, safety surface.
 * Thin server wrapper that resolves the dynamic segment and delegates to
 * CaseWorkspace (client), mirroring the HearthPage pattern.
 */

import { CaseWorkspace } from "@/components/dude/CaseWorkspace";

export default async function DudeCasePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <CaseWorkspace caseId={id} />;
}
