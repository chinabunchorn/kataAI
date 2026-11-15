# KataAI — frontend

A React + TypeScript + Vite startup-style landing page for the project's question-and-CSV workflow. Navy blue and white, oversized **KataAI** typography, a full-height opening, and a separate white input section below the fold.

## Run

Use Node.js 26 (tested with 26.3.1) and npm. Supported alternatives for the full test toolchain are Node 22.22.2+ within 22.x or Node 24.15+ within 24.x.

```bash
cd /Users/nuttananapirakcheewan/kataAI/frontend
npm ci
npm run dev
```

Open the printed localhost URL, normally `http://127.0.0.1:5173`. The server is bound to loopback, not the LAN. `npm run build` creates the production bundle; `npm run preview` serves it locally.

## Experience

- The page opens with a large KataAI wordmark and startup-style introduction, not a dashboard or developer inspector.
- **Start exploring**, **Try KataAI**, and **Scroll to begin** navigate to the form with a gentle 1.4-second scroll. No forced automatic scrolling occurs on page load.
- Wheel, touch and keyboard input can interrupt the animated navigation. Reduced-motion preferences select immediate navigation without decorative animation.
- The form contains a message textbox and a CSV drag/drop box, with file browsing, sample inputs, a five-row data preview and reset.
- **Check my request** validates the inputs and shows a simple local readiness confirmation. It does not claim the data was analyzed.
- **No payload/schema/JSON inspector, Copy JSON button, execution timeline or fake AI answer is displayed.** Payload examples belong in the project handoff/chat rather than the product UI.

## Local-only boundary

Questions must be non-empty and at most 4,000 JavaScript UTF-16 code units. The frontend accepts one UTF-8 CSV no larger than 128 KiB, with non-empty unique headers, consistent row width, at least one data row, at most 100 columns and at most 10,000 data rows. Quoted fields and a UTF-8 BOM are supported; malformed input produces actionable feedback.

CSV cell values are rendered as text, not executed. Data is kept in browser memory, not localStorage, IndexedDB or cookies. Editing/removing/replacing an input clears the prior readiness state. Asynchronous selection tracking prevents a superseded read from restoring an old file.

No backend adapter, API client, authentication, upload, model call, generated-code execution, Kubernetes deployment, persistence or clipboard action is included. The unchanged original File and typed metadata are prepared internally for a later backend integration; they are not rendered on the page. See [FRONTEND-PAYLOAD-HANDOFF.md](FRONTEND-PAYLOAD-HANDOFF.md) for the proposed server handoff and trust boundaries.

## Checks

```bash
npm test
npm run build
npm run format:check
npx playwright install chromium
npm run test:e2e -- --workers=2
```

Browser coverage includes hero-first layout, scroll duration/interruption, reduced motion, keyboard access, drag/drop, validation, no network submission, safe text rendering, absence of a schema inspector, responsive overflow, and axe WCAG A/AA checks. Screenshots are under `evidence/v2-*`. Automated checks do not certify accessibility or sandbox security; Safari, Firefox and real mobile hardware are not covered.

## Files

- `src/App.tsx`: landing page, gentle navigation and local input state.
- `src/styles.css`: navy/white design, oversized wordmark and responsive layouts.
- `src/lib/csv.ts`: bounded browser-only CSV inspection.
- `src/lib/submission.ts`: internal typed metadata preparation, no transport.
- `src/*.test.tsx`, `src/lib/*.test.ts`: component/validation tests.
- `e2e/workspace.spec.ts`: real-browser interaction/accessibility tests.
- `design-archive/workspace-v1.zip`: previous dashboard-style source and documentation, preserved before this redesign.

KataAI is the course project's UI label, not an official Kata Containers product or a claim of a running sandbox. The original specification and research guide remain unchanged.
