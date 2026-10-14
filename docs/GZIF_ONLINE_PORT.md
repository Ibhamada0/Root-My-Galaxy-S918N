# S918N GZIF online port

This branch prepares an **experimental online port**, not a supported release.
Current target: SM-S918N, CP2A.260605.016.S918NKSU8GZIF, Android 17,
kernel 5.15.197-android13-8-34343818-abS918NKSU8GZIF.

## Inputs

1. Upload the original stock boot.img.lz4 as a **public GitHub release asset**.
   Copy its direct releases/download URL, not the release page URL.
2. Put the URL in ci/gzif-input.json on this branch.
3. For a full build, also supply the exact output of:
   adb shell getprop ro.build.fingerprint

A commit to the input file automatically starts the workflow on this branch.
Manual workflow_dispatch is also available after the workflow exists on the
default branch. Do not merge just to dispatch: the branch push trigger is enough.

The workflow validates the compressed SHA-256:
c7f37c99b54a8a164b082a88af5a833f7f48bcd4ca98db9dbd8b4192e984253b
and decompressed SHA-256:
1552a1dbf45a95ef25626097605c2f1d3e64c1b557353887b905be1ea166635e

With no boot URL, only safeguard tests run. With a URL but no fingerprint,
the kernel contract and KernelSU ABI are checked without compiling or executing
a payload; the script does not guess the fingerprint.
With both inputs, it derives and independently verifies the GZIF firmware
contract, builds BOPE and its helpers, and audits KernelSU symbols, CRCs and
layouts before rebuilding ksud and packaging an APK.

## Output and limits

Actions artifacts contain logs, evidence and, only after all static gates pass,
a generated target archive and experimental debug APK. Failure logs are retained.
No release or version tag is published, and no device commands are executed.

The experimental APK uses the reviewed upstream app client because it supports
the helper, launcher and mmFactory components required by BOPE. Its application ID
is io.github.ibhamada0.rootmygalaxy.gzif.experimental, separate from the existing
S918N release. It is not yet a migration of this fork's UI/settings or a signed
upgrade to the existing app. Existing FZG1 support remains untouched.

Successful compilation and static checks do not validate allocator/timing
calibration or real-device behavior. Clean-boot testing on the owner's device
is still required before claiming GZIF support or publishing a stable release.

## Provenance

BOPE, its tools and the donor app are credited to:
https://github.com/soumarcelino/Root-My-Galaxy-SM-S918B
Pinned donor commit: 362416498212658e17f72f05e64259b85998d75b
Donor target: targets/zzi8-WIP (S918BXXUAZZI8).

KernelSU Next v3.4.0:
https://github.com/KernelSU-Next/KernelSU-Next
Pinned commit: 1a879d6a866f80b1fa1c1009a2ffa747873cbb5e.
The donor's Samsung patch is applied to that source before rebuilding userspace.

Kernel extraction:
https://github.com/marin-m/vmlinux-to-elf
Pinned commit: 19683fb95b29cd31362d49e6f48ab8368f96cbdf.

Upstream licenses and attribution are retained. Raw boot data is downloaded
into the ephemeral runner and is excluded from the generated target archive.
