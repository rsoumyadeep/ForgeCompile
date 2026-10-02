# Failure Log

Meaningful failures, wrong turns and debugging discoveries, recorded as they happen. Entries
are never deleted or rewritten to look better. A fix that later turns out wrong gets a
follow-up entry.

Template:

```
## F-NNN — <short title>
- Date / Phase:
- Attempted:            what was being done
- Why:                  motivation
- Symptom:              observed failure / error text
- Root cause:
- Debugging process:
- Fix:
- Fix worked?:
- Lesson:
```

---

## F-001 — `uv sync` failed: hatchling requires README before first build

- **Date / Phase:** 2026-10-02, Phase 0
- **Attempted:** Running `uv sync` right after writing `pyproject.toml` and the package
  sources, before writing any documentation.
- **Symptom:** `OSError: Readme file does not exist: README.md` raised from
  `hatchling/metadata/core.py` while building the editable install.
- **Root cause:** `pyproject.toml` declares `readme = "README.md"`. Hatchling validates
  metadata fields eagerly when it builds the package, so a missing readme is fatal.
- **Fix:** Wrote `README.md` (planned anyway) and re-ran `uv sync`.
- **Fix worked?:** Yes.
- **Lesson:** Package metadata files are build inputs. Order scaffolding so that every file
  referenced by `pyproject.toml` exists before the first install.
