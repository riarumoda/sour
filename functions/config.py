"""Constants for sweet."""

from __future__ import annotations

DEVICE = "sweet"

BLOCK = 4096
PARTITIONS = ("system", "system_ext", "product", "vendor", "odm")

FSTAB_FILES = ("/etc/fstab.default", "/etc/fstab.emmc")
PERSIST_MOUNTS = ("/mnt/vendor/persist", "/persist")

UPDATER_DIR = "/priv-app/Updater"
UPDATER_FILES = (
    "/etc/permissions/Updater.xml",
    "/etc/default-permissions/default-permissions_org.lineageos.updater.xml",
    "/etc/init/init.lineage-updater.rc",
)

DSU_PREFIX = "rom2dsu-sweet-lineage"
STOCK_ARCHIVE = "stock.tar.lz4"
DEFAULT_UDC = "a600000.dwc3"

DEBUG_ADB_PROPS = (
    ("ro.secure", "0"),
    ("ro.adb.secure", "0"),
    ("ro.debuggable", "1"),
    ("persist.sys.usb.config", "adb"),
)
DEBUG_ADB_CONFIGFS_RC = (
    "/system/etc/init/hw/init.usb.configfs.rc",
    "/etc/init/hw/init.usb.configfs.rc",
)
DEBUG_ADB_RC_NAME = "init.adb_early.rc"
DEBUG_ADB_RC = """\
# Early, authorization-free adbd.

on post-fs-data
    setprop persist.sys.usb.config adb

on post-fs
    mkdir /config/usb_gadget/g1 0770
    mkdir /config/usb_gadget/g1/strings/0x409 0770
    write /config/usb_gadget/g1/bcdUSB 0x0200
    write /config/usb_gadget/g1/bcdDevice 0x0200
    write /config/usb_gadget/g1/idVendor 0x18d1
    write /config/usb_gadget/g1/idProduct 0x4ee7
    write /config/usb_gadget/g1/strings/0x409/serialnumber ${{ro.serialno}}
    write /config/usb_gadget/g1/strings/0x409/manufacturer ${{ro.product.manufacturer}}
    write /config/usb_gadget/g1/strings/0x409/product ${{ro.product.model}}
    mkdir /config/usb_gadget/g1/functions/ffs.adb
    mkdir /config/usb_gadget/g1/configs/b.1 0770
    mkdir /config/usb_gadget/g1/configs/b.1/strings/0x409 0770
    write /config/usb_gadget/g1/configs/b.1/MaxPower 500
    mkdir /dev/usb-ffs 0770 shell shell
    mkdir /dev/usb-ffs/adb 0770 shell shell
    mount functionfs adb /dev/usb-ffs/adb uid=2000,gid=1000,rmode=0770,fmode=0660
    setprop sys.usb.controller {udc}
    setprop sys.usb.configfs 1
    setprop sys.usb.config adb
    start adbd

on boot
    setprop persist.sys.usb.config adb
    start adbd
"""
