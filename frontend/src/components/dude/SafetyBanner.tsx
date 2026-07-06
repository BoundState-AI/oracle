/**
 * SafetyBanner — crisis/safety rendering for DUDE (spec v0.2 §5, I1).
 *
 * Design contract: when any capture/analyze response or voice safety frame
 * carries safety output, the backend's message and EVERY resource (name,
 * contact, note) render prominently at the top of the page, BEFORE any
 * other content. There is no dismiss button, no collapse, no auto-hide —
 * hiding a crisis resource is the cardinal failure mode of this surface.
 *
 * All copy inside the alert is backend copy rendered verbatim (spec I2);
 * the only strings owned by this component are structural labels.
 */

import { ShieldAlert } from "lucide-react";

import type { SafetyPayload } from "@/lib/dudeApi";

export function SafetyBanner({ alerts }: { alerts: SafetyPayload[] }) {
  if (alerts.length === 0) return null;

  return (
    <div role="alert" className="border-b-2 border-red-500/60 bg-red-950/60">
      <div className="mx-auto max-w-4xl space-y-5 px-6 py-5">
        {alerts.map((alert, index) => (
          <div key={index} className="space-y-4">
            <div className="flex items-start gap-3">
              <ShieldAlert className="mt-0.5 h-6 w-6 shrink-0 text-red-300" />
              {/* Backend copy, verbatim. */}
              <p className="whitespace-pre-wrap text-base font-medium leading-7 text-red-50">
                {alert.message}
              </p>
            </div>
            {alert.resources.length > 0 && (
              <ul className="grid gap-3 sm:grid-cols-2">
                {alert.resources.map((resource, resourceIndex) => (
                  <li
                    key={resourceIndex}
                    className="rounded-xl border border-red-400/40 bg-red-900/40 p-4"
                  >
                    <p className="text-sm font-semibold text-red-50">
                      {resource.name}
                    </p>
                    <p className="mt-1 font-mono text-lg font-bold tracking-wide text-white">
                      {resource.contact}
                    </p>
                    {resource.note && (
                      <p className="mt-1 text-sm leading-6 text-red-100/90">
                        {resource.note}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {alert.flags.length > 0 && (
              <p className="text-xs font-medium uppercase tracking-[0.16em] text-red-300/90">
                {alert.flags.join(" · ")}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
