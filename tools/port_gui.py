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

  python port_gui.py --auto --source SRC --device-files FOLDER [--out OUT] [--skip-build]
      # FULLY AUTOMATIC: scans FOLDER for boot.img/.lz4 + kernel + kallsyms.txt,
      # derives model/codename/firmware from file names, analyzes the boot image,
      # derives all kernel offsets, patches target.h/p0_fingerprint.h, and builds
      # the APK. Zero manual input.
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

RE_MODEL = re.compile(r"SM-[A-Z]\d{3}[A-Z0-9]*")
RE_BUILD = re.compile(r"(?<![A-Z0-9])([A-Z]\d{3}[A-Z])([A-Z]{2,4}[A-Z0-9][A-Z]{3}\d)(?![A-Z0-9])")
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
    p.add_argument("--analyze-boot", dest="analyze_boot", action="store_true",
                   help="analyze boot.img / boot.img.lz4 / kernel ELF and derive device offsets")
    p.add_argument("--boot", help="boot.img / boot.img.lz4 / kernel ELF to analyze")
    p.add_argument("--kallsyms", help="kallsyms.txt from the device (recommended)")
    p.add_argument("--text-base", help="override KIMAGE_TEXT_BASE (hex, e.g. 0xffffffc008000000)")
    p.add_argument("--out-offsets", help="output path for the generated device_offsets_<MODEL>.h")
    p.add_argument("--auto", dest="auto", action="store_true",
                   help="FULLY AUTOMATIC pipeline: detect device files -> derive offsets -> "
                        "port -> patch headers -> build APK (zero manual input)")
    p.add_argument("--device-files",
                   help="folder containing the new device's boot.img / boot.img.lz4 / kernel / "
                        "kallsyms.txt (default: current directory)")
    p.add_argument("--skip-build", action="store_true",
                   help="auto mode: skip the gradle APK build step")
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
# boot offset analyzer — محلّل ملف البوت واستخراج أوفستات الجهاز
# --------------------------------------------------------------------------

KALLSYMS_WANT = [
    ("init_task", ("init_task",)),
    ("commit_creds", ("commit_creds",)),
    ("prepare_kernel_cred", ("prepare_kernel_cred",)),
    ("override_creds", ("override_creds",)),
    ("revert_creds", ("revert_creds",)),
    ("selinux_enforcing", ("selinux_enforcing",)),
    ("selinux_enforcing_boot", ("selinux_enforcing_boot",)),
    ("kmalloc_caches", ("kmalloc_caches",)),
    ("kmalloc_caches_trace", ("kmalloc_caches_trace",)),
    ("ashmem_fops", ("ashmem_fops",)),
    ("anon_pipe_buf_ops", ("anon_pipe_buf_ops",)),
    ("system_unbound_wq", ("system_unbound_wq",)),
    ("call_usermodehelper_exec_work", ("call_usermodehelper_exec_work",)),
    ("run_cmd", ("run_cmd",)),
    ("usermodehelper_read_trylock", ("usermodehelper_read_trylock",)),
    ("init_cred", ("init_cred",)),
    ("cred_jar", ("cred_jar",)),
    ("__futex_wait", ("__futex_wait",)),
    ("trace_event_raw_event_sched_process_vfork", ("trace_event_raw_event_sched_process_vfork",)),
    ("swapper_pg_dir", ("swapper_pg_dir",)),
    ("_text", ("_text",)),
]


def _read_any(path):
    with open(path, "rb") as fh:
        return fh.read()


def decompress_lz4_file(path, log=None):
    """If path ends with .lz4, decompress (python lz4.frame, else lz4 CLI) and
    return the unpacked path. Otherwise return path unchanged."""
    log = log or (lambda s: None)
    if not str(path).lower().endswith(".lz4"):
        return path
    out = os.path.splitext(path)[0] + ".unpack"
    try:
        import lz4.frame
        with open(path, "rb") as fh, open(out, "wb") as fo:
            fo.write(lz4.frame.decompress(fh.read()))
        log("[*] lz4 decompressed (python lz4.frame) -> %s" % out)
        return out
    except Exception:
        pass
    import shutil
    exe = shutil.which("lz4")
    if exe:
        import subprocess
        subprocess.run([exe, "-d", "-f", path, out], check=True)
        log("[*] lz4 decompressed (CLI %s) -> %s" % (exe, out))
        return out
    raise RuntimeError(
        "boot file is .lz4 but no lz4 support found — run `pip install lz4` "
        "or install the lz4 CLI tool"
    )


def parse_elf(buf, log=None):
    """Parse a 64-bit little/big-endian ELF kernel image."""
    log = log or (lambda s: None)
    import struct
    if buf[:4] != b"\x7fELF":
        raise RuntimeError("not an ELF image")
    klass = buf[4]
    if klass != 2:
        raise RuntimeError("only 64-bit ELF kernels are supported")
    le = "<" if buf[5] == 1 else ">"
    e_type = struct.unpack_from(le + "H", buf, 16)[0]
    e_machine = struct.unpack_from(le + "H", buf, 18)[0]
    e_entry = struct.unpack_from(le + "Q", buf, 24)[0]
    e_phoff = struct.unpack_from(le + "Q", buf, 32)[0]
    e_phentsize = struct.unpack_from(le + "H", buf, 54)[0]
    e_phnum = struct.unpack_from(le + "H", buf, 56)[0]
    segs = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type = struct.unpack_from(le + "I", buf, off)[0]
        p_flags = struct.unpack_from(le + "I", buf, off + 4)[0]
        p_offset = struct.unpack_from(le + "Q", buf, off + 8)[0]
        p_vaddr = struct.unpack_from(le + "Q", buf, off + 16)[0]
        p_paddr = struct.unpack_from(le + "Q", buf, off + 24)[0]
        p_filesz = struct.unpack_from(le + "Q", buf, off + 32)[0]
        p_memsz = struct.unpack_from(le + "Q", buf, off + 40)[0]
        p_align = struct.unpack_from(le + "Q", buf, off + 48)[0]
        segs.append(dict(type=p_type, flags=p_flags, off=p_offset, vaddr=p_vaddr,
                         paddr=p_paddr, filesz=p_filesz, memsz=p_memsz, align=p_align))
    loads = [s for s in segs if s["type"] == 1]
    text = None
    for s in loads:
        if s["vaddr"] <= e_entry < s["vaddr"] + s["memsz"]:
            text = s
            break
    if text is None and loads:
        text = min(loads, key=lambda s: s["vaddr"])
    log("[*] ELF machine=0x%x entry=0x%x phnum=%d" % (e_machine, e_entry, len(loads)))
    for s in loads:
        log("    LOAD vaddr=0x%x paddr=0x%x flags=%d memsz=0x%x"
            % (s["vaddr"], s["paddr"], s["flags"], s["memsz"]))
    return {
        "machine": e_machine,
        "entry": e_entry,
        "text_vaddr": text["vaddr"] if text else 0,
        "text_paddr": text["paddr"] if text else 0,
        "segments": loads,
    }


def arm64_image_info(buf, log=None):
    """Detect a raw ARM64 kernel Image (magic b'ARM\\x64' at offset 0x38).
    Returns dict(text_offset, image_size) or None."""
    log = log or (lambda s: None)
    import struct
    if len(buf) < 0x40 or buf[0x38:0x3c] != b"ARM\x64":
        return None
    text_offset = struct.unpack_from("<Q", buf, 8)[0]
    image_size = struct.unpack_from("<Q", buf, 16)[0]
    log("[*] ARM64 Image: text_offset=0x%x image_size=0x%x"
        % (text_offset, image_size))
    log("    Samsung phys base is normally 0x80000000; P0_KERNEL_PHYS_LOAD = "
        "0x80000000 + text_offset (or the plain phys base used by the ROM). "
        "Verify against your target.h.")
    return {"text_offset": text_offset, "image_size": image_size}


def decompress_payload(buf, log=None):
    """Try gzip / lz4-frame / zstd decompression.
    Returns (decompressed_bytes, name) or (None, None)."""
    log = log or (lambda s: None)
    if buf[:2] == b"\x1f\x8b":
        import gzip
        return gzip.decompress(buf), "gzip"
    if buf[:4] == b"\x04\x22\x4d\x18":
        try:
            import lz4.frame
            return lz4.frame.decompress(buf), "lz4-frame"
        except Exception:
            pass
    if buf[:4] == b"\x28\xb5\x2f\xfd":
        try:
            import zstandard
            return zstandard.ZstdDecompressor().decompress(buf), "zstd"
        except Exception:
            pass
    return None, None


def _scan_payload_offset(payload, log=None):
    """Scan the first 2 MB (4 KB-aligned) for a known payload magic.
    Returns (offset, kind) or (None, None)."""
    log = log or (lambda s: None)
    limit = min(len(payload), 2 * 1024 * 1024)
    for off in range(0, limit, 0x1000):
        seg = payload[off:off + 64]
        if seg[:4] == b"\x7fELF":
            return off, "elf"
        if seg[0x38:0x3c] == b"ARM\x64":
            return off, "arm64-image"
        if seg[:2] == b"\x1f\x8b" or seg[:4] in (b"\x04\x22\x4d\x18", b"\x28\xb5\x2f\xfd", b"\xfd7zXZ\x00"):
            return off, "compressed"
    return None, None


def _unpack_kernel_payload(payload, res, log):
    """ELF -> parse; ARM64 Image -> detect; compressed -> decompress & recurse.
    Falls back to scanning for a known payload at an aligned offset; if nothing
    is found the payload type is recorded as unknown and offsets must come from
    kallsyms (KIMAGE_TEXT_BASE = `_text`, Samsung phys base 0x80000000)."""
    if payload[:4] == b"\x7fELF":
        res["payload_type"] = "elf"
        res["elf"] = parse_elf(payload, log)
        return payload
    ai = arm64_image_info(payload, log)
    if ai is not None:
        res["payload_type"] = "arm64-image"
        res["arm64_image"] = ai
        return payload
    dec, name = decompress_payload(payload, log)
    if dec is not None:
        log("[*] kernel payload is %s-compressed -> %d bytes" % (name, len(dec)))
        return _unpack_kernel_payload(dec, res, log)
    off, kind = _scan_payload_offset(payload, log)
    if off is not None:
        log("[*] payload magic found at file offset 0x%x (kind=%s)" % (off, kind))
        res["kernel_offset"] = off
        return _unpack_kernel_payload(payload[off:], res, log)
    res["payload_type"] = "unknown"
    log("[!] kernel payload format unrecognized (magic=%r); offsets will be "
        "derived from kallsyms only (KIMAGE_TEXT_BASE = `_text`, Samsung phys "
        "base assumed 0x80000000 — verify against the device)." % payload[:8])
    return payload


def analyze_boot_file(boot_path, log=None):
    """Analyze boot.img (Android v0-v4), boot.img.lz4, or a raw kernel ELF.
    Returns dict with format, kernel offset, and ELF-derived addresses."""
    log = log or (lambda s: None)
    import struct
    path = decompress_lz4_file(boot_path, log)
    buf = _read_any(path)
    res = {"file": boot_path, "unpacked": path, "size": len(buf)}
    if buf[:8] == b"ANDROID!":
        kernel_size = struct.unpack_from("<I", buf, 8)[0]
        hdr_ver = struct.unpack_from("<I", buf, 40)[0] if len(buf) >= 44 else 0
        res["format"] = "android-boot-v%d" % hdr_ver
        if hdr_ver >= 3:
            # v3/v4: kernel starts immediately after the fixed 4096-byte header
            koff, ksize = 4096, kernel_size or (len(buf) - 4096)
            res["kernel_offset"] = koff
            log("[*] Android boot image v%d (no page table) kernel at 0x%x size=%d"
                % (hdr_ver, koff, ksize))
        else:
            page_size = struct.unpack_from("<I", buf, 36)[0] or 4096
            kernel_addr = struct.unpack_from("<I", buf, 12)[0]
            koff, ksize = page_size, kernel_size
            res["kernel_offset"] = koff
            res["kernel_addr"] = kernel_addr
            log("[*] Android boot image v%d page=%d kernel_addr=0x%x size=%d"
                % (hdr_ver, page_size, kernel_addr, kernel_size))
        _unpack_kernel_payload(buf[koff:koff + ksize], res, log)
    elif buf[:4] == b"\x7fELF":
        res["format"] = "raw-elf-kernel"
        res["kernel_offset"] = 0
        res["payload_type"] = "elf"
        res["elf"] = parse_elf(buf, log)
    elif arm64_image_info(buf, log) is not None:
        res["format"] = "raw-arm64-image"
        res["kernel_offset"] = 0
        res["payload_type"] = "arm64-image"
        res["arm64_image"] = arm64_image_info(buf, log) or {}
    else:
        dec, name = decompress_payload(buf, log)
        if dec is not None:
            log("[*] kernel payload is %s-compressed -> %d bytes" % (name, len(dec)))
            _unpack_kernel_payload(dec, res, log)
        else:
            raise RuntimeError(
                "unrecognized file: not ANDROID! boot image, not ELF kernel, "
                "not ARM64 Image, not gzip/lz4/zstd (magic=%r)" % buf[:8])
    if res.get("elf"):
        elf = res["elf"]
        res["text_base"] = elf["text_vaddr"]
        res["phys_load"] = elf["text_paddr"]
        res["phys_load_masked"] = elf["text_paddr"] & ~(0x200000 - 1)
        res["entry"] = elf["entry"]
    else:
        ai = res.get("arm64_image") or {}
        res["text_base"] = 0  # resolved from kallsyms `_text` or --text-base
        res["phys_load"] = (0x80000000 + ai.get("text_offset", 0)) & 0xFFFFFFFF
        res["phys_load_masked"] = res["phys_load"] & ~(0x200000 - 1)
        # unknown payload: fall back to the Samsung Exynos phys base (0x80000000)
        if res.get("payload_type") == "unknown":
            res["phys_load"] = 0x80000000
            res["phys_load_masked"] = 0x80000000
        res["entry"] = 0
    return res


def parse_kallsyms(path, text_base, log=None):
    """Parse a device kallsyms.txt and map wanted symbols -> (addr, offset)."""
    log = log or (lambda s: None)
    found = {}
    total = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                addr = int(parts[0], 16)
            except ValueError:
                continue
            name = parts[-1].strip()
            total += 1
            key = name.split(".")[0]
            if key in found:
                continue
            if key in dict(KALLSYMS_WANT):
                found[key] = addr
    res = {}
    for label, _ in KALLSYMS_WANT:
        if label in found:
            a = found[label]
            off = a - text_base if a > text_base else a
            res[label] = {"addr": a, "off": off}
    log("[*] kallsyms: %d lines scanned, %d/%d wanted symbols found"
        % (total, len(res), len(KALLSYMS_WANT)))
    return res


def build_offsets_header(res, syms, params, log=None):
    log = log or (lambda s: None)
    model = (params.get("model") or "DEVICE").replace(" ", "_")
    L = []
    L.append("/*")
    L.append(" * device_offsets_%s.h — auto-generated by tools/port_gui.py analyze-boot" % model)
    L.append(" * boot   : %s" % res["file"])
    L.append(" * format : %s  kernel_offset=%d" % (res["format"], res.get("kernel_offset", 0)))
    L.append(" *")
    L.append(" * Symbol offsets are derived from the device kallsyms.")
    L.append(" * Exploit-semantic defines (SLIDE_*, P0_ORACLE_*, *BANK_*, MM_STRUCT_SZ,")
    L.append(" * TASK_STRUCT_*_OFF, FAKE_TASK_*, P0_PAGE_OFFSET) are NOT derivable from")
    L.append(" * kallsyms — copy them from the source target.h and verify manually.")
    L.append(" */")
    L.append("")
    L.append("#define KIMAGE_TEXT_BASE      0x%016x" % res["text_base"])
    L.append("#define P0_KERNEL_PHYS_LOAD   0x%08x   /* text LOAD seg paddr */" % res["phys_load"])
    L.append("#define P0_KERNEL_PHYS_LOAD_M 0x%08x   /* 2MB-aligned */" % res["phys_load_masked"])
    L.append("#define BOOT_ENTRY            0x%016x" % res["entry"])
    L.append("")
    L.append("/* kallsyms-derived offsets (addr - KIMAGE_TEXT_BASE) */")
    for label in (_l for _l, _ in KALLSYMS_WANT):
        if label in syms:
            L.append("#define %-40s 0x%08x" % (label.upper() + "_OFF", syms[label]["off"]))
    L.append("")
    L.append("/* not automatic: SLIDE_TRACEFS_WORKER_CALLER_OFF, SLIDE_BANK_*, P0_ORACLE_*,")
    L.append("   TASK_STRUCT_CRED_OFF, FAKE_TASK_*, MM_STRUCT_SZ, P0_PAGE_OFFSET */")
    return "\n".join(L) + "\n"


def _dump_offsets_table(res, syms, log=None):
    log = log or (lambda s: None)
    log("")
    log("=== device offsets (KIMAGE_TEXT_BASE = 0x%016x) ===" % res["text_base"])
    log("P0_KERNEL_PHYS_LOAD    0x%08x   (text LOAD seg paddr)" % res["phys_load"])
    log("P0_KERNEL_PHYS_LOAD_M  0x%08x   (2MB-aligned)" % res["phys_load_masked"])
    log("BOOT_ENTRY             0x%016x" % res["entry"])
    log("")
    log("%-44s %-18s %s" % ("SYMBOL", "ADDR", "OFFSET"))
    for label in (_l for _l, _ in KALLSYMS_WANT):
        if label in syms:
            d = syms[label]
            log("%-44s 0x%016x 0x%08x" % (label.upper() + "_OFF", d["addr"], d["off"]))
    missing = [l for l, _ in KALLSYMS_WANT if l not in syms]
    if missing:
        log("")
        log("[!] not found in kallsyms: %s" % ", ".join(missing))


def main_boot_analyzer(args, log=None):
    log = log or print
    if not args.boot:
        print("[-] analyze-boot requires --boot boot.img|boot.img.lz4|kernel")
        return 2
    params = {"model": args.model or "", "codename": args.codename or ""}
    res = analyze_boot_file(args.boot, log=log)
    syms = {}
    if args.kallsyms:
        syms = parse_kallsyms(args.kallsyms, 0, log=log)
    text_base = res["text_base"]
    if args.text_base:
        text_base = int(args.text_base, 0)
        log("[*] KIMAGE_TEXT_BASE overridden: 0x%x" % text_base)
    elif not text_base and syms.get("_text"):
        text_base = syms["_text"]["addr"]
        log("[*] KIMAGE_TEXT_BASE from kallsyms _text: 0x%x" % text_base)
    if not text_base:
        raise SystemExit("[!] cannot determine KIMAGE_TEXT_BASE — pass --text-base "
                         "0xffffffc008000000 (kallsyms `_text`) or a kallsyms file")
    res["text_base"] = text_base
    for k in syms:
        a = syms[k]["addr"]
        syms[k]["off"] = a - text_base if a >= text_base else a
    _dump_offsets_table(res, syms, log=log)
    header = build_offsets_header(res, syms, params, log=log)
    out = args.out_offsets or ("device_offsets_%s.h" % (params["model"] or "DEVICE"))
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(header)
    log("[+] offsets header written: %s" % out)
    return 0


def _boot_gui_window(parent):
    """Standalone Toplevel: analyze boot.img/.lz4/kallsyms and save offsets."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    import threading
    win = tk.Toplevel(parent)
    win.title("RMG Boot Analyzer — محلّل البوت (الأوفستات)")
    win.geometry("760x560")
    v = {"boot": tk.StringVar(), "kallsyms": tk.StringVar(), "model": tk.StringVar(),
         "textbase": tk.StringVar(), "out": tk.StringVar()}
    frm = ttk.Frame(win)
    frm.pack(fill="both", expand=True, padx=8, pady=8)

    def row(label, var, btn, r):
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", padx=2, pady=2)
        ttk.Entry(frm, textvariable=var, width=64).grid(row=r, column=1, sticky="we", padx=2, pady=2)
        if btn:
            ttk.Button(frm, text="…", width=3, command=btn).grid(row=r, column=2, padx=2)

    row("boot.img / boot.img.lz4 / kernel:", v["boot"],
        lambda: v["boot"].set(filedialog.askopenfilename()), 0)
    row("kallsyms.txt (اختياري لكن مهم):", v["kallsyms"],
        lambda: v["kallsyms"].set(filedialog.askopenfilename()), 1)
    row("الموديل (مثل SM-S918N):", v["model"], None, 2)
    row("KIMAGE_TEXT_BASE (اختياري 0x…):", v["textbase"], None, 3)
    row("حفظ الـ header في:", v["out"],
        lambda: v["out"].set(filedialog.asksaveasfilename(defaultextension=".h")), 4)
    box = tk.Text(frm, height=20, state="disabled", font=("TkFixedFont", 9))
    box.grid(row=5, column=0, columnspan=3, sticky="nsew")
    frm.rowconfigure(5, weight=1)
    frm.columnconfigure(1, weight=1)

    def log(s):
        box.configure(state="normal")
        box.insert("end", str(s) + "\n")
        box.see("end")
        box.configure(state="disabled")

    def run():
        boot = v["boot"].get()
        if not boot:
            messagebox.showerror("خطأ", "اختار ملف boot.img أولًا")
            return
        try:
            params = {"model": v["model"].get().strip() or "DEVICE", "codename": ""}
            res = analyze_boot_file(boot, log=log)
            syms = {}
            if v["kallsyms"].get().strip():
                syms = parse_kallsyms(v["kallsyms"].get().strip(), 0, log=log)
            else:
                log("[!] بدون kallsyms — أوفستات P0 فقط متاحة")
            tb = res["text_base"]
            if v["textbase"].get().strip():
                tb = int(v["textbase"].get().strip(), 0)
            elif not tb and syms.get("_text"):
                tb = syms["_text"]["addr"]
                log("[*] KIMAGE_TEXT_BASE من kallsyms _text: 0x%x" % tb)
            res["text_base"] = tb
            for k in syms:
                a = syms[k]["addr"]
                syms[k]["off"] = a - tb if (tb and a >= tb) else a
            _dump_offsets_table(res, syms, log=log)
            header = build_offsets_header(res, syms, params, log=log)
            out = v["out"].get().strip() or ("device_offsets_%s.h" % params["model"])
            with open(out, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(header)
            log("[+] الـ header محفوظ: " + out)
        except Exception as exc:
            log("[-] " + str(exc))

    ttk.Button(frm, text="تحليل واستخراج الأوفستات  Analyze & Extract",
               command=lambda: threading.Thread(target=run, daemon=True).start()
               ).grid(row=6, column=0, columnspan=3, pady=6)


# --------------------------------------------------------------------------
# AUTOMATIC end-to-end pipeline (--auto) — zero manual input
# --------------------------------------------------------------------------

CODENAME_MAP = {
    "908": "dm2q", "916": "dm1q", "918": "dm3q", "926": "dm2q",
    "928": "dm5q", "936": "dm3q", "986": "dm3q", "711": "dm4q",
}
OFFSET_DEFINES = [
    ("INIT_TASK_OFF", "init_task"),
    ("COMMIT_CREDS_OFF", "commit_creds"),
    ("PREPARE_KERNEL_CRED_OFF", "prepare_kernel_cred"),
    ("OVERRIDE_CREDS_OFF", "override_creds"),
    ("OVERIDE_CREDS_OFF", "override_creds"),
    ("REVERT_CREDS_OFF", "revert_creds"),
    ("SELINUX_ENFORCING_OFF", "selinux_enforcing"),
    ("SELINUX_ENFORCING_BOOT_OFF", "selinux_enforcing_boot"),
    ("KMALLOC_CACHES_OFF", "kmalloc_caches"),
    ("ASHMEM_FOPS_OFF", "ashmem_fops"),
    ("ANON_PIPE_BUF_OPS_OFF", "anon_pipe_buf_ops"),
    ("SYSTEM_UNBOUND_WQ_OFF", "system_unbound_wq"),
    ("CALL_USERMODEHELPER_EXEC_WORK_OFF", "call_usermodehelper_exec_work"),
    ("RUN_CMD_OFF", "run_cmd"),
    ("USERMODEHELPER_READ_TRYLOCK_OFF", "usermodehelper_read_trylock"),
    ("INIT_CRED_OFF", "init_cred"),
    ("CRED_JAR_OFF", "cred_jar"),
    ("SWAPPER_PG_DIR_OFF", "swapper_pg_dir"),
]


def detect_device_from_folder(folder, log=None):
    """Scan a folder of firmware/device files for model/codename/build and the
    paths of boot.img(.lz4), kernel and kallsyms.txt. Zero input needed."""
    log = log or (lambda s: None)
    names, paths = [], {}
    for dp, dn, fns in os.walk(folder):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for fn in fns:
            names.append(fn)
            low = fn.lower()
            fp = os.path.join(dp, fn)
            if low == "boot.img" or low.startswith("boot.img.") or low.startswith("boot-"):
                paths.setdefault("boot", fp)
            elif low == "kernel" or low.startswith("kernel."):
                paths.setdefault("kernel", fp)
            elif low == "kallsyms.txt":
                paths.setdefault("kallsyms", fp)
    joined = " ".join(names)
    det = {"build": "", "model": "", "codename": "", "kmi": ""}
    m = RE_BUILD.search(joined)
    if m:
        det["build"] = m.group(0)
    m = RE_MODEL.search(joined)
    if m:
        det["model"] = m.group(0)
    if not det["model"] and det["build"] and len(det["build"]) >= 5:
        # S918NKSS8FZG1 -> SM-S918N
        det["model"] = "SM-S" + det["build"][1:5]
    stub = det["model"][4:7] if det["model"].startswith("SM-S") else ""
    if stub in CODENAME_MAP:
        det["codename"] = CODENAME_MAP[stub]
    elif det["build"]:
        det["codename"] = ("dm-" + det["build"][1:5]).lower()
    log("[auto] scanned %d file(s): build=%r model=%r codename=%r"
        % (len(names), det["build"], det["model"], det["codename"]))
    log("[auto] device files found: %s" % json.dumps(paths, ensure_ascii=False))
    return det, paths


def auto_patch_offsets(out_root, res, syms, log=None):
    """Rewrite every `#define <OFFSET> 0x…` we derived, inside every target.h /
    p0_fingerprint.h / offsets header in the ported tree. Returns patched count."""
    log = log or (lambda s: None)
    tb = res.get("text_base") or 0
    phys = res.get("phys_load") or 0
    values = {}
    for define, sym in OFFSET_DEFINES:
        if sym in syms:
            values[define] = syms[sym]["off"]
    if tb:
        values["KIMAGE_TEXT_BASE"] = tb
    if phys:
        values["P0_KERNEL_PHYS_LOAD"] = phys
        values["P0_KERNEL_PHYS_LOAD_M"] = phys & ~(0x200000 - 1)
    if not values:
        log("[auto] no kallsyms-derived offsets available — headers left untouched")
        return 0
    patched = 0
    for dp, _, fns in os.walk(out_root):
        if any(x in dp.split(os.sep) for x in SKIP_DIRS):
            continue
        for fn in fns:
            if os.path.splitext(fn)[1].lower() not in TEXT_EXT:
                continue
            fp = os.path.join(dp, fn)
            text = read_text(fp)
            if not any(("#define " + k) in text for k in values):
                continue
            changed = False
            for define, val in values.items():
                pat = re.compile(r"(#define\s+%s\s+)0x[0-9a-fA-F]+" % re.escape(define))
                if pat.search(text):
                    text = pat.sub(lambda m: m.group(1) + ("0x%08x" % val), text)
                    changed = True
            if changed:
                write_text(fp, text)
                patched += 1
                log("[auto] patched %s" % os.path.relpath(fp, out_root))
    return patched


def main_auto(args, log=None):
    """Full end-to-end port: detect -> analyze -> port -> patch -> build."""
    log = log or print
    source = os.path.abspath(args.source or os.path.dirname(os.path.abspath(__file__)))
    devfolder = os.path.abspath(args.device_files or os.getcwd())
    out = os.path.abspath(args.out or (source + "-port-AUTO"))
    if not os.path.isdir(source):
        log("[-] source not found: %s" % source)
        return 2
    det, paths = detect_device_from_folder(devfolder, log)
    old = discover_tokens(source)
    log("[auto] base discovered: %s" % json.dumps(old, ensure_ascii=False))
    params = {
        "codename": det["codename"] or old.get("codename", ""),
        "model": det["model"] or old.get("model", ""),
        "build": det["build"] or old.get("build", ""),
        "kmi": old.get("kmi", "android13-5.15"),
        "android": "", "oneui": "", "partitions": "",
        "update_versions": True,
    }
    if not params["model"]:
        log("[-] could not derive the model — put boot.img/kallsyms.txt or a firmware file "
            "whose name contains the model (e.g. AP_S928BXXX_…) in the device folder")
        return 2
    res = run_port(source, out, params, log=log, dry_run=False)
    syms = {}
    boot = paths.get("boot") or paths.get("kernel")
    if boot:
        try:
            ban = analyze_boot_file(boot, log=log)
            res["boot"] = ban
            res["phys_load"] = ban.get("phys_load") or 0
        except Exception as exc:
            log("[auto] boot analysis failed (continuing with kallsyms): %s" % exc)
    if paths.get("kallsyms"):
        tb = (res.get("boot") or {}).get("text_base") or 0
        syms = parse_kallsyms(paths["kallsyms"], 0, log=log)
        if not tb and syms.get("_text"):
            tb = syms["_text"]["addr"]
            log("[auto] KIMAGE_TEXT_BASE from kallsyms _text: 0x%x" % tb)
        for k in syms:
            a = syms[k]["addr"]
            syms[k]["off"] = a - tb if (tb and a >= tb) else a
        res["text_base"] = tb
    else:
        log("[auto] no kallsyms.txt in device folder — headers left untouched; "
            "drop kallsyms.txt beside boot.img to auto-patch all offsets")
    n = auto_patch_offsets(out, res, syms, log=log)
    log("[auto] %d header file(s) auto-patched with device offsets" % n)
    apk = None
    if not args.skip_build:
        g = os.path.join(out, "gradlew")
        if os.path.exists(g):
            import stat, subprocess
            os.chmod(g, os.stat(g).st_mode | stat.S_IEXEC)
            log("[auto] building APK (gradlew :app:assembleDebug)…")
            try:
                r = subprocess.run([g, ":app:assembleDebug", "--no-daemon"],
                                   cwd=out, capture_output=True, text=True, timeout=1800)
            except Exception as exc:
                log("[auto] gradle wrapper failed: %s" % exc)
                return 1
            if r.returncode == 0:
                cand = os.path.join(out, "app", "build", "outputs", "apk", "debug")
                apks = (sorted(os.path.join(cand, f) for f in os.listdir(cand)
                               if f.endswith(".apk")) if os.path.isdir(cand) else [])
                apk = apks[-1] if apks else None
                log("[auto] APK built: %s" % apk)
            else:
                log("[auto] gradle build failed rc=%d (tail: %s)"
                    % (r.returncode, (r.stderr or r.stdout)[-500:]))
        else:
            log("[auto] no gradlew in output — skipped build")
    log("[+] AUTO DONE  out=%s  offsets_patched=%d  apk=%s" % (out, n, apk or "none"))
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
            ttk.Button(btns, text="Boot Analyzer  محلّل البوت", command=self.open_boot_analyzer).pack(side="left", padx=4)
            ttk.Button(btns, text="Auto  أوتوماتيك", command=self.open_auto).pack(side="left", padx=4)

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

        def open_boot_analyzer(self):
            _boot_gui_window(self.root)

        def open_auto(self):
            src = filedialog.askdirectory(title="مجلد البورت المصدر  Source port folder")
            if not src:
                return
            dev = filedialog.askdirectory(title="مجلد ملفات الجهاز  Device files (boot/kallsyms)")
            if not dev:
                return

            def worker():
                self.log("\n----- AUTO PIPELINE -----")
                try:
                    import types
                    a = types.SimpleNamespace(auto=True, source=src, out=src + "-port-AUTO",
                                              device_files=dev, skip_build=False)
                    main_auto(a, log=self.log)
                    self.log("[+] " + UI["done"])
                except Exception as exc:
                    self.log("[-] auto: %s" % exc)

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
    if getattr(args, "auto", False):
        return main_auto(args)
    if getattr(args, "analyze_boot", False):
        return main_boot_analyzer(args)
    if args.cli:
        return main_cli(args)
    return _gui_main()


if __name__ == "__main__":
    sys.exit(main())
