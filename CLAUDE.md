# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
General rules for all of Francesco's projects (stack, code conventions, repository rules, git/GitHub, the
Drive mirror, how he works) are in `..\CLAUDE.md`; this file has the project-specific details.

## Purpose

Command-line converter from legacy EndNote libraries (`.enl`, pre-EndNote-20) to RIS, so the references can be
imported elsewhere without EndNote. It is a CLI tool, not a Tkinter GUI like the other projects, so it has no
screenshot and no `.bat` launcher; it makes no plots, so PlotStyleKit does not apply.

## Running / tests

```bash
py enl_to_ris.py "MyLibrary.enl" [MyLibrary.ris]
py -m unittest discover -s tests -v
```

Needs `pymysql` (`requirements.txt`), Windows, and the `.enl` file **plus** its `<name>.Data` folder next to it.
Sample data: `example data/bibliografia antioxidant assay e lycopene.enl` (+ `.Data`, gitignored: a personal
bibliography, never commit). The real-library test also needs the portable MariaDB already downloaded to
`%LOCALAPPDATA%\enl_to_ris`; otherwise it is skipped.

## Architecture

Single file `enl_to_ris.py`, plain functions:

- `ensure_mariadb()` downloads (once) and caches the official portable MariaDB 10.11.7 Windows zip.
- `find_table_files()` locates `refs.frm/.MYD/.MYI` under `<library>.Data/rdb` (or `tdb`).
- `TempServer` (context manager) creates a throwaway data dir, copies the `refs*` files into a schema folder,
  starts `mariadbd` on a free local port with `--skip-grant-tables`, and shuts it down and deletes everything on
  exit.
- `fetch_records()` runs `ALTER TABLE refs FORCE` (the legacy `.frm` must be rewritten) and `SELECT * FROM refs`.
- `record_to_ris()` maps one row to a RIS entry: `REFTYPE_MAP` (type codes), `SIMPLE_TAGS` (field -> tag),
  authors/keywords split on `\r` (`MULTI_VALUE_SEP`), `pages` split into SP/EP, DOI cleaned, and
  `LEFTOVER_NOTE_FIELDS` exported as `N1  - [field] value` so nothing is lost.

**Why MariaDB and not a hand-written parser:** the table is MyISAM with "dynamic records" where long fields are
split across blocks; a small parsing mistake corrupts the text silently. Using the real engine is the safe choice.

## Verified / not verified

- Verified on one library (73 records; tests assert the count). Reference type codes `0` (journal article), `1`
  (book), `7` (book section) were checked by hand; other codes export as `GEN` and are listed at the end of the run.
- Not exported: attached PDFs and figures, the `reftype` table (empty in these libraries).
- Windows only (portable Windows MariaDB build).

## Editing conventions (project)
- Follow `..\CLAUDE.md`: everything in English, surgical edits. The code was already in English.
- Never commit anything from `example data/` (real bibliography).
