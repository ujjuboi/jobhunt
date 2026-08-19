# Review — Phase 7 Close UX Gaps

Date: 2026-08-19
Scope: PLAN.md Phase 7 implementation (G1–G5) across `app/`, `screens/`, `db/`, `resume/`,
`search.py`, and `tests/`. Reviewed against the current uncommitted working tree.

## Summary

Phase 7 delivers the G1–G5 UX wiring: profile auto-save for Fit scoring, Jobs→Resume job
selection, Save to Outputs, live Dashboard counts + quick actions, and search across all
enabled sources. The reviewer found 5 medium and 3 low severity issues, all confirmed against
the code. None are blockers for merging, but M1–M5 should be fixed before the Phase is
called done (several directly undercut the Phase's stated goals: live counts, per-source
error surfacing, and correct artifact output).

## Findings

### Medium

1. **Dashboard shows a leftover "- No recent activity" placeholder (duplicate line).**
   `screens/dashboard.py:65` composes an id-less `Static("- No recent activity")` inside
   `#dashboard_content`. `_update_stats` (`dashboard.py:40-45`) removes only statics whose id
   starts with `activity_`, so this placeholder is never removed:
   - With jobs: the stale placeholder line persists *plus* the real activity lines.
   - Without jobs: the compose placeholder plus the one mounted at `dashboard.py:55` renders
     two "- No recent activity" lines.
   Fix: give the compose placeholder an id (e.g. `activity_empty`, matching the existing
   include pattern) so it is removed by the same block, or clear/re-populate the activity
   region explicitly.

2. **Dashboard stats are computed once and never refresh.**
   Textual keeps installed screens mounted across `switch_screen`, and `_update_stats` is
   only called from `on_mount` (`dashboard.py:16-19`). After a search (G5) or any ingestion,
   returning to the Dashboard still shows the startup counts, so G4's "live counts" only
   work on the very first mount. Fix: refresh on the screen-resume event (e.g.
   `on_screen_resume`, verify the exact Textual 8.x handler name) in addition to `on_mount`.

3. **`ResumeScreen._save_outputs` saves output under the *currently* selected job, not the
   job it was generated for.**
   `_last_tailored` / `_last_cover_letter` (`screens/resume.py:165, 209`) are generated
   against the job resolved at click time, but `_save_outputs` (`resume.py:215-232`) re-reads
   `self.app.selected_job_id` and saves under that. Sequence: generate a tailored resume for
   Job A → go to Jobs, select Job B (e.g. to check fit) → Save to Outputs → artifacts land in
   `outputs/{B.company}/{B.id}/` while the content is tailored to A, and the UI reports
   success. Fix: snapshot `job_id`/`company` when generation succeeds and use those in
   `_save_outputs` (optionally warn if the current selection differs).

4. **Search: per-source error notes never surface, and per-source tagging is dead code.**
   - The agent's `search_jobs` tool swallows every exception and returns `[]`
     (`agent/__init__.py` "search_jobs" `except` → `logger.warning` + `return []`), so the
     per-source `try/except` and `failed_sources` collection in `_search`
     (`search.py:101-115`) never fire — including the LinkedIn-without-creds case the plan
     calls out. The failure is only logged, invisible in the TUI.
   - `job.source = source` (`search.py:126-127`) is unreachable: `Job` is a pydantic model
     with a required `source` field, so `hasattr(job, 'source')` is always `True`. If it
     *were* reachable it would tag every job with the last-iterated `source`, which is wrong.
   - The `[source]` tag was also never added to the results rendering
     (`search.py:66-70`), so the source isn't shown either.
   Fixes: add a `raise_errors=False` param to `ToolRegistry.search_jobs` and have the Search
   screen pass `True`, catching per-source errors into a visible note; remove the dead
   `hasattr` block and render `[job.source]` using the source already set by the adapters'
   `normalize_job`; render the failure note in the results textarea instead of `print()`.

5. **Search dedupe silently drops jobs with empty title/company.**
   `search.py:123-129`: `key is None` (empty title or company) → the job is not appended to
   `deduped_jobs`. LinkedIn cards can yield empty company strings (`linkedin.py` normalize,
   `''` allowed), so those results vanish silently. Fix: fall back to `job.id` as the key when
   title/company are empty, retaining the item.

### Low

6. **Dashboard ignores the injected db, falls back to a fresh instance.**
   `DashboardScreen.__init__(db)` stores `self.database`, but `_update_stats`
   (`dashboard.py:24-25`) imports `jobhunt.db` again and constructs a brand-new `JobHuntDB()`
   on the default relative path `jobhunt.db`. `self.database` is dead. It works today only
   because `JobHuntApp` also uses the default path; it breaks as soon as the app passes any
   other path, and it opens a second connection each mount. Note
   `test_dashboard_mount_renders_counts` passes *because* both instances hit the same default
   file — it would not catch a divergence. Fix: use `self.database`.

7. **Missing tests for G2 and G3.**
   PLAN.md G2 calls for a `test_app.py` row-selection test and a guidance-message test;
   G3 calls for an `_save_outputs` test with a mocked `ResumeManager` asserting the
   company/job id passed through. `test_resume_screen.py` covers profile auto-save only;
   `test_app.py` adds the two dashboard tests but no Jobs row-selection test. The new
   job-selection and save-outputs paths are untested. Add: `on_data_table_row_selected` →
   `app.selected_job_id` + status (fake event or mounted table), and `_save_outputs` with a
   mocked manager asserting the generation-time company/job id.

8. **Search result significance (context for G5).**
   Because no companies are configured, the agent's `search_jobs` falls through to
   `adapter.search_jobs(query, limit)`; Greenhouse maps that to `get_jobs(query, limit)`,
   treating the query as an org slug (`greenhouse.py` `search_jobs`), so most queries 404 and
   return nothing. This predates Phase 7, but running the loop over three sources makes it
   more visible: with no `sources.companies` config, all sources return `[]` and the user
   gets "No jobs found". Worth a config hint in the results (e.g. "configure company slugs in
   Settings") as part of G5.

## Context (pre-existing, in scope for "close UX gaps")

- `ResumeScreen.on_button_pressed` (`resume.py:112-118`) and `SearchScreen.on_button_pressed`
  (`search.py:34-37`) don't call `super().on_button_pressed(event)`, so the persistent nav bar
  doesn't work from those screens. Both handlers predate the Phase 7 diff; JobsScreen's old
  handler was (correctly) removed here, which restored nav on that screen. Add the `super()`
  call to Search and Resume.

## Remaining Fix Order

1. Dashboard: use `self.database`; give compose placeholder an id and remove it during
   refresh; refresh on screen-resume (M5, M1, M2).
2. Resume: snapshot generation-time job id/company; `_save_outputs` uses snapshots (M3).
3. Search: `raise_errors` param + visible failure notes + `[source]` tag + id fallback key +
   empty-result hint (M4, M8); nav `super()` call.
4. Nav: add `super().on_button_pressed(event)` to Search/Resume screens.
5. Tests: row-selection + `_save_outputs` coverage (M7); update `tests/test_search.py` for
   source tag, surfaced failures, empty-title retention.
6. Verify: `uv run jobhunt-test`; then `uv run jobhunt-check`.

## Supplementary Review (AI second pass)

### Additional Findings

1. **`search.py:135` — `print()` instead of logger.**
   Phase 6 replaced all `print()` calls with module loggers across the codebase. This one
   was missed. Fix: `logger.warning("Failed sources: %s", failed_sources)`.

2. **`search.py:90` — Import inside method body.**
   `from ..config import get_user_config` is inside `_search()` which runs in a thread.
   While it works, it's inconsistent with the rest of the codebase which imports at module
   level. Move to the top of the file.

3. **`resume.py` — Job resolution logic duplicated 3 times.**
   The same ~15-line block (check `selected_job_id`, call `db.get_job`, populate
   `_selected_job_description`/`_selected_company`/`_selected_job_id`) appears in
   `_generate_tailored_resume`, `_generate_cover_letter`, and `_save_outputs`. Extract to a
   `_resolve_selected_job() -> Optional[Job]` helper that returns the job or None with a
   status message. This also intersects with finding #3 above (snapshotting at generation
   time) — the helper should accept an optional `job_id` override parameter.

4. **`dashboard.py:73-81` — `on_button_pressed` always calls `super()` first.**
   For action buttons (search_jobs_btn, view_jobs_btn, generate_resume_btn), the parent
   handler loops through all nav buttons finding no match — wasted work. Check if the button
   is an action button first, and only call `super()` if it's not.

5. **`dashboard.py:54` — "No recent activity" fallback line missing id.**
   This is a duplicate of finding #1 above. The compose placeholder at `dashboard.py:64` has
   no `id` and survives cleanup. Add `id="activity_empty"` and include it in the filter at
   line 40.

6. **`test_resume_screen.py:45` — Mocking `query_one` is fragile.**
   The test patches `screen.query_one` to a `Mock()`, but `_update_resume_preview` calls
   `self.db.save_profile(db_profile)` which will work with the mock. The assertion
   `mock_db.save_profile.assert_called_once()` passes but doesn't verify the profile
   conversion was correct. The conversion is tested separately in `test_resume.py`, so this
   test is acceptable but the mocking approach is brittle — if `_update_resume_preview` adds
   more `query_one` calls, the mock may break unexpectedly.