"""Tests for missing_translations.py on a small synthetic tree: python3 -m unittest discover tools"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import missing_translations
import sync_app


def write(root, locale, file, name, app, *rows):
    path = root / "locales" / locale / f"{file}.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join("\t".join(r) + "\n" for r in rows)
    path.write_text(sync_app.header(name, locale, app) + "\n" + body, encoding="utf-8")


class MissingTranslationsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

        # de: has "language.name" and "Save" in common.tsv
        write(
            self.root,
            "de",
            "common",
            "Deutsch",
            "every Crafting App",
            ("@id", "language.name", "Deutsch"),
            ("", "Save", "Speichern"),
            ("", "Cancel", "Abbrechen"),
        )
        # de/wordcraft: has "Heading"
        write(
            self.root,
            "de",
            "wordcraft",
            "Deutsch",
            "WordCraft",
            ("", "Heading", "Überschrift"),
        )

        # fr/common: has "language.name", "Save"
        write(
            self.root,
            "fr",
            "common",
            "Français",
            "every Crafting App",
            ("@id", "language.name", "Français"),
            ("", "Save", "Enregistrer"),
        )
        # fr/wordcraft: has "Heading", "Subtitle", "Cancel", and "Bold"
        # Notice: "Cancel" is in de/common.tsv, so it should NOT be added to de/wordcraft.tsv!
        # "Subtitle" and "Bold" are NOT in de/wordcraft.tsv or de/common.tsv, so they SHOULD be added!
        write(
            self.root,
            "fr",
            "wordcraft",
            "Français",
            "WordCraft",
            ("", "Heading", "En-tête"),
            ("", "Subtitle", "Sous-titre"),
            ("", "Cancel", "Annuler"),
            ("menu", "Bold", "Gras"),
        )

    def run_tool(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            missing_translations.main(list(argv))
        return out.getvalue()

    def test_adds_missing_translations_skipping_common(self):
        target = self.root / "locales" / "de" / "wordcraft.tsv"
        with contextlib.redirect_stdout(io.StringIO()):
            missing_translations.find_missing(
                str(target), root=self.root, comment=False, dry_run=False
            )

        content = target.read_text(encoding="utf-8")
        self.assertIn("# Missing translations:\n", content)
        # "Bold" with context "menu" and "Subtitle" should be added
        self.assertIn("\nmenu\tBold\t\n", content)
        self.assertIn("\n\tSubtitle\t\n", content)
        # "Cancel" is already in de/common.tsv, must NOT be added
        self.assertNotIn("Cancel", content)
        # Existing "Heading" should still be there
        self.assertIn("\tHeading\tÜberschrift\n", content)

    def test_comment_flag_prefixes_rows_with_hash(self):
        target = self.root / "locales" / "de" / "wordcraft.tsv"
        with contextlib.redirect_stdout(io.StringIO()):
            missing_translations.find_missing(
                str(target), root=self.root, comment=True, dry_run=False
            )

        content = target.read_text(encoding="utf-8")
        self.assertIn("# Missing translations:\n", content)
        self.assertIn("\n#menu\tBold\t\n", content)
        self.assertIn("\n#\tSubtitle\t\n", content)

    def test_dry_run_does_not_modify_file(self):
        target = self.root / "locales" / "de" / "wordcraft.tsv"
        before = target.read_text(encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            missing_translations.find_missing(
                str(target), root=self.root, comment=False, dry_run=True
            )
        after = target.read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_idempotent_running_twice_does_not_duplicate(self):
        target = self.root / "locales" / "de" / "wordcraft.tsv"
        with contextlib.redirect_stdout(io.StringIO()):
            missing_translations.find_missing(
                str(target), root=self.root, comment=False, dry_run=False
            )
        first_run = target.read_text(encoding="utf-8")

        # Second run should find 0 translations to add and leave content unchanged
        with contextlib.redirect_stdout(io.StringIO()):
            missing_translations.find_missing(
                str(target), root=self.root, comment=False, dry_run=False
            )
        second_run = target.read_text(encoding="utf-8")
        self.assertEqual(first_run, second_run)


if __name__ == "__main__":
    unittest.main()
