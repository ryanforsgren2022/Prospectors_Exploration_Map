# Repository workflow rules

## Execution

- When the user asks for a change or agrees to a proposed fix, continue through implementation and verification without stopping at an acknowledgment or plan.
- Treat corrections and follow-up messages as direction to continue the active task unless the user explicitly asks to stop.
- If an external dependency blocks completion, finish every safe in-scope step, identify the exact blocker, and ask only for the missing access or decision.
- Do not describe an unverified architecture as fact; inspect the implementation and data before choosing a fix.

## Publishing

- All publishing must deploy directly to the production environment.
- Never create, stage, or promote a preview deployment for this project.
- For Vercel CLI releases, use an explicit production command such as `vercel deploy --prod`.
- Build and verify locally before publishing, but do not use a preview deployment as a verification step.

## Uniformity

- Keep shared frontend behavior, state layers, styles, zoom thresholds, visibility rules, and loading lifecycles uniform across all supported states.
- Use shared configuration and shared code paths instead of state-specific implementations or duplicated fallback layers.
- Do not introduce a per-state exception unless the user explicitly requests and approves it.
- Add regression coverage that fails when supported states diverge from the shared implementation.


## VM builds and downloads

- Run VM builds sequentially, not concurrently.
- Run downloads in parallel.
- Limit all VM work, including concurrent processes and downloads, to a combined three CPU cores and 7 GiB of memory. Treat remaining VM resources as unavailable.
