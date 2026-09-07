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

## Download & Install (from GitHub Releases)

The simplest way to get the app is to download the latest release and
sideload it onto the device. No store, no Play account, no shell.

**Latest stable release:** [v0.3.5](https://github.com/Ibhamada0/Root-My-Galaxy-S918N/releases/tag/v0.3.5)
([all releases](https://github.com/Ibhamada0/Root-My-Galaxy-S918N/releases))

| Asset              | Size                       | Use it for                                                                                                     |
| ------------------ | -------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `app-release.apk`  | ~71.3 MB (74,722,550 B)    | **Normal users.** Signed by the same release key used since v0.3.4, so it can be installed over an existing build. |
| `app-debug.apk`    | ~88.0 MB (92,286,988 B)    | Developers only. Signed with the default debug key inside the CI runner, so its certificate can change between CI runs. |

Direct download links for v0.3.5:

- https://github.com/Ibhamada0/Root-My-Galaxy-S918N/releases/download/v0.3.5/app-release.apk
- https://github.com/Ibhamada0/Root-My-Galaxy-S918N/releases/download/v0.3.5/app-debug.apk

### Signing identity (verifies the file really came from this repo)

All `app-release.apk` builds since v0.3.4 are signed with the same release
key committed in `app/signing/release.jks`. The certificate's SHA-256
fingerprint is:

```
ee190f56b3c6c4550befa5a457b9a4a6adc6486bb2eaea900a2bcf65c58c8bc5
```

You can verify it yourself after downloading:

```sh
# macOS / Linux, requires Android build-tools (apksigner)
apksigner verify --print-certs app-release.apk \
  | grep "Signer #1 certificate SHA-256 digest"
# expected output:
# ee190f56b3c6c4550befa5a457b9a4a6adc6486bb2eaea900a2bcf65c58c8bc5
```

If the digest does **not** match, do not install the file — you have a
different (possibly tampered) build.

### Step 1 — allow this app to install other apps

The first time you run the app it must be granted the
"Install unknown apps" permission, because both Shizuku and the bundled
KernelSU Manager are installed through the system package installer, not
via a silent shell command.

1. On the device: **Settings → Apps → Special access → Install unknown apps**.
2. Pick **Root My Galaxy** and toggle **Allow**.
3. Repeat for **Shizuku** if you plan to use it.

On Android 14+ the path is:
**Settings → Apps → Root My Galaxy → Install unknown apps**.

### Step 2 — pick one installation method

All three methods write the same `app-release.apk`, so the certificate
check above applies whichever path you choose.

**A. Sideload from the device browser (no PC needed).**

1. Open `https://github.com/Ibhamada0/Root-My-Galaxy-S918N/releases/latest`
   in the phone's browser.
2. Tap `app-release.apk` and confirm the download.
3. Tap the downloaded file from the notification shade (or open
   `Files → Downloads`) and let the system's package installer handle it.

**B. From a PC over ADB (recommended for developers).**

```sh
adb install -r app-release.apk
# expected last line: Success
```

`-r` reinstalls over the previous build, which works as long as the
signing certificate is the same — and it is, for every `app-release.apk`
from v0.3.4 onward.

**C. From the app's built-in updater.**

Once a previous build is installed, **Settings → "Check for update"**
pulls the latest release from
`https://api.github.com/repos/Ibhamada0/Root-My-Galaxy-S918N/releases/latest`
and hands the APK to the system installer. This is the only path that
uses no `pm install` shell command and no browser fallback.

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

## Updating from a Previous Version

If you already have a previous `v0.3.x` build installed, you can update to
the latest release **without uninstalling first**. The release key has
been fixed since `v0.3.4`, so the certificate matches and Android treats
the new APK as a normal upgrade.

Three update paths, all valid:

1. **In-app updater (preferred).** Settings → "Check for update". The
   app downloads `app-release.apk` from `/repos/Ibhamada0/Root-My-Galaxy-S918N/releases/latest`
   and hands it to the system installer.
2. **ADB update.** `adb install -r app-release.apk`. No
   `INSTALL_FAILED_UPDATE_INCOMPATIBLE` as long as the certificate
   matches (verified by the SHA-256 fingerprint in the section above).
3. **Sideload.** Download `app-release.apk` over the device browser and
   tap the file; the system installer detects that it is an upgrade.

> **Heads-up for `v0.3.1`, `v0.3.2`, `v0.3.3`.** Those three builds were
> signed with a throwaway keystore generated inside the CI runner for
> each build, so their certificate differs from `v0.3.4`'s and from
> every build after it. If you carry one of them on your phone,
> `adb install -r` will fail with `INSTALL_FAILED_UPDATE_INCOMPATIBLE`.
> The fix is a one-time cleanup: uninstall the old build, then install
> `v0.3.5` (or any later `app-release.apk`) fresh. Every subsequent
> update will land cleanly over the previous one.

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
