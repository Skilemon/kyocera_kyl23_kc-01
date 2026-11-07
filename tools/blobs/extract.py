#!/usr/bin/env python3
"""Pull the proprietary half of the stock 4.4.4 system into a LineageOS tree.

The stock image keeps vendor libraries in two places: /vendor/lib, which is
already where 7.1 wants them, and /lib, which in 4.4 mixed AOSP and vendor
code side by side.  Only the vendor half of /lib may be carried over: for a
vendor process the linker searches /vendor/lib first, so a 4.4 libc or
libstagefright dropped in there would shadow the 7.1 one and take the system
down before it draws a frame.

What decides "vendor" is the name.  Everything Android 14.1 compiles itself is
listed in AOSP_LIBS below and stays behind; anything else under /lib is
carried.  That test is deliberately conservative -- carrying one library too
many costs a few hundred kilobytes, carrying one too few costs a boot loop.

Layout: files land under proprietary/ at the path they must end up at on the
device, so the generated copy rule is a straight prefix.  /lib/hw is the one
exception, it moves to /vendor/lib/hw because 7.1 only looks there.

Usage:
    extract.py --system <unpacked stock system> --repo <repo root>
"""
import argparse
import os
import shutil
import subprocess
import sys

# Libraries a LineageOS 14.1 build produces itself.  See module docstring.
AOSP_LIBS = set("""
libandroid libandroidfw libandroid_runtime libandroid_servers
libart libart-compiler libbcc libbcinfo
libaudioeffect_jni libaudioflinger libaudio-resampler libaudioroute libaudioutils
libbinder libbluetooth_jni
libcamera_client libcamera_metadata libcameraservice
libcommon_time_client libcompiler_rt libcrypto libc libctest libcurl libcutils
libdashplayer libdefcontainer_jni libdiskconfig libdl libdrmframework libdrmframework_jni
libeffects libEGL libETC1 libexif libexpat libext2_blkid libext2_com_err libext2_e2p
libext2fs libext2_profile libext2_uuid libext4_utils libexternal
libfacelock_jni libfilterframework_jni libfilterfw libfilterpack_facedetect
libfilterpack_imageproc libframesequence libft2
libgabi++ libgccdemangle libGLES_trace libGLESv1_CM libGLESv2 libGLESv3 libgui
libhardware libhardware_legacy libharfbuzz_ng libhwui libicui18n libicuuc libinput
libjavacore libjavacrypto libjnigraphics libjpeg libLLVM liblog liblogwrap
libm libmdnssd
libmedia libmedia_jni libmediaplayerservice libmemtrack libmtp
libnativehelper libnbaio libnetlink libnetutils libnfc_ndef libnl_2 libOpenMAXAL
libOpenSLES libpng libpowermanager libpower
libRScpp libRSCpuRef libRSDriver libRS librs_jni
libselinux libsensorservice libskia libsonivox libsoundpool libsparse
libspeexresampler libsqlite libsqlite_jni libssl
libstagefright libstagefright_omx libstagefright_foundation libstagefright_httplive
libstagefright_wfd libstagefright_avc_common libstagefright_enc_common libstagefright_yuv
libstagefright_amrnb_common libstagefright_soft_aacdec libstagefright_soft_aacenc
libstagefright_soft_amrdec libstagefright_soft_amrnbenc libstagefright_soft_amrwbenc
libstagefright_soft_flacenc libstagefright_soft_g711dec libstagefright_soft_gsmdec
libstagefright_soft_h264dec libstagefright_soft_h264enc libstagefright_soft_mp3dec
libstagefright_soft_mpeg4dec libstagefright_soft_mpeg4enc libstagefright_soft_rawdec
libstagefright_soft_vorbisdec libstagefright_soft_vpxdec libstagefright_soft_vpxenc
libstdc++ libstlport libsurfaceflinger libsurfaceflinger_ddmconnection
libsuspend libsync libsysutils libthread_db libtinyalsa libtinycompress libtinyxml
libtinyxml2 libui libusbhost libutils libvariablespeed
libwebp_android libwebviewchromium_plat_support libwebviewchromium libwilhelm
libwpa_client libxml2 libz
libebt_802_3 libebt_among libebt_arp libebt_arpreply libebt_ip libebt_ip6
libebt_limit libebt_log libebt_mark libebt_mark_m libebt_nat libebt_nflog
libebt_pkttype libebt_redirect libebt_standard libebt_stp libebt_ulog libebt_vlan
libebtable_broute libebtable_filter libebtable_nat libebtc libiprouteutil
libkeystore_binder libvorbisidec
""".split())

# Present in the 4.4 image but replaced wholesale in 7.1; carrying them over
# would only add dead weight (and, for libsoftkeymaster, a second keymaster).
DROP = {
    "libsoftkeymaster", "libril", "librilutils", "libreference-ril",
    "libbt-hci", "libbt-utils", "libsensors.default",
    "libsupol",                      # SuperSU leftover, nothing links to it
    "libdvm", "libcorkscrew", "libbcc.sha1",
}

# init.rc / init.qcom.rc / init.target.rc start these; they are the binaries
# without which the radio, the sensors, the charger and the thermal loop are
# dead.  Anything not listed stays behind -- the stock /bin also holds camera
# test tools and BSP diagnostics the ROM has no use for.
VENDOR_BIN = """
rild qmuxd netmgrd port-bridge bridgemgrd qmiproxy qcom-system-daemon
qseecomd qrngd qrngp irsc_util rmt_storage time_daemon
mpdecision thermal-engine
mm-qcamera-daemon
wcnss_service wcnss_filter
adsprpcd
gpsone_daemon
uimd ts_daemon
fusiond gravityd linearaccd rotatevecd
ftmdaemon
drmdiagapp
""".split()

# Configuration the 4.4 blobs read from /system/etc, plus the firmware blobs
# they load.  These stay in system/etc on purpose: the vendor libraries are
# 4.4 binaries with 4.4 path assumptions baked in, and /system/etc is the one
# location that means the same thing in both trees.
#
# "security" is deliberately absent.  It holds the 156 CA certificates, the
# otacerts bundle and mac_permissions.xml from 4.4, and all three are generated
# by the 7.1 tree from its own sources.  Copying the 4.4 versions over them
# reinstates a 2013-era trust store (including CAs that were later removed for
# issuing bad certificates) and replaces the 7.1 signature-permission map with
# one that predates it.  The build even says so, once per file:
#     warning: overriding commands for target '.../system/etc/security/cacerts/bf64f35b.0'
ETC_DIRS = [
    "acdbdata", "bluetooth", "firmware", "hostapd", "permissions",
    "ppp", "wifi", "dhcpcd", "nfc",
]
ETC_FILES = """
audio_effects.conf audio_policy.conf mixer_paths.xml
media_codecs.xml media_profiles.xml
thermal-engine-8226.conf
gps.conf izat.conf flp.conf quipc.conf sap.conf msap.conf xtwifi.conf
cacert_location.pem xtra_root_cert.pem
nfcee_access.xml nfc-nci.conf ethertypes clatd.conf
init.qcom.audio.sh init.qcom.bt.sh init.qcom.coex.sh init.qcom.efs.sync.sh
init.qcom.fm.sh init.qcom.post_boot.sh init.qcom.sdio.sh init.qcom.wifi.sh
init.ath3k.bt.sh init.crda.sh hsic.control.bt.sh qca6234-service.sh hcidump.sh
""".split()

# /vendor in the stock image is already vendor-only, minus the preinstalled
# apps that the ROM replaces with its own.
VENDOR_SKIP_DIRS = {"app", "media", "pittpatt"}


def is_elf(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"\x7fELF"
    except OSError:
        return False


def soname(path):
    out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "Library soname:" in line:
            return line.split("[", 1)[1].rstrip("]")
    return os.path.basename(path)


def needed(path):
    out = subprocess.run(["readelf", "-d", path], capture_output=True, text=True).stdout
    return [l.split("[", 1)[1].rstrip("]") for l in out.splitlines()
            if "Shared library:" in l]


def vendor_closure(sysroot):
    """Names of /lib libraries some vendor entry point actually reaches.

    /lib in 4.4 holds both halves of the system, and the vendor half is not
    only what the HALs link against -- it is also whatever the daemons and the
    apps dlopen.  Carrying everything that is not AOSP would drag in the JNI
    libraries of the preinstalled Kyocera apps (31 MB of Chromium among them)
    that the ROM does not ship and nothing loads.

    So the set is computed instead of guessed: start from every HAL, every
    library already in /vendor/lib, and every binary in /bin or /vendor/bin,
    then follow DT_NEEDED.  What the walk reaches and AOSP does not provide is
    what has to move.
    """
    idx = {}
    for base in ("lib", "vendor/lib", "vendor/lib/hw", "bin", "vendor/bin"):
        d = os.path.join(sysroot, base)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            if os.path.islink(p) or not os.path.isfile(p) or not is_elf(p):
                continue
            idx.setdefault(soname(p), p)

    roots = []
    for base in ("vendor/lib", "vendor/lib/hw", "lib/hw", "bin", "vendor/bin"):
        d = os.path.join(sysroot, base)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            if os.path.isfile(p) and not os.path.islink(p) and is_elf(p):
                roots.append(p)

    seen, queue = set(), list(roots)
    while queue:
        p = queue.pop()
        if p in seen:
            continue
        seen.add(p)
        for dep in needed(p):
            q = idx.get(dep)
            if q and q not in seen:
                queue.append(q)

    out = set()
    for p in seen:
        if os.path.dirname(p) == os.path.join(sysroot, "lib"):
            out.add(os.path.basename(p))
    return out


def copy(src, dst, mode=None):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    st = os.stat(src)
    os.chmod(dst, mode if mode is not None else (st.st_mode & 0o777))
    return os.path.getsize(dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", required=True, help="unpacked stock system root")
    ap.add_argument("--repo", required=True, help="repository root")
    ap.add_argument("--vendor", default="vendor/kyocera/msm8926-common")
    args = ap.parse_args()

    sysroot = os.path.abspath(args.system)
    outdir = os.path.join(args.repo, args.vendor, "proprietary")
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)

    copied = []          # (target path relative to device root, size)

    def add(src_rel, dst_rel):
        src = os.path.join(sysroot, src_rel)
        if not os.path.isfile(src):
            return
        n = copy(src, os.path.join(outdir, dst_rel))
        copied.append((dst_rel, n))

    # ---------------------------------------------------------------- /vendor
    vroot = os.path.join(sysroot, "vendor")
    for dirpath, dirnames, filenames in os.walk(vroot):
        rel = os.path.relpath(dirpath, vroot)
        if rel == ".":
            dirnames[:] = [d for d in dirnames if d not in VENDOR_SKIP_DIRS]
            rel = ""
        for fn in filenames:
            src_rel = os.path.join("vendor", rel, fn)
            dst_rel = os.path.join("vendor", rel, fn)
            add(src_rel, dst_rel)

    # ------------------------------------------------------------------- /lib
    # The set to move is not "everything that is not AOSP" -- see the long
    # comment in vendor_closure().  It is the DT_NEEDED closure of the vendor
    # entry points, plus the handful of plugins that are loaded by name and so
    # never show up as a NEEDED edge.
    DLOPEN_EXTRA = {
        "libstagefrighthw.so",   # mediaserver dlopens this as the OMX core
        "libacdbloader.so",      # audio HAL reads ACDB through it
    }
    libdir = os.path.join(sysroot, "lib")
    wanted = vendor_closure(sysroot) | DLOPEN_EXTRA
    carried = []
    skipped = []
    for fn in sorted(os.listdir(libdir)):
        p = os.path.join(libdir, fn)
        if not os.path.isfile(p) or os.path.islink(p) or not fn.endswith(".so"):
            continue
        base = soname(p)
        base = base[:-3] if base.endswith(".so") else base
        if base in AOSP_LIBS or base in DROP or fn not in wanted:
            skipped.append(fn)
            continue
        add(os.path.join("lib", fn), os.path.join("vendor", "lib", fn))
        carried.append(fn)

    # HALs live in /lib/hw in 4.4 and in /vendor/lib/hw in 7.1.
    hwdir = os.path.join(libdir, "hw")
    for fn in sorted(os.listdir(hwdir)):
        if fn.endswith(".so"):
            add(os.path.join("lib", "hw", fn), os.path.join("vendor", "lib", "hw", fn))

    # Kernel modules.  The kernel is the same 3.4 tree, so the vermagic still
    # matches; wlan.ko in particular has to come from here, there is no source
    # for it in the GPL drop.
    moddir = os.path.join(libdir, "modules")
    for dirpath, _, filenames in os.walk(moddir):
        rel = os.path.relpath(dirpath, moddir)
        for fn in filenames:
            src_rel = os.path.join("lib", "modules", rel, fn)
            dst_rel = os.path.join("vendor", "lib", "modules", rel, fn)
            add(src_rel, dst_rel)

    # ------------------------------------------------------------------- /bin
    for fn in VENDOR_BIN:
        add(os.path.join("bin", fn), os.path.join("vendor", "bin", fn))

    # ------------------------------------------------------------------- /etc
    for d in ETC_DIRS:
        src_dir = os.path.join(sysroot, "etc", d)
        if not os.path.isdir(src_dir):
            continue
        for dirpath, _, filenames in os.walk(src_dir):
            rel = os.path.relpath(dirpath, os.path.join(sysroot, "etc"))
            for fn in filenames:
                add(os.path.join("etc", rel, fn), os.path.join("system", "etc", rel, fn))
    for fn in ETC_FILES:
        add(os.path.join("etc", fn), os.path.join("system", "etc", fn))

    # ------------------------------------------------------------- write make
    copied.sort()
    mk = os.path.join(args.repo, args.vendor, "msm8926-common-vendor.mk")
    with open(mk, "w") as fh:
        fh.write("#\n# Generated by tools/blobs/extract.py -- do not edit by hand.\n#\n")
        fh.write("# Source: the stock 4.4.4 system image of this device.\n")
        fh.write("# %d files, %.1f MB\n#\n\n" % (
            len(copied), sum(n for _, n in copied) / 1048576))
        fh.write("PRODUCT_COPY_FILES += \\\n")
        last = len(copied) - 1
        for i, (rel, _) in enumerate(copied):
            dst = "$(TARGET_COPY_OUT_VENDOR)/" + rel[7:] if rel.startswith("vendor/") else rel
            # No trailing backslash on the final entry: a line continuation into
            # an empty line leaves PRODUCT_COPY_FILES holding a stray blank
            # element, which the build reports as a malformed copy rule.
            cont = "" if i == last else " \\"
            fh.write("    %s/proprietary/%s:%s%s\n" % (args.vendor, rel, dst, cont))
        fh.write("\n")

    # A flat manifest is easier to diff than the .mk and doubles as the input
    # for the tarball the CI downloads.
    man = os.path.join(args.repo, args.vendor, "proprietary-files.txt")
    with open(man, "w") as fh:
        fh.write("# Paths inside proprietary/.  Consumed by tools/blobs/pack.sh.\n")
        for rel, n in copied:
            fh.write("%s %d\n" % (rel, n))

    total = sum(n for _, n in copied)
    print("copied %d files, %.1f MB" % (len(copied), total / 1048576))
    print("carried out of /lib: %d, left behind: %d" % (len(carried), len(skipped)))
    print("wrote %s" % mk)
    print("wrote %s" % man)
    return 0


if __name__ == "__main__":
    sys.exit(main())
