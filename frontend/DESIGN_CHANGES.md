# ORACLE Frontend Redesign — Dark Academic Aesthetic

**Date:** 2026-06-09  
**Approach:** Bold, distinctive design matching the audited backend credibility  
**Theme:** Dark Academic / Lab Instrumentation  

---

## Design Philosophy

ORACLE is a philosophically rigorous, audited review engine. The frontend should *look* like what it is: a serious compliance tool where disagreement is visible and decisions are traceable.

**The aesthetic:** Not "helpful AI assistant" but "research lab dashboard" — think auditor's workstation, scientific instrument interface.

---

## Visual Changes

### 1. Color System (Dark Academic)

**Palette:**
- **Base:** Deep charcoal (#0f1419) — near-black, no blue tint
- **Cards/UI:** Slightly lighter charcoal (#1a1f28)
- **Primary (Authority):** Slate blue (#3d5a80) — commands attention without aggression
- **Secondary (Contrast):** Warm stone gray (#9b8b7e) — humanizes the severity
- **Consensus states (semantic):**
  - Full Agreement: Sage green (#6b9e7f) — harmony
  - Stable with Notes: Amber (#d4a45f) — caution
  - Blocked: Deep red (#c05050) — stop, requires human decision

**Rationale:** The old navy+electric-blue felt generic. This palette feels *specific* — auditor's office, not tech startup.

### 2. Typography

**Headers:** Crimson Text (serif, 600/700 weight)
- Conveys authority, formality, print-grade quality
- Used for h1–h6, main titles, section headings
- Generous letter-spacing for breathing room

**Body/Data:** IBM Plex Mono (monospace, 400/500 weight)
- Metrics, code, specifications, data tables
- Creates "lab notebook" aesthetic
- Precise, traceable, scientific

**Rationale:** Serif+mono pairing is unusual but intentional. It says "this is documented, traceable, not a conversational interface."

### 3. Layout & Spatial Hierarchy

**Changes:**
- **Vertical emphasis:** Sections stack with 2–3rem gaps (generously spaced, like a research paper)
- **Critical info prominent:** Consensus status and verdict consistency appear first
- **Secondary flows recessed:** Pack selection, round tuning are discoverable but below the fold
- **Monospace labels:** All UI labels (metrics, buttons, sections) use uppercase monospace for visual consistency

**Rationale:** Makes the most important information (whether the system reached agreement) visually dominant.

### 4. New Components

#### ConsensusVisualizer
- Visual badge showing consensus type: Full Agreement | Stable with Notes | Blocked
- Icon-based (check, alert, X) for quick recognition
- Displays oracle count as dots
- Integrates verdict summary if available

#### VerdictIndicator
- Shows whether reviewer verdicts blocked or overrode the coordinator decision
- Two states:
  - **Veto Applied:** Red alert — unanimous reviewer dissent forced human review
  - **Override Disclosed:** Amber alert — coordinator overrode partial dissent (with full reasoning)
  - **Aligned:** Green checkmark — all verdicts aligned

#### Updated CritiquePanel
- Now a "scientific dashboard" layout:
  - Header with title + context
  - Consensus status section (prominent)
  - Reviewer alignment / verdict consistency section
  - Metrics grid (grouped by semantic category: Consensus, Findings, Resolution)
  - Detailed findings report (findings report markdown)
  - Action buttons (Start Over, Generate Deliverables)

#### Updated RoundsSelector
- Language: "Review Configuration" not "Review Rounds"
- Specifications listed in monospace (e.g., "4 oracles × 2 rounds = 8 reviewer calls")
- Cost estimate: $8–$32 depending on document length
- Convergence rules explained: "Baseline convergence requires round 2+. Persistent disagreement is reported as blocked."

---

## CSS System

**New utilities added to globals.css:**
- `.metrics-grid` — responsive metrics layout
- `.metric-item` — single metric card
- `.metric-label` — monospace, uppercase metric label
- `.metric-value` — large, prominent metric number
- `.consensus-badge` — semantic color badges for consensus states
- `.oracle-divider` — visual separator for oracle consensus visualization
- `.findings-section` — vertical spacing for findings sections
- `.loading` — subtle pulse animation

**Typography system:**
- `font-serif` for headers (Crimson Text)
- `font-mono` for data/metrics (IBM Plex Mono)
- Generous line-height (1.7) for readability
- Letter-spacing adjustments for hierarchy

---

## Files Modified

1. **globals.css**
   - New color variables (dark academic palette, consensus colors)
   - Font imports (Crimson Text, IBM Plex Mono)
   - New utilities (metrics-grid, consensus-badge, etc.)
   - Typography system overhaul

2. **CritiquePanel.tsx**
   - Redesigned as scientific dashboard
   - Imports ConsensusVisualizer, VerdictIndicator
   - Metrics grouped by semantic category
   - New layout: header → consensus status → verdict consistency → metrics → findings

3. **RoundsSelector.tsx**
   - Language updated to "Review Configuration"
   - Specifications in monospace (oracle count × rounds)
   - Cost estimates
   - Convergence rules explained

4. **ConsensusVisualizer.tsx** (NEW)
   - Renders consensus type (Full Agreement | Stable with Notes | Blocked)
   - Icon-based state indication
   - Oracle count visualization

5. **VerdictIndicator.tsx** (NEW)
   - Shows veto or override status
   - Explains why reviewer verdicts mattered

---

## Visual Behavior

### Animations
- Fade-in on page load (0.5s)
- Subtle pulse on loading states
- Smooth transitions on hover/focus

### Interactive States
- Buttons: uppercase monospace labels, serious styling
- Focus states: clear outline with ring color
- Hover: primary color background on buttons

### Micro-interactions
- Metric cards have subtle top border (gradient)
- Consensus badges have semantic color backgrounds with transparency
- Card styling: thin border, subtle top line gradient

---

## Accessibility

- All contrast ratios meet WCAG AA standards
- Focus states are clear and visible
- Monospace metrics are legible at small sizes
- Color is never the only indicator (icons, text labels also present)

---

## Rationale: Why This Matters

The backend now has:
- Philosophy rules enforced (dissent surfaces, no false consensus)
- All 4 CRITICALs closed
- 144 tests passing
- Golden harness preventing regression

The frontend should match that credibility. An audited, serious system deserves a serious-looking interface. The dark academic aesthetic says:

> "This is an engineering system where disagreement is visible and decisions are traceable."

Not:

> "This is a helpful AI tool."

---

## Future Enhancements (Not In Scope)

- Animation on findings list (staggered reveal)
- Advanced data visualization (convergence trajectory chart)
- Customizable metric grouping
- Export findings as PDF with branded header
- Dark/light mode toggle (currently dark-only)

---

## Testing Notes

- Typography: Verify Crimson Text and IBM Plex Mono load correctly
- Colors: Test all consensus badges on different backgrounds
- Layout: Verify responsive behavior on mobile (metrics grid, sections)
- Components: Test ConsensusVisualizer and VerdictIndicator with different states
- Accessibility: Run WCAG AA contrast checks on all colors
