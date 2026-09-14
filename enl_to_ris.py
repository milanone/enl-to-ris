#!/usr/bin/env python3
"""Convert a legacy EndNote library (.enl, pre-version-20 format) to RIS.

Background
----------
Before EndNote 20, the .enl file was only a small pointer/settings file;
the actual records live in a companion "<library name>.Data" folder, in a
MyISAM database (the same on-disk format MySQL/MariaDB used before InnoDB
became the default): a "refs" table stored as refs.frm (structure) +
refs.MYD (data) + refs.MYI (index), normally under "<library>.Data/rdb/".

There is no public spec for this exact on-disk layout, and hand-parsing
the MyISAM "dynamic record" binary format is fragile (large fields can be
split across storage blocks, silently producing corrupted output if the
parsing is even slightly wrong). Real MariaDB/MySQL code reads its own
format correctly, so this script uses a real (portable, no-install)
MariaDB server as an explicit, self-provisioning dependency: on first run
it downloads and caches "MariaDB Server" (GPLv2) as a portable zip under
your local app-data folder, and on every run it briefly starts a private,
throwaway instance pointed at a copy of the library's table files, reads
the data over SQL, then shuts the instance down.

Requirements
------------
- The .enl file AND its companion "<library name>.Data" folder must both
  be present (the .Data folder holds the real refs.MYI index; without it
  the legacy table cannot be opened at all).
- Internet access on first run only, to fetch the portable MariaDB
  package from archive.mariadb.org (~90 MB, cached afterwards under
  %LOCALAPPDATA%\\enl_to_ris on Windows, or ~/.cache/enl_to_ris elsewhere).
- pip install pymysql

Usage
-----
    python enl_to_ris.py "MyLibrary.enl" MyLibrary.ris

Reference-type mapping
-----------------------
EndNote stores each record's reference type as a small integer whose
meaning is defined by the *application's* type list, not by the library
file itself (a "reftype" table exists but ships empty in the library).
REFTYPE_MAP below only covers the codes observed and manually verified
against real records while building this script (0/1/7). If your library
uses other codes, the script falls back to the generic RIS type "GEN" and
prints a summary of every code found so you can extend the map.
"""

import argparse
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

MARIADB_VERSION = "10.11.7"
MARIADB_ZIP_NAME = f"mariadb-{MARIADB_VERSION}-winx64.zip"
MARIADB_URL = (
    f"https://archive.mariadb.org/mariadb-{MARIADB_VERSION}/"
    f"winx64-packages/{MARIADB_ZIP_NAME}"
)

REFTYPE_MAP = {
    0: "JOUR",   # Journal Article (verified: volume/issue/pages/journal name)
    1: "BOOK",   # Book (verified: publisher + place published, no host title)
    7: "CHAP",   # Book Section (verified: secondary_title = host book title)
}

SIMPLE_TAGS = [
    ("title", "TI"),
    ("secondary_title", "T2"),
    ("tertiary_title", "T3"),
    ("year", "PY"),
    ("volume", "VL"),
    ("number", "IS"),
    ("place_published", "CY"),
    ("publisher", "PB"),
    ("isbn", "SN"),
    ("language", "LA"),
    ("edition", "ET"),
    ("abstract", "AB"),
    ("url", "UR"),
]

LEFTOVER_NOTE_FIELDS = [
    "notes", "research_notes", "translated_title", "alternate_title",
    "short_title", "label", "call_number", "accession_number",
    "author_address", "section", "custom_1", "custom_2", "custom_3",
    "custom_4", "custom_5", "custom_6", "custom_7",
]

MULTI_VALUE_SEP = "\r"


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "enl_to_ris"


def ensure_mariadb() -> Path:
    """Return the path to a portable MariaDB install, downloading it once."""
    install_dir = cache_dir() / f"mariadb-{MARIADB_VERSION}-winx64"
    mariadbd = install_dir / "bin" / "mariadbd.exe"
    if mariadbd.exists():
        return install_dir

    install_dir.parent.mkdir(parents=True, exist_ok=True)
    zip_path = install_dir.parent / MARIADB_ZIP_NAME
    print(
        f"Missing dependency: downloading MariaDB {MARIADB_VERSION} portable "
        f"(~90 MB) from {MARIADB_URL}\nto {zip_path} (will be reused on "
        f"future runs)..."
    )
    import urllib.request

    urllib.request.urlretrieve(MARIADB_URL, zip_path)
    print("Extracting...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(install_dir.parent)
    zip_path.unlink()
    if not mariadbd.exists():
        sys.exit(f"Extraction failed: {mariadbd} not found after unzip.")
    return install_dir


def find_table_files(enl_path: Path) -> Path:
    """Return the directory holding refs.frm/.MYD/.MYI for this library."""
    data_dir = enl_path.with_suffix("")
    data_dir = data_dir.with_name(data_dir.name + ".Data")
    for sub in ("rdb", "tdb"):
        candidate = data_dir / sub
        if (candidate / "refs.MYI").exists():
            return candidate
    sys.exit(
        f"Can't find '{data_dir}\\rdb\\refs.MYI' (or tdb). Pre-EndNote-20 "
        f"libraries need the '{data_dir.name}' folder next to the .enl "
        f"file: it holds the MyISAM index, without which the legacy table "
        f"can't be opened at all."
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    sys.exit("MariaDB did not respond within the startup timeout.")


class TempServer:
    """A throwaway MariaDB instance serving one copy of the refs table."""

    def __init__(self, mariadb_dir: Path, table_dir: Path):
        self.mariadb_dir = mariadb_dir
        self.table_dir = table_dir
        self.work_dir = Path(
            os.environ.get("TEMP", "/tmp")
        ) / f"enl_to_ris_{os.getpid()}"
        self.datadir = self.work_dir / "data"
        self.port = free_port()
        self.proc = None

    def __enter__(self):
        self.datadir.mkdir(parents=True)
        subprocess.run(
            [
                str(self.mariadb_dir / "bin" / "mysql_install_db.exe"),
                f"--datadir={self.datadir}",
            ],
            check=True,
            capture_output=True,
        )
        schema_dir = self.datadir / "endnote"
        schema_dir.mkdir()
        for f in self.table_dir.glob("refs*"):
            shutil.copy2(f, schema_dir / f.name)

        self.proc = subprocess.Popen(
            [
                str(self.mariadb_dir / "bin" / "mariadbd.exe"),
                f"--datadir={self.datadir}",
                f"--port={self.port}",
                "--bind-address=127.0.0.1",
                "--skip-grant-tables",
                "--skip-networking=0",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        wait_for_port(self.port)
        return self

    def __exit__(self, *exc):
        if self.proc is not None:
            subprocess.run(
                [
                    str(self.mariadb_dir / "bin" / "mariadb-admin.exe"),
                    "-h", "127.0.0.1", "-P", str(self.port), "-u", "root",
                    "shutdown",
                ],
                capture_output=True,
            )
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.work_dir, ignore_errors=True)


def fetch_records(server: TempServer) -> list[dict]:
    import pymysql

    conn = pymysql.connect(
        host="127.0.0.1",
        port=server.port,
        user="root",
        database="endnote",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            # The legacy .frm predates this server version and must be
            # rewritten before it can be queried normally.
            cur.execute("ALTER TABLE refs FORCE")
            cur.execute("SELECT * FROM refs ORDER BY id")
            return cur.fetchall()
    finally:
        conn.close()


def split_multi(raw: str) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split(MULTI_VALUE_SEP) if p.strip()]


def clean_doi(raw: str) -> str:
    raw = raw.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if raw.lower().startswith(prefix):
            return raw[len(prefix):]
    return raw


def record_to_ris(row: dict) -> str:
    ris_type = REFTYPE_MAP.get(row.get("reference_type"), "GEN")
    lines = [f"TY  - {ris_type}"]

    for author in split_multi(row.get("author") or ""):
        lines.append(f"AU  - {author}")

    for field, tag in SIMPLE_TAGS:
        value = (row.get(field) or "").strip()
        if value:
            lines.append(f"{tag}  - {value}")

    doi = (row.get("electronic_resource_number") or "").strip()
    if doi:
        lines.append(f"DO  - {clean_doi(doi)}")

    pages = (row.get("pages") or "").strip()
    if pages:
        if "-" in pages:
            start, _, end = pages.partition("-")
            lines.append(f"SP  - {start.strip()}")
            if end.strip():
                lines.append(f"EP  - {end.strip()}")
        else:
            lines.append(f"SP  - {pages}")

    for keyword in split_multi(row.get("keywords") or ""):
        lines.append(f"KW  - {keyword}")

    for field in LEFTOVER_NOTE_FIELDS:
        value = (row.get(field) or "").strip()
        if value:
            lines.append(f"N1  - [{field}] {value}")

    lines.append("ER  - ")
    return "\n".join(lines)


def convert(enl_path: Path, output_path: Path) -> None:
    mariadb_dir = ensure_mariadb()
    table_dir = find_table_files(enl_path)

    with TempServer(mariadb_dir, table_dir) as server:
        rows = fetch_records(server)

    entries = [record_to_ris(row) for row in rows]
    output_path.write_text("\n\n".join(entries) + "\n", encoding="utf-8")

    seen_types = sorted({row.get("reference_type") for row in rows})
    unmapped = [t for t in seen_types if t not in REFTYPE_MAP]
    print(f"Converted {len(entries)} records to {output_path}")
    if unmapped:
        print(
            f"Warning: unmapped reference_type codes (exported as GEN): "
            f"{unmapped}. Check the corresponding records and extend "
            f"REFTYPE_MAP in the script if needed."
        )


def main() -> None:
    if platform.system() != "Windows":
        sys.exit(
            "This script uses MariaDB's portable Windows binaries; on "
            "other operating systems it needs to be adapted to a "
            "different MariaDB/MySQL package."
        )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="EndNote library file (.enl)")
    parser.add_argument(
        "output", type=Path, nargs="?", help="Destination RIS file (.ris)"
    )
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"File not found: {args.input}")
    if args.output is None:
        args.output = args.input.with_suffix(".ris")

    convert(args.input, args.output)


if __name__ == "__main__":
    main()
