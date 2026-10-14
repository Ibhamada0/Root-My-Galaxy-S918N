#!/usr/bin/env python3
"""Online, fail-closed GZIF port using pinned upstream BOPE tools.

BOPE and the target-generation implementation are by soumarcelino:
https://github.com/soumarcelino/Root-My-Galaxy-SM-S918B
This adapter accepts the owner's standalone stock boot.img.lz4.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import urlparse
from urllib.request import urlopen

BUILD = "S918NKSU8GZIF"
DISPLAY = "CP2A.260605.016." + BUILD
RELEASE = "5.15.197-android13-8-34343818-ab" + BUILD
BOOT_SHA256 = "c7f37c99b54a8a164b082a88af5a833f7f48bcd4ca98db9dbd8b4192e984253b"
RAW_BOOT_SHA256 = "1552a1dbf45a95ef25626097605c2f1d3e64c1b557353887b905be1ea166635e"
UPSTREAM_SHA = "362416498212658e17f72f05e64259b85998d75b"
SLUG = "s918ngzif"
MAX_COMPRESSED_SIZE = 64 * 1024 * 1024

def validate_inputs(url: str, fingerprint: str) -> None:
    if url:
        p = urlparse(url)
        # Public GitHub release assets or raw repository files only.
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            raise ValueError("boot_url must be a public HTTPS GitHub download URL")
        if p.hostname == "github.com":
            if not re.fullmatch(r"/[^/]+/[^/]+/releases/download/[^/]+/[^/]+", p.path):
                raise ValueError("Use the GitHub release asset download link")
        elif p.hostname == "raw.githubusercontent.com":
            if len(p.path.strip("/").split("/")) < 4:
                raise ValueError("Incomplete raw GitHub file URL")
        else:
            raise ValueError("boot_url must use github.com or raw.githubusercontent.com")
        if p.query or p.fragment:
            raise ValueError("Use a public download URL without query or fragment")
    if fingerprint and not re.fullmatch(
        r"samsung/[A-Za-z0-9_.-]+/dm3q:17/CP2A\.260605\.016/"
        r"S918NKSU8GZIF:user/release-keys", fingerprint
    ):
        raise ValueError("Fingerprint must be the exact GZIF / Android 17 device value")

def resolve_inputs(config_path: Path, output: Path) -> dict:
    config = json.loads(config_path.read_text())
    url = os.environ.get("INPUT_BOOT_URL", "").strip() or config.get("boot_url", "")
    fingerprint = os.environ.get("INPUT_FINGERPRINT", "").strip() or config.get("fingerprint", "")
    validate_inputs(url, fingerprint)
    data = {"boot_url": url, "fingerprint": fingerprint}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2) + "\n")
    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as stream:
            stream.write("ready=" + str(bool(url)).lower() + "\n")
    return data

def sha256(path: Path) -> str:
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()

def download_boot(url: str, destination: Path) -> None:
    validate_inputs(url, "")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # GitHub redirects public release assets to its authenticated asset CDN.
    with urlopen(url, timeout=90) as response, destination.open("wb") as out:
        if urlparse(response.url).scheme != "https":
            raise ValueError("Insecure download redirect")
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_COMPRESSED_SIZE:
                raise ValueError("Unexpected boot download size")
            out.write(chunk)
    if sha256(destination) != BOOT_SHA256:
        raise ValueError("boot.img.lz4 SHA-256 differs from the owner's verified GZIF file")

def run_port(project: Path, inputs: dict, report_dir: Path) -> None:
    project = project.resolve()
    report_dir = report_dir.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    actual_sha = subprocess.check_output(
        ["git", "-C", str(project), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual_sha != UPSTREAM_SHA:
        raise ValueError("Upstream checkout does not match the reviewed pinned commit")
    validate_inputs(inputs["boot_url"], inputs["fingerprint"])
    if not inputs["boot_url"]:
        raise ValueError("A boot download URL is required")
    sys.path.insert(0, str(project / "tools"))
    from bope.kernel import prepare_kernel
    from bope.contract import derive_contract, parse_numeric_macros, verify_contract
    from bope.target import create_target_skeleton, build_target, app_profile, integrate_app
    from bope.kernelsu import prepare_kernelsu
    from bope.factory_cli import _enforce_exact_runtime_identity, _string_macro

    donor = project / "targets/zzi8-WIP"
    donor_header = donor / "brazilian-open-payload-engine/src/target.h"
    target = project / ("targets/" + SLUG + "-WIP")
    if target.exists():
        raise ValueError("Refusing to overwrite an existing target")
    fingerprint = inputs["fingerprint"]
    info = SimpleNamespace(
        slug=SLUG, model="SM-S918N", device="dm3q", post_build=BUILD,
        pre_build=_string_macro(donor_header, "TARGET_BUILD"),
        post_fingerprint=fingerprint,
    )
    create_target_skeleton(donor, target, info)
    # The source is a standalone boot image, not an OTA or synthesized factory ZIP.
    (target / "README.md").write_text(
        "# SM-S918N GZIF experimental port\n\n"
        "Source: owner's standalone stock boot.img.lz4, verified by SHA-256.\n"
        "Generated with pinned soumarcelino BOPE tools. Device testing is pending.\n"
    )
    firmware = target / "firmware"
    logs = target / "port-logs"
    logs.mkdir(parents=True, exist_ok=True)
    compressed = firmware / "boot.img.lz4"
    boot = firmware / "boot_GZIF.img"
    download_boot(inputs["boot_url"], compressed)
    subprocess.run(["lz4", "-d", "-f", str(compressed), str(boot)], check=True)
    if sha256(boot) != RAW_BOOT_SHA256:
        raise ValueError("Decompressed boot image SHA-256 mismatch")
    base = parse_numeric_macros(donor_header)["TARGET_KIMAGE_TEXT_BASE"]
    def tool(name: str) -> Path:
        found = shutil.which(name)
        if not found:
            raise RuntimeError("Required tool unavailable: " + name)
        return Path(found)
    kernel = prepare_kernel(
        boot, firmware, "GZIF", base_address=base, unpacker=None,
        kallsyms_finder=tool("kallsyms-finder"), vmlinux_to_elf=tool("vmlinux-to-elf"),
        pahole=tool("pahole"), logs_dir=logs,
    )
    if kernel.identity.release != RELEASE:
        raise ValueError("Kernel release does not match the owner's GZIF device")
    evidence = {
        "status": "KERNEL_ANALYZED_RUNTIME_FINGERPRINT_REQUIRED",
        "upstream_repository": "soumarcelino/Root-My-Galaxy-SM-S918B",
        "upstream_commit": UPSTREAM_SHA,
        "target": {"model": "SM-S918N", "build_display": DISPLAY,
                   "kernel_release": kernel.identity.release,
                   "kernel_version": kernel.identity.version_info},
        "boot_lz4_sha256": sha256(compressed), "boot_sha256": sha256(boot),
        "device_validated": False,
    }
    evidence_path = report_dir / "gzif-report.json"
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    contract = derive_contract(
        donor_header, target / "brazilian-open-payload-engine/src/target.h",
        target_name=SLUG, model="SM-S918N", device="dm3q", build=BUILD,
        fingerprint=fingerprint, kernel_release=kernel.identity.release,
        kernel_version=kernel.identity.version_info, elf=kernel.elf, btf=kernel.btf,
        llvm_nm=tool("llvm-nm"), pahole=tool("pahole"),
    )
    verification = verify_contract(
        contract.header, elf=kernel.elf, btf=kernel.btf,
        llvm_nm=tool("llvm-nm"), pahole=tool("pahole"),
    )
    evidence["contract"] = {
        "verification": verification, "changed": contract.changed,
        "inherited_calibration": contract.inherited,
    }
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    if not verification["passed"]:
        raise RuntimeError("Generated GZIF contract failed independent verification")
    if not fingerprint:
        evidence["status"] = "CONTRACT_VERIFIED_RUNTIME_FINGERPRINT_REQUIRED"
        evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
        (target / "port-manifest.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print("GZIF contract verified. Exact device fingerprint is required before compilation.")
        return
    _enforce_exact_runtime_identity(target / "brazilian-open-payload-engine")
    ndk = Path(os.environ["ANDROID_NDK_HOME"])
    artifacts = build_target(target, ndk=ndk, logs=logs)
    ksu = prepare_kernelsu(
        donor, target, slug=SLUG,
        donor_release=_string_macro(donor_header, "TARGET_KERNEL_RELEASE"),
        target_release=kernel.identity.release, target_kallsyms=kernel.kallsyms,
        target_vmlinux=kernel.elf, target_btf=kernel.btf,
        llvm_nm=tool("llvm-nm"), pahole=tool("pahole"),
        ksu_source=Path(os.environ["KSU_SOURCE"]), ndk=ndk, logs_dir=logs,
    )
    ksud = target / ksu["ksud"]["path"]
    profile = app_profile(info, kernel, artifacts, ksud)
    profile["displayName"] += " | EXPERIMENTAL - device validation pending"
    # BOPE needs upstream's helper/launcher/mmFactory-aware app client.
    # Build an isolated experimental client; do not label the existing app supported.
    manifest = project / "app/src/main/assets/targets-v3.json"
    manifest.write_text(json.dumps({"schemaVersion": 3, "payloads": []}) + "\n")
    integrate_app(project, profile, artifacts, ksud)
    gradle = project / "app/build.gradle.kts"
    old = 'applicationId = "io.github.rootmygalaxy.s23ultra"'
    text = gradle.read_text()
    if text.count(old) != 1:
        raise RuntimeError("Unexpected upstream application ID declaration")
    gradle.write_text(text.replace(
        old, 'applicationId = "io.github.ibhamada0.rootmygalaxy.gzif.experimental"'
    ))
    evidence.update(status="STATIC_CHECKS_PASSED_DEVICE_TEST_PENDING",
                    kernelsu=ksu, app_profile=profile)
    evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
    (target / "port-manifest.json").write_text(json.dumps(evidence, indent=2) + "\n")
    (report_dir / "apk-ready").write_text("Build debug APK from the pinned upstream client.\n")

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolve-inputs", action="store_true")
    parser.add_argument("--config", type=Path, default=Path("ci/gzif-input.json"))
    parser.add_argument("--inputs", type=Path, default=Path("online-out/inputs.json"))
    parser.add_argument("--project", type=Path, default=Path("online-upstream"))
    parser.add_argument("--reports", type=Path, default=Path("online-out"))
    args = parser.parse_args()
    if args.resolve_inputs:
        inputs = resolve_inputs(args.config, args.inputs)
        print("Input ready" if inputs["boot_url"] else "Waiting for a public boot download URL")
    else:
        run_port(args.project, json.loads(args.inputs.read_text()), args.reports)

if __name__ == "__main__":
    main()
