#!/usr/bin/env python3
import argparse
import csv
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from pdfminer.high_level import extract_text

BASE_DIR = Path(__file__).resolve().parents[1]


def safe_name(name: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "_", name).strip("_")[:80]


def download_pdf(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return
    urllib.request.urlretrieve(url, dest)


def extract_text_pdf(pdf_path: Path) -> str:
    try:
        return extract_text(str(pdf_path)) or ""
    except Exception:
        return ""


def ocr_pdf(pdf_path: Path, lang: str = "chi_tra+eng") -> str:
    pdftoppm = shutil.which("pdftoppm")
    tesseract = shutil.which("tesseract")
    if not pdftoppm or not tesseract:
        raise RuntimeError("pdftoppm/tesseract not found")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        prefix = tmp_dir / "page"
        subprocess.run([pdftoppm, "-r", "200", "-png", str(pdf_path), str(prefix)], check=True)
        images = sorted(tmp_dir.glob("page-*.png"))
        texts = []
        for img in images:
            proc = subprocess.run([
                tesseract,
                str(img),
                "stdout",
                "-l",
                lang,
                "--psm",
                "6",
            ], capture_output=True, text=True)
            texts.append(proc.stdout or "")
        return "\n\n".join(texts).strip()


def process_csv(csv_path: Path, out_prefix: str, limit: int | None, offset: int, min_len: int, use_ocr: bool) -> None:
    rows = []
    with csv_path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    rows.sort(key=lambda r: int(r["year"]), reverse=True)
    rows = rows[offset: (offset + limit) if limit else None]

    pdf_dir = BASE_DIR / "exams" / f"pdfs_{out_prefix}"
    text_dir = BASE_DIR / "exams" / f"texts_{out_prefix}"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)

    usable = []

    for r in rows:
        year = r["year"]
        school = r["school"]
        url = r["download_url"]
        safe = safe_name(school)
        pdf_path = pdf_dir / f"{year}_{safe}.pdf"
        txt_path = text_dir / f"{year}_{safe}.txt"
        method = "pdf"

        if txt_path.exists():
            try:
                cached = txt_path.read_text()
                if len(cached) >= min_len:
                    usable.append({
                        **r,
                        "text_file": str(txt_path),
                        "method": "cached",
                        "text_len": str(len(cached)),
                    })
                    continue
            except Exception:
                pass

        try:
            download_pdf(url, pdf_path)
        except Exception:
            continue

        text = extract_text_pdf(pdf_path)
        if len(text) < min_len and use_ocr:
            try:
                text = ocr_pdf(pdf_path)
                method = "ocr"
            except Exception:
                text = ""

        if len(text) >= min_len:
            txt_path.write_text(text)
            usable.append({
                **r,
                "text_file": str(txt_path),
                "method": method,
                "text_len": str(len(text)),
            })

    out_csv = BASE_DIR / "exams" / f"usable_{out_prefix}.csv"
    existing = {}
    if out_csv.exists():
        with out_csv.open(newline="") as f:
            for row in csv.DictReader(f):
                existing[row["download_url"]] = row

    for u in usable:
        existing[u["download_url"]] = u

    merged = list(existing.values())
    merged.sort(key=lambda r: (int(r["year"]), r["school"]), reverse=True)

    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "year", "school", "subject", "download_url", "text_file", "method", "text_len"
        ])
        writer.writeheader()
        for u in merged:
            writer.writerow(u)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True, help="Input CSV (from exams/*.csv)")
    parser.add_argument("--out", required=True, help="Output prefix, e.g. computer_concepts")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--min-len", type=int, default=1000)
    parser.add_argument("--no-ocr", action="store_true")
    args = parser.parse_args()

    process_csv(
        Path(args.csv),
        args.out,
        args.limit,
        args.offset,
        args.min_len,
        use_ocr=not args.no_ocr,
    )
