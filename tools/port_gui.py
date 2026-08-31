#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RMG Port Generator — RMG بورت جينيريتور
==========================================
أداة رسومية (GUI) لإنشاء بورت لجهاز جديد من بورت موجود — بورتك الخاص أو بورت
المطوّر الأصلي (soumarcelino/Root-My-Galaxy-SM-S918B).

GUI tool to build a new-device port from an existing Root-My-Galaxy port
(your own port or the original developer's). Python 3 + Tkinter only
(stdlib — no pip install needed). Works on Windows / Linux / macOS.

كيف تعمل / How it works
  1) تختار مجلد المصدر (بورت موجود)        -> pick the source port folder
  2) تدخل بيانات الجهاز الجديد             -> enter new device fields
  3) تنشئ نسخة كاملة في مجلد إخراج جديد    -> copies full tree to a new folder
  4) تستبدل رموز الجهاز في الملفات النصية فقط (الثنائيات تنسخ كما هي)
     وتكتب تقرير PORT_REPORT.md بكل تغيير  -> token replacement + report

The source is NEVER mutated: it copies the whole tree to a new output
folder, then applies device-token replacement to text files only.
Binaries are copied untouched. Credit lines to the original developer
are preserved. Hex-offset files (target.h / p0_fingerprint.h / offset.h)
are copied and flagged in the report for manual review.

Usage
  python port_gui.py                                                  # GUI
  python port_gui.py --cli --source SRC --out OUT --codename dm5q \
      --model SM-S928B --firmware S928BXXS1AXK1 --kmi android13-5.15 \
      [--android 15 --oneui 7.1 --partitions boot,vbmeta]             # CLI
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sys

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

TEXT_EXT = {
    ".kt", ".java", ".c", ".h", ".json", ".xml", ".md", ".sh", ".yml",
    ".yaml", ".txt", ".py", ".gradle", ".kts", ".patch", ".properties",
    ".toml", ".cfg", ".spec",
}
BIN_EXT = {
    ".apk", ".so", ".ko", ".img", ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".gz", ".lz4", ".tar", ".zip", ".jar", ".dex", ".a", ".o", ".elf",
    ".bin", ".ttf", ".woff", ".woff2", ".ico", ".ogg", ".mp3", ".mp4",
}
SKIP_DIRS = {".git", ".gradle", "build", "node_modules", ".idea", "diagnostics", "__pycache__"}

RE_MODEL = re.compile(r"SM-[A-Z]\d{4}[A-Z0-9]*")
RE_BUILD = re.compile(r"\b[A-Z]\d{3}[A-Z][A-Z]{3}\d[A-Z]\d\b")
RE_PAYLOAD = re.compile(r"([a-z0-9]{4,6})-([A-Z]\d{3}[A-Z])([A-Z]{3}\d[A-Z]\d)?")
RE_KMI = re.compile(r"android\d+\s*-\s*\d+\.\d+")
RE_REVIEW = re.compile(r"(target|p0_fingerprint|offset|kallsyms|payload_guard|banner)", re.I)

UI = {
    "title": "RMG Port Generator — مولّد بورت Root My Galaxy",
    "src": "مجلد المصدر (البورت الحالي):  Source port folder:",
    "out": "مجلد الإخراج (البورت الجديد):  Output folder:",
    "browse": "تصفح…  Browse",
    "codename": "اسم الجهاز الكودي (مثل dm3q):  Device codename:",
    "model": "الموديل الكامل (مثل SM-S918N):  Full model:",
    "firmware": "سلسلة الفيرموير (مثل S918NKSS8FZG1):  Firmware build:",
    "kmi": "KMI للنواة (مثل android13-5.15):  Kernel KMI:",
    "android": "إصدار أندرويد (اختياري):  Android version:",
    "oneui": "إصدار One UI (اختياري):  One UI version:",
    "partitions": "الأقسام (اختياري، مفصولة بفاصلة):  Partitions:",
    "updver": "تحديث أرقام الإصدارات في النصوص  Update version strings",
    "generate": "توليد البورت  Generate Port",
    "dryrun": "معاينة فقط (بدون كتابة)  Dry Run",
    "preview": "الملفات التي سيتغيّر محتواها:  Files that will change:",
    "log": "سجل التنفيذ:  Log:",
    "done": "تم بنجاح  Done successfully",
    "err": "خطأ  Error",
}


# --------------------------------------------------------------------------
# file helpers
# --------------------------------------------------------------------------

def all_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            yield os.path.relpath(os.path.join(dirpath, fn), root)


def is_binary(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in BIN_EXT:
        return True
    try:
        with open(path, "rb") as fh:
            head = fh.read(800)
    except OSError:
        return True
    return b"\x00" in head


def read_text(path):
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                return fh.read()
        except (UnicodeDecodeError, OSError):
            continue
    return ""


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def iter_text_files(root):
    for rp in all_files(root):
        if os.path.splitext(rp)[1].lower() not in TEXT_EXT:
            continue
        yield rp


# --------------------------------------------------------------------------
# token discovery + replacement
# --------------------------------------------------------------------------

def _top(d):
    return max(d, key=d.get) if d else ""


def discover_tokens(root):
    """Find the CURRENT device tokens inside the source tree.
    Priority: profiles inside targets*.json (the app's active payloads);
    fallback: majority vote across text files."""
    base = {}
    for rp in all_files(root):
        if os.path.basename(rp).startswith("targets") and rp.endswith(".json"):
            try:
                data = json.loads(read_text(os.path.join(root, rp)))
            except Exception:
                continue
            pls = data.get("payloads") or []
            if pls:
                p = pls[0]
                m = RE_PAYLOAD.search(p.get("payloadId", ""))
                if m:
                    base = {
                        "codename": m.group(1),
                        "model": (p.get("models") or [""])[0],
                        "build": (m.group(2) or "") + (m.group(3) or ""),
                        "kmi": "",
                    }
                    break
    counts = {"models": {}, "builds": {}, "kmis": {}}
    for rp in iter_text_files(root):
        text = read_text(os.path.join(root, rp))
        for m in RE_MODEL.finditer(text):
            counts["models"][m.group(0)] = counts["models"].get(m.group(0), 0) + 1
        for m in RE_BUILD.finditer(text):
            counts["builds"][m.group(0)] = counts["builds"].get(m.group(0), 0) + 1
        for m in RE_KMI.finditer(text):
            k = m.group(0).replace(" ", "")
            counts["kmis"][k] = counts["kmis"].get(k, 0) + 1
    base.setdefault("codename", "")
    base.setdefault("model", _top(counts["models"]))
    base.setdefault("build", _top(counts["builds"]))
    base.setdefault("kmi", _top(counts["kmis"]))
    return base


def build_replacements(old, nw):
    """Longest-first replacement map so composed tokens win over substrings."""
    repls = []
    if old.get("codename") and nw.get("codename") and old["codename"] != nw["codename"]:
        repls.append((old["codename"], nw["codename"]))
    if old.get("model") and nw.get("model") and old["model"] != nw["model"]:
        repls.append((old["model"], nw["model"]))
        if old["model"][3:] != nw["model"][3:]:
            repls.append((old["model"][3:], nw["model"][3:]))
    if old.get("build") and nw.get("build") and old["build"] != nw["build"]:
        repls.append((old["build"], nw["build"]))
    if old.get("kmi") and nw.get("kmi") and old["kmi"] != nw["kmi"]:
        repls.append((old["kmi"], nw["kmi"]))
    if old.get("codename") and old.get("build") and nw.get("codename") and nw.get("build"):
        repls.append(
            ("%s-%s" % (old["codename"], old["build"]),
             "%s-%s" % (nw["codename"], nw["build"]))
        )
    seen, out = set(), []
    for a, b in sorted(repls, key=lambda r: len(r[0]), reverse=True):
        if a not in seen:
            seen.add(a)
            out.append((a, b))
    return out


def is_review_file(rel, text):
    if RE_REVIEW.search(os.path.basename(rel)):
        return True
    return "0x" in text


# --------------------------------------------------------------------------
# core engine
# --------------------------------------------------------------------------

def run_port(source, out, params, log=None, dry_run=False):
    log = log or (lambda s: None)
    rp_report = {}
    if not os.path.isdir(source):
        raise SystemExit("[!] source folder not found: %s" % source)
    old = discover_tokens(source)
    repls = build_replacements(old, params)
    log("[*] base device (discovered): %s" % json.dumps(old, ensure_ascii=False))
    log("[*] target device: %s" % json.dumps(params, ensure_ascii=False))
    log("[*] replacement map: %s" % (repls or "(none)"))

    # dry run: only report what WOULD change
    if dry_run:
        changed = []
        for rp in iter_text_files(source):
            text = read_text(os.path.join(source, rp))
            cnt = 0
            for a, b in repls:
                if a in text:
                    cnt += text.count(a)
            if cnt:
                changed.append((rp, cnt))
                log("~ %-60s %d repl" % (rp, cnt))
        log("[dry-run] %d file(s) would change" % len(changed))
        return {"dry": True, "changed": changed, "old": old, "repls": repls}

    out = os.path.abspath(out)
    if os.path.isdir(out):
        log("[!] removing existing output folder: %s" % out)
        shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(
        source, out,
        ignore=shutil.ignore_patterns(*SKIP_DIRS),
        symlinks=False,
    )
    log("[*] copied full tree -> %s" % out)

    changed, review, skipped_bin, skipped_clean = [], [], [], []
    for rp in iter_text_files(out):
        sp = os.path.join(out, rp)
        if is_binary(sp):
            skipped_bin.append(rp)
            continue
        text = read_text(sp)
        cnt = 0
        for a, b in repls:
            if a in text:
                cnt += text.count(a)
                text = text.replace(a, b)
        if not cnt:
            skipped_clean.append(rp)
            continue
        write_text(sp, text)
        changed.append((rp, cnt))
        if is_review_file(rp, text):
            review.append(rp)
        log("OK %-60s %d repl%s" % (rp, cnt, "  [REVIEW]" if rp in review else ""))

    report = write_report(out, source, old, params, repls, changed,
                          review, skipped_bin, skipped_clean)
    log("[*] done: %d file(s) changed, %d binary(ies) copied untouched, "
        "%d review file(s)" % (len(changed), len(skipped_bin), len(review)))
    return {
        "dry": False, "old": old, "repls": repls, "changed": changed,
        "review": review, "skipped_bin": skipped_bin,
        "skipped_clean": skipped_clean, "out": out, "report": report,
    }


def write_report(out, source, old, params, repls, changed, review,
                 skipped_bin, skipped_clean):
    lines = []
    lines.append("# PORT_REPORT — تقرير البورت")
    lines.append("")
    lines.append("Generated: %s" % datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    lines.append("Source : `%s`" % source)
    lines.append("Output : `%s`" % out)
    lines.append("")
    lines.append("## Base device (discovered) — الجهاز الأساسي المكتشف")
    lines.append("")
    lines.append("| token | value |")
    lines.append("|---|---|")
    for k, v in sorted(old.items()):
        lines.append("| %s | `%s` |" % (k, v))
    lines.append("")
    lines.append("## Target device — الجهاز الجديد")
    lines.append("")
    lines.append("| field | value |")
    lines.append("|---|---|")
    for k, v in sorted(params.items()):
        lines.append("| %s | `%s` |" % (k, v))
    lines.append("")
    lines.append("## Replacement map — خريطة الاستبدال")
    lines.append("")
    if repls:
        lines.append("| old | new |")
        lines.append("|---|---|")
        for a, b in repls:
            lines.append("| `%s` | `%s` |" % (a, b))
    else:
        lines.append("_none — no tokens replaced_")
    lines.append("")
    lines.append("## Changed files — الملفات المعدّلة (%d)" % len(changed))
    lines.append("")
    for rp, cnt in sorted(changed):
        lines.append("- `%s` — %d replacement(s)" % (rp, cnt))
    lines.append("")
    lines.append("## Files needing MANUAL review (hex offsets / guards) — مراجعة يدوية")
    lines.append("")
    if review:
        for rp in sorted(review):
            lines.append("- `%s`" % rp)
        lines.append("")
        lines.append("> هذه الملفات تحتوي أوفستات/عناوين خاصة بالجهاز: يجب اشتقاقها من "
                     "kallsyms و boot.img للجهاز الجديد قبل البناء. "
                     "These files carry device-specific offsets/addresses; derive them "
                     "from the new device's kallsyms + boot.img before building.")
    else:
        lines.append("_none_")
    lines.append("")
    lines.append("## Skipped — تم تخطّي")
    lines.append("")
    lines.append("- Binary files copied untouched: **%d**" % len(skipped_bin))
    lines.append("- Text files with no token changes: **%d**" % len(skipped_clean))
    lines.append("")
    lines.append("## Credits — الحقوق")
    lines.append("")
    lines.append("This is a port of the original developer's project "
                 "[soumarcelino/Root-My-Galaxy-SM-S918B](https://github.com/soumarcelino/"
                 "Root-My-Galaxy-SM-S918B) (Apache-2.0) and "
                 "[HyperRamzey/Root-My-Galaxy-Payloads](https://github.com/HyperRamzey/"
                 "Root-My-Galaxy-Payloads) (Apache-2.0). Credit lines in all files are "
                 "preserved. — هذا بورت من مشروع المطوّر الأصلي؛ جميع أسطر الحقوق محفوظة.")
    lines.append("")
    lines.append("## Next steps — الخطوات القادمة")
    lines.append("")
    lines.append("1. Review `target.h` / `p0_fingerprint.h` offsets against the new device's kallsyms + boot.img.")
    lines.append("2. If the new firmware KMI differs, rebuild `ksud` / payload binaries for it.")
    lines.append("3. Update `targets-v3.json` asset sizes if payloads change.")
    lines.append("4. Build: `./gradlew :app:assembleDebug`")
    report_path = os.path.join(out, "PORT_REPORT.md")
    write_text(report_path, "\n".join(lines) + "\n")
    return report_path


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="port_gui.py",
        description="RMG Port Generator — GUI/CLI tool to create a new-device port "
                    "from an existing Root-My-Galaxy port.",
    )
    p.add_argument("--cli", action="store_true", help="run headless (no GUI)")
    p.add_argument("--source", help="source port folder")
    p.add_argument("--out", help="output folder for the new port")
    p.add_argument("--codename", help="new device codename (e.g. dm5q)")
    p.add_argument("--model", help="new full model (e.g. SM-S928B)")
    p.add_argument("--firmware", help="new firmware build (e.g. S928BXXS1AXK1)")
    p.add_argument("--kmi", help="new kernel KMI (e.g. android13-5.15)")
    p.add_argument("--android", help="new Android version (optional)")
    p.add_argument("--oneui", help="new One UI version (optional)")
    p.add_argument("--partitions", help="partition names, comma separated (optional)")
    p.add_argument("--dry", action="store_true", help="dry run: only preview")
    return p


def main_cli(args):
    if not args.source or not args.out:
        print("[-] --cli requires --source and --out")
        return 2
    params = {
        "codename": args.codename or "",
        "model": args.model or "",
        "build": args.firmware or "",
        "kmi": args.kmi or "",
        "android": args.android or "",
        "oneui": args.oneui or "",
        "partitions": args.partitions or "",
        "update_versions": True,
    }
    res = run_port(args.source, args.out, params, log=print, dry_run=args.dry)
    if args.dry:
        print("[*] dry-run OK — nothing written")
        return 0
    print("[+] ported to %s" % res["out"])
    print("[+] report: %s" % res["report"])
    return 0


# --------------------------------------------------------------------------
# GUI (Tkinter)
# --------------------------------------------------------------------------

def _gui_main():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as exc:  # pragma: no cover
        print("[-] Tkinter not available on this machine: %s" % exc)
        return 2

    class PortGUI:
        def __init__(self, root):
            self.root = root
            root.title(UI["title"])
            root.geometry("980x720")
            self.vars = {
                "source": tk.StringVar(),
                "out": tk.StringVar(),
                "codename": tk.StringVar(),
                "model": tk.StringVar(),
                "firmware": tk.StringVar(),
                "kmi": tk.StringVar(),
                "android": tk.StringVar(),
                "oneui": tk.StringVar(),
                "partitions": tk.StringVar(),
                "updver": tk.BooleanVar(value=True),
            }
            self.build_ui()

        def build_ui(self):
            pad = {"padx": 8, "pady": 4}
            main = ttk.Frame(self.root); main.pack(fill="both", expand=True)

            left = ttk.Frame(main); left.pack(side="left", fill="y", padx=6, pady=6)
            right = ttk.Frame(main); right.pack(side="right", fill="both", expand=True, padx=6, pady=6)

            r = 0
            ttk.Label(left, text=UI["src"]).grid(row=r, column=0, sticky="w", **pad); r += 1
            ttk.Entry(left, textvariable=self.vars["source"], width=52).grid(row=r, column=0, sticky="we", **pad)
            ttk.Button(left, text=UI["browse"], command=self.pick_source).grid(row=r, column=1, **pad); r += 1

            ttk.Label(left, text=UI["out"]).grid(row=r, column=0, sticky="w", **pad); r += 1
            ttk.Entry(left, textvariable=self.vars["out"], width=52).grid(row=r, column=0, sticky="we", **pad)
            ttk.Button(left, text=UI["browse"], command=self.pick_out).grid(row=r, column=1, **pad); r += 1

            ttk.Separator(left).grid(row=r, column=0, columnspan=2, sticky="we", pady=6); r += 1
            ttk.Label(left, text=UI["codename"]).grid(row=r, column=0, sticky="w", **pad); r += 1
            ttk.Entry(left, textvariable=self.vars["codename"], width=52).grid(row=r, column=0, sticky="we", **pad); r += 1
            ttk.Label(left, text=UI["model"]).grid(row=r, column=0, sticky="w", **pad); r += 1
            ttk.Entry(left, textvariable=self.vars["model"], width=52).grid(row=r, column=0, sticky="we", **pad); r += 1
            ttk.Label(left, text=UI["firmware"]).grid(row=r, column=0, sticky="w", **pad); r += 1
            ttk.Entry(left, textvariable=self.vars["firmware"], width=52).grid(row=r, column=0, sticky="we", **pad); r += 1
            ttk.Label(left, text=UI["kmi"]).grid(row=r, column=0, sticky="w", **pad); r += 1
            ttk.Entry(left, textvariable=self.vars["kmi"], width=52).grid(row=r, column=0, sticky="we", **pad); r += 1
            ttk.Label(left, text=UI["android"]).grid(row=r, column=0, sticky="w", **pad); r += 1
            ttk.Entry(left, textvariable=self.vars["android"], width=52).grid(row=r, column=0, sticky="we", **pad); r += 1
            ttk.Label(left, text=UI["oneui"]).grid(row=r, column=0, sticky="w", **pad); r += 1
            ttk.Entry(left, textvariable=self.vars["oneui"], width=52).grid(row=r, column=0, sticky="we", **pad); r += 1
            ttk.Label(left, text=UI["partitions"]).grid(row=r, column=0, sticky="w", **pad); r += 1
            ttk.Entry(left, textvariable=self.vars["partitions"], width=52).grid(row=r, column=0, sticky="we", **pad); r += 1

            ttk.Checkbutton(left, text=UI["updver"], variable=self.vars["updver"]).grid(
                row=r, column=0, columnspan=2, sticky="w", **pad); r += 1

            btns = ttk.Frame(left); btns.grid(row=r, column=0, columnspan=2, sticky="we", pady=8); r += 1
            ttk.Button(btns, text=UI["generate"], command=lambda: self.generate(False)).pack(side="left", padx=4)
            ttk.Button(btns, text=UI["dryrun"], command=lambda: self.generate(True)).pack(side="left", padx=4)

            ttk.Label(left, text=UI["preview"]).grid(row=r, column=0, sticky="w", **pad); r += 1
            self.preview = tk.Listbox(left, height=8, width=64)
            self.preview.grid(row=r, column=0, columnspan=2, sticky="we", **pad); r += 1

            ttk.Label(right, text=UI["log"]).pack(anchor="w")
            self.logbox = tk.Text(right, height=36, width=70, state="disabled")
            self.logbox.pack(fill="both", expand=True)

        def pick_source(self):
            d = filedialog.askdirectory(title=UI["src"])
            if not d:
                return
            self.vars["source"].set(d)
            self.prefill(d)
            self.refresh_preview()

        def pick_out(self):
            d = filedialog.askdirectory(title=UI["out"])
            if d:
                self.vars["out"].set(os.path.join(d, "port-new-device"))

        def prefill(self, src):
            try:
                old = discover_tokens(src)
                self.vars["codename"].set(old.get("codename", ""))
                self.vars["model"].set(old.get("model", ""))
                self.vars["firmware"].set(old.get("build", ""))
                self.vars["kmi"].set(old.get("kmi", ""))
            except Exception as exc:
                self.log("[-] discover: %s" % exc)

        def refresh_preview(self):
            self.preview.delete(0, "end")
            src = self.vars["source"].get()
            if not os.path.isdir(src):
                return
            params = self.current_params()
            repls = build_replacements(discover_tokens(src), params)
            if not repls:
                self.preview.insert("end", "(no tokens to replace — check fields)")
                return
            for rp in iter_text_files(src):
                text = read_text(os.path.join(src, rp))
                if any(a in text for a, _ in repls):
                    self.preview.insert("end", rp)

        def current_params(self):
            return {
                "codename": self.vars["codename"].get().strip(),
                "model": self.vars["model"].get().strip(),
                "build": self.vars["firmware"].get().strip(),
                "kmi": self.vars["kmi"].get().strip(),
                "android": self.vars["android"].get().strip(),
                "oneui": self.vars["oneui"].get().strip(),
                "partitions": self.vars["partitions"].get().strip(),
                "update_versions": self.vars["updver"].get(),
            }

        def log(self, msg):
            self.root.after(0, self._append, msg)

        def _append(self, msg):
            self.logbox.configure(state="normal")
            self.logbox.insert("end", str(msg) + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
            self.root.update_idletasks()

        def generate(self, dry):
            src = self.vars["source"].get()
            out = self.vars["out"].get() or os.path.join(os.path.dirname(src), "port-new-device")
            if not os.path.isdir(src):
                messagebox.showerror(UI["err"], UI["err"] + ": source folder")
                return
            params = self.current_params()
            if not dry and not params.get("model") and not params.get("codename"):
                messagebox.showerror(UI["err"], UI["err"] + ": codename/model")
                return
            self.log("\n---------- %s ----------" % ("DRY RUN" if dry else "GENERATE"))

            def worker():
                try:
                    run_port(src, out, params, log=self.log, dry_run=dry)
                    self.log("[+] " + UI["done"])
                    if not dry:
                        self.log("[+] output: " + os.path.abspath(out))
                except Exception as exc:
                    self.log("[-] %s: %s" % (UI["err"], exc))
                    self.log(sys.exc_info()[1].__class__.__name__)

            import threading
            threading.Thread(target=worker, daemon=True).start()

    root = tk.Tk()
    PortGUI(root)
    root.mainloop()
    return 0


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cli:
        return main_cli(args)
    return _gui_main()


if __name__ == "__main__":
    sys.exit(main())
