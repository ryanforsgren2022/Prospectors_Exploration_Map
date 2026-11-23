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


## Automatic updater resources

- Automatic updater jobs share a total limit of one CPU core and 2 GiB of RAM, including their child processes and downloads.
- These limits apply to the automatic updater, not to the live site or other repository/VM work.
- Let the validation already running on November 21, 2026 finish before applying the changed updater limits.
