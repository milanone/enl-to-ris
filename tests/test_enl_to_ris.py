"""Tests for enl_to_ris: the RIS conversion logic (no MariaDB needed) and, when the sample library and the
cached portable MariaDB are present, a full conversion of 'example data/bibliografia antioxidant assay e
lycopene.enl' (gitignored, real data).

    py -m unittest discover -s tests -v
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("enl_to_ris", os.path.join(HERE, "..", "enl_to_ris.py"))
e2r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2r)

SAMPLE = Path(HERE).parent / "example data" / "bibliografia antioxidant assay e lycopene.enl"


class TestHelpers(unittest.TestCase):
    def test_split_multi(self):
        self.assertEqual(e2r.split_multi("Rossi, M\rBianchi, L\r"), ["Rossi, M", "Bianchi, L"])
        self.assertEqual(e2r.split_multi(""), [])
        self.assertEqual(e2r.split_multi(None), [])

    def test_clean_doi(self):
        self.assertEqual(e2r.clean_doi("https://doi.org/10.1000/xyz"), "10.1000/xyz")
        self.assertEqual(e2r.clean_doi("DOI:10.1000/xyz"), "10.1000/xyz")
        self.assertEqual(e2r.clean_doi(" 10.1000/xyz "), "10.1000/xyz")

    def test_find_table_files_missing(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                e2r.find_table_files(Path(d) / "lib.enl")

    def test_find_table_files(self):
        with tempfile.TemporaryDirectory() as d:
            rdb = Path(d) / "lib.Data" / "rdb"
            rdb.mkdir(parents=True)
            (rdb / "refs.MYI").write_bytes(b"")
            self.assertEqual(e2r.find_table_files(Path(d) / "lib.enl"), rdb)


class TestRecordToRis(unittest.TestCase):
    def test_journal_article(self):
        row = {"reference_type": 0, "author": "Rossi, M\rBianchi, L", "title": "A title",
               "secondary_title": "J. Test", "year": "2020", "volume": "5", "number": "2",
               "pages": "10-20", "electronic_resource_number": "https://doi.org/10.1/abc",
               "keywords": "one\rtwo"}
        lines = e2r.record_to_ris(row).split("\n")
        self.assertEqual(lines[0], "TY  - JOUR")
        self.assertEqual(lines[-1], "ER  - ")
        for expected in ("AU  - Rossi, M", "AU  - Bianchi, L", "TI  - A title", "T2  - J. Test", "PY  - 2020",
                         "VL  - 5", "IS  - 2", "SP  - 10", "EP  - 20", "DO  - 10.1/abc", "KW  - one", "KW  - two"):
            self.assertIn(expected, lines)

    def test_single_page_has_no_end_page(self):
        lines = e2r.record_to_ris({"reference_type": 0, "pages": "42"}).split("\n")
        self.assertIn("SP  - 42", lines)
        self.assertFalse(any(l.startswith("EP") for l in lines))

    def test_unknown_type_is_generic(self):
        self.assertEqual(e2r.record_to_ris({"reference_type": 99}).split("\n")[0], "TY  - GEN")

    def test_book_and_chapter(self):
        self.assertTrue(e2r.record_to_ris({"reference_type": 1}).startswith("TY  - BOOK"))
        self.assertTrue(e2r.record_to_ris({"reference_type": 7}).startswith("TY  - CHAP"))

    def test_leftover_fields_become_notes(self):
        ris = e2r.record_to_ris({"reference_type": 0, "notes": "check this", "label": "L1"})
        self.assertIn("N1  - [notes] check this", ris)
        self.assertIn("N1  - [label] L1", ris)

    def test_empty_values_are_skipped(self):
        ris = e2r.record_to_ris({"reference_type": 0, "title": "  ", "year": None})
        self.assertNotIn("TI  -", ris)
        self.assertNotIn("PY  -", ris)


@unittest.skipUnless(SAMPLE.exists() and (e2r.cache_dir() / f"mariadb-{e2r.MARIADB_VERSION}-winx64" / "bin"
                                          / "mariadbd.exe").exists(),
                     "sample library or cached MariaDB not present")
class TestRealLibrary(unittest.TestCase):
    def test_full_conversion(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.ris"
            e2r.convert(SAMPLE, out)
            text = out.read_text(encoding="utf-8")
        self.assertEqual(text.count("\nER  - ") + text.startswith("ER  - "), 73)
        self.assertEqual(text.count("TY  - "), 73)


if __name__ == "__main__":
    unittest.main()
