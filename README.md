# Sour

Build a **Dynamic System Update** package for the Redmi Note 10 Pro / Pro Max
(`sweet`) from a LineageOS OTA.

This repository is deliberately device-specific: one entry point (`build.py`)
with the implementation in `functions/`. It only knows sweet and only builds a
DSU guest for LineageOS.

```
LineageOS zip ──► build.py ──► artifacts/
                                 ├── rom2dsu-sweet-lineage-<date>-dsu.zip
                                 ├── stock.tar.lz4
                                 └── SHA256SUMS.txt
```

## Requirements

Linux, plus:

```sh
sudo apt install curl e2fsprogs lz4 python3-brotli
```

`debugfs`, `dumpe2fs`, `e2fsck`, `lz4` and `tar` are used directly. The raw
images need about 5 GiB of scratch space; the final zip is about 1.4 GiB.

## Build

```sh
./build.py                              # newest LineageOS build for sweet
./build.py --version 23.2               # pin a series
./build.py ~/Downloads/lineage-*.zip    # local file
./build.py https://download.lineageos.org/...   # explicit URL
```

Without a file, the LineageOS API is queried and the zip is downloaded to
`out/cache/`, then checked against the API's sha256.

Useful options:

| option | meaning |
| --- | --- |
| `--version X` | LineageOS series for the API, e.g. `23.2` (default: newest) |
| `--resolve-only` | print the resolved ROM and exit |
| `--cache-dir DIR` | download cache (default `out/cache`) |
| `--workdir DIR` | scratch directory for the raw images (default `out/work`) |
| `--artifacts DIR` | output directory (default `artifacts`) |
| `--keep-work` | keep the extracted raw images |
| `KEEP_WORK=1` | same as `--keep-work` |
| `BUILD_DATE=YYYYMMDD` | override the date in the zip name |

The ROM is unpacked from its `*.new.dat.br` + `*.transfer.list` files (sdat
v1-v4). The five guest partitions are `system`, `system_ext`, `product`,
`vendor` and `odm`.

## Output

`rom2dsu-sweet-lineage-<date>-dsu.zip` contains exactly the five patched
images:

```
system.img
system_ext.img
product.img
vendor.img
odm.img
```

Flash it with **DSU Sideloader** or `gsi_tool`. It does not contain
`boot.img`, `dtbo.img` or `vbmeta.img`; the guest boots on the host's kernel
and ramdisk.

`stock.tar.lz4` is a fixed-name archive of the same five images *before* any
patch, for restoring or comparing. `SHA256SUMS.txt` covers both files.

## What is patched

### `/metadata` is never mounted

The guest vendor fstab (`/vendor/etc/fstab.default` and `fstab.emmc`) loses
its `/metadata` entry. The partition belongs to the host; mounting it would let
the guest's `restorecon_recursive /metadata` relabel host state and would give
aconfigd the host's ownership instead of the guest's.

`/data` is switched to fstab-dsumode semantics:

```
latemount,wait,check,formattable,fileencryption=ice,quota,reservedsize=128M,checkpoint=fs
```

with `metadata_encryption=` and `keydirectory=` removed.

### Persist is read-only

`/mnt/vendor/persist` is mounted `ro` and is no longer `check`ed or
`formattable`. Every write to it is removed from the vendor init scripts:

- `restorecon` / `restorecon_recursive`
- `mkdir`, `chown`, `chmod` under `/mnt/vendor/persist`
- the charger-mode `mount` is forced to `ro`

The host's Find Device (`fdsd`), DRM and calibration data are never written or
relabelled.

### No LineageOS Updater

The Updater app and all of its system_ext leftovers are deleted:

- `/priv-app/Updater` (including `oat`)
- `/etc/permissions/Updater.xml`
- `/etc/default-permissions/default-permissions_org.lineageos.updater.xml`
- `/etc/init/init.lineage-updater.rc`

### Early-boot ADB

A fresh DSU `/data` has no adb key and stock adbd only starts after the vendor
USB setup. The system image is patched so a guest that dies at the splash
screen can still be inspected over USB:

- `ro.secure=0`, `ro.adb.secure=0`, `ro.debuggable=1`,
  `persist.sys.usb.config=adb`
- a `post-fs` adb-only gadget in `/system/etc/init/init.adb_early.rc`
- the USB controller defaults to `a600000.dwc3` (read from `vendor.usb.controller`
  when present)

This package is **insecure by design**: adbd accepts connections without
authorization and runs as root.

## Verification

Before writing the zip the builder checks, and fails if any of these is false:

- no `/metadata` entry in either fstab
- `/data` uses `fileencryption=ice` and no metadata encryption
- persist is `ro` and not `check`/`formattable`
- no persist writes remain in the vendor init scripts
- the Updater and its files are gone
- the early-ADB properties and rc file are present
- `e2fsck -fn` is clean on every image

## Notes

- The host must support DSU (Android 10+) and have a `/metadata` partition of
  at least 16 MiB. Bootloader verification normally has to be disabled for the
  host while testing an unsigned DSU package.
- First-stage mounts still come from the host's boot ramdisk. If the host
  ramdisk fstab mounts `/metadata`, that happens before the guest vendor fstab
  is read; check `adb shell mount | grep metadata` after booting the guest.
- The zip is not signed.
