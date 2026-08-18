# Review — Phase 4 Resume + Cover Letters

Date: 2026-08-18 (updated)
Scope: `resume/` module, `ResumeScreen`, `plan/PLAN.md` updates

## Summary

Phase 4 delivers a `resume/` module (DOCX parser, tailoring, cover letters, PDF conversion) and a
rewritten `ResumeScreen`. Initial review found 18 issues across critical, high, medium, and minor
severity. 11 have been fixed. The most critical remaining issue is a missing `List` import in
`profile_parser.py` that crashes the entire resume module on import.

## Findings

### Critical

1. ~~**`ResumeScreen.compose()` breaks the screen layout.**~~ **FIXED** — screen now uses `_get_content()` pattern.

2. ~~**`ResumeManager.__init__` hard-fails on missing LibreOffice, blocking all screen mount.**~~ **FIXED** — check deferred to `generate_pdf()`.

3. ~~**`resume/main.py` is an exact duplicate of `resume/__init__.py`.**~~ **FIXED** — file deleted.

### High

4. **Duplicate `Profile` model — two conflicting definitions.** **OPEN**
   `src/jobhunt/models/__init__.py:28-39` defines a `Profile` with `experience: List[Dict[str, Any]]`
   and `education: List[Dict[str, Any]]`. `src/jobhunt/resume/profile_parser.py:25-35` defines a
   different `Profile` with `experience: List[ResumeSection]` and `education: List[ResumeSection]`.
   The two models serve different consumers (db/scoring/agent vs resume module) and are never
   interchanged, so this is an acceptable design — but should be documented.

5. ~~**Test files are outside pytest and provide no coverage.**~~ **FIXED** — root-level files deleted.
   `tests/test_resume.py` exists with proper pytest assertions. Note: `test_resume_manager_instantiation`
   will fail if `../Resumes/` does not exist on the test machine.

6. ~~**Relative `base_resume_dir` resolves against CWD, not project root.**~~ **FIXED** — now anchored
   via `Path(__file__).parent.parent.parent`.

7. ~~**Stale `../Resume/` vs `../Resumes/` mismatch with PLAN.md.**~~ **FIXED** — PLAN.md:110,139 both
   use `../Resumes/` consistently.

### Medium

8. ~~**Section header detection is too greedy.**~~ **FIXED** — `profile_parser.py:136` now uses
   `re.search(r'\b' + re.escape(word) + r'\b', name)`.

9. ~~**`is_experience_timeline` is extremely broad.**~~ **FIXED** — `profile_parser.py:167` now requires
   `r'\d{4}\s*-\s*\d{4}'`.

10. **`_update_skills` adds random words as skills.** **OPEN** (acknowledged placeholder)
    `tailor.py:74-86` — stopword list expanded (line 76-78) but still adds arbitrary words > 3 chars.
    Will be replaced by LLM-based tailoring.

11. **`on_select_changed` fires during `on_mount`, causing duplicate preview load.** **OPEN**
    `screens/resume.py:48-49` — `select.value = resumes[0]` fires `on_select_changed` which calls
    `_update_resume_preview`, then line 49 calls it again explicitly. Remove the explicit call.

12. ~~**`os.path.dirname(pdf_path)` returns empty string without directory component.**~~ **FIXED** —
    `pdf_converter.py:32` now wraps with `os.path.abspath()`.

13. ~~**Binary lookup uses `which` — not portable.**~~ **FIXED** — `pdf_converter.py:24,62` now use
    `shutil.which()`.

### Minor

14. **Unused imports in `screens/resume.py`.** **OPEN** — `Vertical` (line 6) and `ComposeResult`
    (line 7) are imported but never used.

15. **Unused imports in `resume/__init__.py`.** **OPEN** — `json` (line 4) and `tempfile` (line 5)
    are imported but never used.

16. **Missing `List` import in `profile_parser.py` — crash bug.** **OPEN — CRITICAL**
    `profile_parser.py:7` imports `Dict, Any, Optional` but not `List`. `List` is used on 15+ lines
    (21, 30-34, 36, 170, 193, 205, 219, 225, 261). This causes `NameError: name 'List' is not
    defined` on import — the entire resume module is broken.

17. ~~**`cover_letter.py:37` has hardcoded `[Company]` in template body.**~~ **FIXED** — now uses
    `{company_name if company_name else 'your company'}`.

18. **`pdf_converter.py` prints errors to stdout + dead `raise` statements.** **OPEN**
    Lines 25, 42 raise `RuntimeError`, but lines 49-51 catch `except Exception` and convert to
    `print() + return False`. The `raise` statements are dead code — they are always caught by the
    generic handler. In a TUI context, `print()` output is invisible. Should let exceptions propagate
    to the caller.

## Remaining Fix Order

1. Add `List` to typing imports in `profile_parser.py` (Finding #16 — crash bug).
2. Fix `pdf_converter.py` error handling — let exceptions propagate (Finding #18).
3. Remove explicit `_update_resume_preview` call in `screens/resume.py:49` (Finding #11).
4. Remove unused imports in `screens/resume.py` and `resume/__init__.py` (Findings #14, #15).
5. Delete dead `isinstance(exp, dict)` branch in `screens/resume.py:73-77`.
6. Skip Finding #10 (placeholder, will be replaced by LLM integration).
