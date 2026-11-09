# LT pool and scheduling diagnostics

This diagnostic branch preserves HTTPX client limits, proxy/TLS behavior, retries,
timeouts, and the existing four-AC/eight-Runners topology.

`GALILEO_LUNA_HTTP_DIAGNOSTICS=true` tags only Luna HTTP requests and measures
HTTPcore pool enqueue-to-connection-assignment, assignment-to-wait entry (pool
housekeeping), and assignment/wait-entry-to-resumption. It also measures time
before pool entry and after response-body completion. These intervals overlap
existing inclusive transport timings; do not add their percentiles. The bounded
private-method adapter is tested against the deployed HTTPcore 1.0.9 and must be
revalidated when HTTPcore changes. The disabled path adds no pool hooks.

`GALILEO_RUNTIME_PROFILE_ENABLED=true` creates an idle diagnostic thread. Creating
`/tmp/ac-runtime-profile.trigger` inside an owned AC container starts one bounded
50 Hz profile (60 seconds by default; `GALILEO_RUNTIME_PROFILE_SECONDS` is clamped
to 1–90). It writes `/tmp/ac-runtime-profile.json` with mode 0600, containing only
Python stack locations, thread names, and aggregate counters. No locals,
arguments, requests, credentials, or public endpoint are collected. CPU weights
are approximate interval CPU attributed to the sampled main-thread Python stack;
native stacks and short calls cannot be resolved. Sampling can perturb timing;
compare the profile window with the unsampled parts of the same run.

Keep connection limits and load fixed during this diagnostic run. A pool limit
increase is warranted only if enqueue-to-assignment wait is material; scheduling
and CPU evidence should determine the next change.
