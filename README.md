# enl-to-ris

Convert a legacy EndNote library (`.enl`, pre-EndNote-20 format) to RIS, without needing EndNote installed.

## Why this exists

Before EndNote 20, the `.enl` file was just a small pointer; the actual
records lived in a companion `<library name>.Data` folder, stored as a
**MyISAM database** — the same on-disk table format MySQL/MariaDB used
before InnoDB became the default. There's no public spec for this exact
layout, and hand-parsing MyISAM's binary "dynamic record" format is
fragile: long fields can be split across storage blocks, and a small
mistake produces corrupted output silently. That's presumably why no
converter for this specific case seems to exist online.

Rather than reimplement that binary format from scratch, this script
uses the real thing: a portable, no-install build of **MariaDB Server**
as an explicit dependency. On first run it downloads and caches the
official portable Windows package; on every run it briefly starts a
private, throwaway instance pointed at a copy of the library's table
files, reads the records over plain SQL, and shuts the instance down.

EndNote 20+ switched the format to plain SQLite, which doesn't need any
of this — this tool is only for older libraries.

## Requirements

- Windows (uses MariaDB's portable Windows build)
- Python 3.10+
- `pip install pymysql`
- Internet access on first run only, to download MariaDB Server
  (~90 MB, GPLv2, from `archive.mariadb.org`), cached afterwards under
  `%LOCALAPPDATA%\enl_to_ris`
- The `.enl` file **and** its companion `<library name>.Data` folder,
  both present side by side (the `.Data` folder holds the MyISAM index
  file; without it, the legacy table can't be opened at all)

## Usage

```bash
python enl_to_ris.py "MyLibrary.enl" MyLibrary.ris
```

If the output path is omitted, it defaults to the input filename with
a `.ris` extension.

## Reference-type mapping

EndNote stores each record's type (Journal Article, Book, ...) as a
small integer, whose meaning is defined by the *application's* type
list — not stored in the library file itself. `REFTYPE_MAP` in the
script currently covers the codes verified by hand against real
records (`0` = Journal Article, `1` = Book, `7` = Book Section). Any
other code is exported as the generic RIS type `GEN`, and the script
prints a summary of every code it found so you can extend the map for
your own library.

## Example run

```
$ python enl_to_ris.py examples/Impedance_bacteria.enl Impedance_bacteria.ris
Converted 76 records to Impedance_bacteria.ris
```

## Limitations

- Windows only.
- Metadata only — attached PDFs/figures in the `.Data` folder are not exported.
- `REFTYPE_MAP` may need extending for libraries using reference types
  other than Journal Article / Book / Book Section (the script tells
  you exactly which codes are unmapped).

## License

[MIT](LICENSE)
