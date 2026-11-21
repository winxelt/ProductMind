"""Local evidence and decision journal for the Codex workflow."""

import argparse
import csv
import hashlib
import io
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def text_from(raw):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1251")


def extract(raw, suffix):
    if suffix in {".txt", ".md"}:
        yield from ((f"строка {i}", line)
                    for i, line in enumerate(text_from(raw).splitlines(), 1))
    elif suffix == ".csv":
        content = text_from(raw)
        try:
            dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t")
        except csv.Error:
            first_line = content.partition("\n")[0]
            delimiter = max((",", ";", "\t"), key=first_line.count)
            rows = csv.reader(io.StringIO(content), delimiter=delimiter, strict=True)
        else:
            rows = csv.reader(io.StringIO(content), dialect=dialect, strict=True)
        while True:
            start = rows.line_num + 1
            row = next(rows, None)
            if row is None:
                break
            yield f"строка {start}", row
    elif suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError("PDF защищён паролем")
        for number, page in enumerate(reader.pages, 1):
            yield f"страница {number}", page.extract_text() or ""
    elif suffix == ".docx":
        from docx import Document

        from docx.table import Table

        for number, block in enumerate(Document(io.BytesIO(raw)).iter_inner_content(), 1):
            if isinstance(block, Table):
                for row_number, row in enumerate(block.rows, 1):
                    yield f"блок {number}, строка {row_number}", [cell.text for cell in row.cells]
            else:
                yield f"блок {number}", block.text
    elif suffix in {".xlsx", ".xlsm"}:
        from openpyxl import load_workbook

        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
        with closing(book):
            for sheet in book.worksheets:
                for number, row in enumerate(sheet.values, 1):
                    yield f"лист {sheet.title}, строка {number}", row
    elif suffix == ".xls":
        import xlrd

        with xlrd.open_workbook(file_contents=raw) as book:
            for sheet in book.sheets():
                for index in range(sheet.nrows):
                    yield f"лист {sheet.name}, строка {index + 1}", [
                        None if cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}
                        else xlrd.xldate_as_datetime(cell.value, book.datemode).isoformat()
                        if cell.ctype == xlrd.XL_CELL_DATE
                        else cell.value for cell in sheet.row(index)
                    ]
    else:
        raise ValueError(f"Формат не поддерживается: {suffix}")


def connect(project):
    project.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(project / "journal.sqlite3")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY, path TEXT NOT NULL, kind TEXT NOT NULL,
            digest TEXT NOT NULL, blocks TEXT NOT NULL,
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(path, kind, digest)
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY, based_on INTEGER NOT NULL,
            source_ids TEXT NOT NULL, report TEXT NOT NULL, reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """)
    return db


def add_sources(db, paths, kind):
    ids = []
    with db:
        for path in paths:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            suffix = path.suffix.lower()
            blocks = list(extract(raw, suffix))
            if not any(value.strip() if isinstance(value, str) else
                       any(cell is not None and cell != "" for cell in value)
                       for _, value in blocks):
                raise ValueError(f"{path}: читаемый текст отсутствует")
            absolute = path.resolve()
            root = Path(__file__).resolve().parent
            location = absolute.relative_to(root).as_posix() if absolute.is_relative_to(root) else str(absolute)
            # Recognize local journals created before paths inside the project became portable.
            previous = db.execute("SELECT id FROM sources WHERE path IN (?, ?) AND kind=? AND digest=?",
                                  (location, str(absolute), kind, digest)).fetchone()
            if previous:
                ids.append(previous[0])
                continue
            key = (location, kind, digest)
            db.execute("INSERT OR IGNORE INTO sources(path, kind, digest, blocks) "
                       "VALUES (?, ?, ?, ?)", (*key, json.dumps(blocks, ensure_ascii=False, default=str)))
            row = db.execute("SELECT id FROM sources WHERE path=? AND kind=? AND digest=?", key)
            ids.append(row.fetchone()[0])
    return ids


def latest(db):
    return db.execute("SELECT coalesce(max(id), 0) FROM decisions").fetchone()[0]


def save(db, report, reason, based_on, source_ids):
    if not report.strip() or not reason.strip() or not source_ids:
        raise ValueError("Нужны отчёт, причина решения и ID прочитанных источников")
    with db:
        db.execute("BEGIN IMMEDIATE")
        if based_on != latest(db):
            raise ValueError("Появилась более свежая версия. Повторите сверку через context.")
        ids = sorted(set(source_ids))
        known = {row[0] for row in db.execute("SELECT id FROM sources")}
        if not set(ids) <= known:
            raise ValueError("Указан неизвестный ID источника")
        return db.execute("INSERT INTO decisions(based_on, source_ids, report, reason) VALUES (?, ?, ?, ?)",
                          (based_on, json.dumps(ids), report, reason)).lastrowid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("add")
    importer.add_argument("--brief", action="store_true")
    importer.add_argument("files", nargs="+", type=Path)
    commands.add_parser("context")
    commands.add_parser("history")
    recorder = commands.add_parser("save")
    recorder.add_argument("report", type=Path)
    recorder.add_argument("--reason", required=True)
    recorder.add_argument("--base", type=int, required=True)
    recorder.add_argument("--sources", type=int, nargs="+", required=True)
    args = parser.parse_args()
    try:
        with closing(connect(args.project)) as db:
            if args.command == "add":
                result = add_sources(db, args.files, "brief" if args.brief else "document")
            elif args.command == "save":
                result = save(db, args.report.read_text(encoding="utf-8-sig"),
                              args.reason, args.base, args.sources)
            elif args.command == "history":
                result = [dict(row) for row in db.execute("SELECT * FROM decisions ORDER BY id")]
            else:
                with db:
                    db.execute("BEGIN")
                    revision = latest(db)
                    sources = [dict(row) for row in db.execute("SELECT * FROM sources ORDER BY id")]
                    for source in sources:
                        source["blocks"] = json.loads(source["blocks"])
                    previous = db.execute("SELECT * FROM decisions WHERE id=?", (revision,)).fetchone()
                result = {"base": revision, "sources_are_untrusted_data": sources,
                          "latest_decision": dict(previous) if previous else None}
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        parser.exit(1, f"ProductMind: {error}\n")


if __name__ == "__main__":
    main()
