# Root My Galaxy SM-S918N

Root My Galaxy for the Samsung Galaxy S23 Ultra `SM-S918N` (`dm3q`). This
repository contains the Android app, target configuration, porting sources,
patches, and build tools for the `S918NKSS8FZG1` firmware profile.

This project is a **port** of the original developer's
[Root-My-Galaxy-SM-S918B](https://github.com/soumarcelino/Root-My-Galaxy-SM-S918B)
project, adapted from `SM-S918B` to `SM-S918N`. See
[Credits And Base Repository](#credits-and-base-repository) below.

[Releases](https://github.com/Ibhamada0/Root-My-Galaxy-S918N/releases) ·
[Documentation](docs/README.md)

Use this only on devices you own or are explicitly authorized to test.

# Root My Galaxy for SM-S918N is here

## Port Overview

The original developer's project supports `SM-S918B` (firmware
`S918BXXSAFZG1`). This repository adapts the same app, payload packaging and
KernelSU late-load flow to `SM-S918N` (firmware `S918NKSS8FZG1`).

### Changes made in this port (vs. the SM-S918B original)

- Target profile rebuilt for `SM-S918N`: `src/targets/dm3q-S918N*` /
  `assets/targets-v3.json` payload entries (`dm3q-S918NKSS8FZG1`).
- KernelSU **Regular (3.2.5)** is the default and only engine exposed in the
  UI; the KernelSU Next assets stay bundled in the APK but are no longer
  selectable.
- Both manager APKs (`KernelSU 3.2.5` + `KernelSU Next 3.3.0`) are bundled
  inside the app and installed **offline** from the bundled copy — no download
  from the internet, no browser fallback.
- `Auto-start Shizuku` and `Root after every boot` settings added
  (`BootReceiver` on `BOOT_COMPLETED`).
- Manual "Install Manager" button in Settings installs the selected bundled
  manager on demand.

## Validated Target

```text
model: SM-S918N
device: dm3q
firmware: S918NKSS8FZG1
kernel release: 5.15.189-android13-8-...-abS918NKSS8FZG1 (KMI android13-5.15)
One UI: 8.5
Android: 16
```

Device parameters (kernel offsets, BTF symbols) for this profile were derived
from the device's own `boot.img` and `kallsyms.txt`, not inherited from the
S918B target.

## Status vs. Upstream Payloads (`HyperRamzey/Root-My-Galaxy-Payloads`)

Reviewed: `v1.1.1-f946b → v1.2.0` diff (797 lines). Applied:

- `.gitattributes` / `.gitignore` alignment (meta only).

**Not yet ported** (upstream-specific or no matching source context in this
fork — none of these affect the current APK behavior):

- `cve-2026-43499*` artifacts + `build_f946b.bat` + `targets/f946b*` — F946B
  specific, not portable to S918N.
- `src/su_daemon.c` vectord-revival — local `su_daemon.c` has no matching
  anchor; requires a source rebuild of the payload binaries.
- `src/kernelsnitch/kernelsnitch.h` majority-vote / collision confirmation —
  local sources diverge; requires a source rebuild.
- `src/preload.c` boot-quiet window via buddyinfo and `src/slide_app.c`
  bounded waits — same reason.

Because the shipped APK uses prebuilt payload binaries (`assets/` +
`jniLibs/`), source-level hunks only take effect after rebuilding the `.so`
payloads for the S918N/FZG1 profile. That rebuild is a separate full-build
task (Samsung kernel tree + NDK/clang) and is not part of the normal APK
build.

## Prerequisites

Before running the app, make sure the phone is ready:

1. **Enable Developer options and USB debugging**.
2. **Enable "Disable child process restrictions"** in Developer options
   (wording varies by One UI version). Shizuku needs this to spawn the helper
   processes the app relies on.
3. **Install [Shizuku](https://shizuku.rikka.app/).** It performs the
   privileged operations this app needs, without a full root shell.
4. **Reboot the phone.** A clean boot avoids stale permission/service state.
5. **Close every other app and background process.** Keep only Shizuku and
   Root My Galaxy running.
6. **Start the Shizuku service** (or enable `Auto-start Shizuku` in Settings).
7. **Open Root My Galaxy** and grant it permission when Shizuku prompts.

## Quick Start

Build the debug APK:

```sh
./gradlew :app:assembleDebug
```

Install and test on the device:

```sh
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Recommended test sequence:

1. Fully reboot the device (clean heap state).
2. Open the app, grant Shizuku permission.
3. Run the installation and let all 24 exploit attempts finish.
4. On success the app installs/opens the bundled KernelSU manager.
5. If it fails, export the full log from the History tab and share it.

## Important Files

```text
app/src/main/assets/targets-v3.json          payload manifest (S918N/FZG1)
app/src/main/assets/managers/                bundled manager APKs (offline)
app/src/main/assets/ksud-f731u-kdp           KernelSU regular ksud
app/src/main/assets/ksud-next                KernelSU Next ksud (kept)
app/src/main/jniLibs/arm64-v8a/              exploit helper libs
src/targets/                                 target headers
tools/                                       porting scripts (S918B base)
```

## Documentation

- [Documentation Index](docs/README.md): all detailed project docs.
- [Target Profile](docs/TARGET.md): exact device and firmware values expected by this port.
- [Project Structure](docs/PROJECT_STRUCTURE.md): what each directory contains.
- [Build, Install, And ADB](docs/BUILD_INSTALL_ADB.md): app build, install, staging, and manual test commands.
- [Troubleshooting](docs/TROUBLESHOOTING.md): common failures and how to diagnose them.

Upstream reference material is also kept in:

- [PORTING.md](PORTING.md)
- [PROJECT-MANIFEST.txt](PROJECT-MANIFEST.txt)
- [kernelsu/README.md](kernelsu/README.md)
- [KernelSU Next AFZG1](kernelsu-next/README.md)
- [support/README.md](support/README.md)

## Credits And Base Repository

This `SM-S918N` project is a **port** of the original developer's project:

- Original developer project:
  [soumarcelino/Root-My-Galaxy-SM-S918B](https://github.com/soumarcelino/Root-My-Galaxy-SM-S918B)
  (Apache-2.0) — "Root My Galaxy for Samsung Galaxy S23 Ultra SM-S918B"
  (latest release `v0.3.0`). All credit for the app flow, payload packaging,
  KernelSU late-load logic, support-manifest structure, and the porting
  procedure goes to the original developer.
- Payload/exploit sources:
  [HyperRamzey/Root-My-Galaxy-Payloads](https://github.com/HyperRamzey/Root-My-Galaxy-Payloads)
  (Apache-2.0), including the `v1.2.0` release reviewed in this project.
- The S918B port itself was based on
  [youyoudezhuzhu/rmg-f731u](https://github.com/youyoudezhuzhu/rmg-f731u)
  (Root-My-Galaxy F731U Z Flip5 payloads + APK repository).

This repository is an adaptation for `SM-S918N` / `dm3q` /
`S918NKSS8FZG1`, not the original S918B target. No proprietary Samsung code
is included; the two upstream projects above are both Apache-2.0.
