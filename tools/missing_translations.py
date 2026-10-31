#!/usr/bin/env python3
"""Find missing English translations for a catalog and append them ready to translate.

    tools/missing_translations.py <target catalog> [--comment] [--dry-run]

Examples:
    tools/missing_translations.py de/wordcraft.tsv
    tools/missing_translations.py locales/de/wordcraft.tsv
    tools/missing_translations.py de wordcraft.tsv
    tools/missing_translations.py de/wordcraft.tsv --dry-run
    tools/missing_translations.py de/wordcraft.tsv --comment

Checks the specified catalog against all other locales' catalogs of the same name (just like
`cargo test coverage_report`), finds all English source keys (context + source text) that are
present in other locales but missing from the target catalog, and appends them to the file
under a `# Missing translations:` comment.

If the target is an app catalog (e.g. `wordcraft.tsv`), any key that already exists in that
language's `common.tsv` is skipped so redundant overrides are never added.

By default, missing rows are appended as `<context><TAB><source><TAB>` ready for translation.
With `--comment` (or `-c`), rows are prefixed with `#` so CI checks pass even before translation.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_catalog_keys(path):
    """Returns a dict of (context, source) -> line from a TSV catalog."""
    if not path.is_file():
        return {}
    keys = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip("\r")
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) >= 2:
            keys[(cols[0], cols[1])] = line
    return keys


def parse_existing_keys_in_target(path):
    """Returns a set of (context, source) keys present in the target catalog,
    including active rows and any previously appended commented/untranslated rows."""
    if not path.is_file():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip("\r")
        if not line:
            continue
        if line.startswith("#"):
            rest = line[1:]
            cols = rest.split("\t")
            if len(cols) >= 2 and not line.startswith("# "):
                keys.add((cols[0], cols[1]))
            continue
        cols = line.split("\t")
        if len(cols) >= 2:
            keys.add((cols[0], cols[1]))
    return keys


def resolve_target(target_str, app_str=None, root=ROOT):
    """Resolves (locale, file_name, target_path) from input arguments."""
    p = Path(target_str)
    if p.is_absolute():
        locales_dir = root / "locales"
        try:
            rel = p.relative_to(locales_dir)
            parts = rel.parts
        except ValueError:
            try:
                rel = p.relative_to(root)
                parts = rel.parts
                if parts and parts[0] == "locales":
                    parts = parts[1:]
            except ValueError:
                parts = p.parts[-2:]
    else:
        clean = target_str.replace("\\", "/").strip("/")
        if clean.startswith("locales/"):
            clean = clean[len("locales/"):]
        parts = [part for part in clean.split("/") if part]

    if len(parts) == 1 and app_str:
        locale = parts[0]
        file_name = app_str
    elif len(parts) == 2:
        locale, file_name = parts[0], parts[1]
    elif len(parts) == 1:
        sys.exit(f"Invalid target {target_str!r}. Specify e.g. 'de/wordcraft.tsv' or 'de wordcraft.tsv'")
    else:
        sys.exit(f"Invalid target path {target_str!r}.")

    if not file_name.endswith(".tsv"):
        file_name += ".tsv"

    target_path = root / "locales" / locale / file_name
    return locale, file_name, target_path


def sort_keys(keys):
    """Catalog order: source text casefolded, then exact source text, then context."""
    return sorted(keys, key=lambda k: (k[1].casefold(), k[1], k[0]))


def find_missing(target_str, app_str=None, comment=False, dry_run=False, root=ROOT):
    locale, file_name, target_path = resolve_target(target_str, app_str, root)
    locales_dir = root / "locales"

    if not (locales_dir / locale).is_dir():
        sys.exit(f"Locale directory does not exist: locales/{locale}")
    if not target_path.is_file():
        sys.exit(f"Target catalog file does not exist: {target_path.relative_to(root)}")

    # 1. Gather all keys from all locales for this catalog name
    all_keys = set()
    counts = {}
    for loc_dir in sorted(locales_dir.iterdir()):
        if not loc_dir.is_dir():
            continue
        other_path = loc_dir / file_name
        if other_path.is_file():
            keys = parse_catalog_keys(other_path)
            counts[loc_dir.name] = len(keys)
            all_keys.update(keys.keys())

    max_count = max(counts.values()) if counts else 0
    max_locs = [loc for loc, cnt in counts.items() if cnt == max_count]
    max_loc_str = ", ".join(max_locs) if max_locs else "none"

    # 2. Existing keys in target catalog
    target_keys = parse_existing_keys_in_target(target_path)
    current_count = counts.get(locale, len(target_keys))

    # 3. If target is an app catalog, read locale's common.tsv
    is_app_catalog = (file_name != "common.tsv")
    common_keys = set()
    if is_app_catalog:
        common_path = locales_dir / locale / "common.tsv"
        if common_path.is_file():
            common_keys = set(parse_catalog_keys(common_path).keys())

    # 4. Determine missing keys
    missing_from_other = all_keys - target_keys
    skipped_common = {k for k in missing_from_other if k in common_keys}
    to_add = missing_from_other - common_keys

    # 5. Print report
    print(f"Target catalog:     {locale}/{file_name}")
    print(f"Current coverage:   {current_count}/{max_count} rows (max in {max_loc_str})")
    print(f"Total keys in all:  {len(all_keys)}")
    print(f"Missing from file:  {len(missing_from_other)}")
    if is_app_catalog:
        print(f"Already in common:  {len(skipped_common)} (skipped)")
    print(f"Translations to add: {len(to_add)}")

    if not to_add:
        print(f"No missing translations to add to {locale}/{file_name}.")
        return 0

    if dry_run:
        print(f"[dry-run] Would add {len(to_add)} keys to {target_path.relative_to(root)}.")
        return 0

    # 6. Append to target file
    text = target_path.read_text(encoding="utf-8")
    sep = "\n" if text and not text.endswith("\n") else ""

    lines_to_append = []
    has_header = "# Missing translations" in text
    if not has_header:
        lines_to_append.append("\n# Missing translations:\n")

    for context, source in sort_keys(to_add):
        if comment:
            lines_to_append.append(f"#{context}\t{source}\t\n")
        else:
            lines_to_append.append(f"{context}\t{source}\t\n")

    new_content = text + sep + "".join(lines_to_append)
    target_path.write_text(new_content, encoding="utf-8")
    print(f"Successfully added {len(to_add)} missing translation(s) to {target_path.relative_to(root)}.")
    return len(to_add)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("target", help="target catalog, e.g. de/wordcraft.tsv or de")
    p.add_argument("app", nargs="?", default=None, help="app name if target was locale, e.g. wordcraft.tsv")
    p.add_argument("-c", "--comment", action="store_true", help="prefix added rows with # so catalog passes CI before translation")
    p.add_argument("-n", "--dry-run", action="store_true", help="report missing rows without modifying the file")
    args = p.parse_args(argv)
    find_missing(args.target, args.app, comment=args.comment, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
