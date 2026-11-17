#!/usr/bin/env python3
"""
apkresign.py -- rebuild an APK with a modified entry and sign it v1, without
touching how the other entries are stored.

Why this exists instead of `jarsigner`:

  jarsigner copies every entry into a fresh JarOutputStream, which compresses
  everything with DEFLATE.  That includes resources.arsc, and AssetManager
  needs that file stored uncompressed -- AAPT always stores it for exactly
  that reason.  A jar-verified APK with a deflated resources.arsc is a device
  that does not boot.

  So the signature is produced by hand, the way SignApk does it:
  MANIFEST.MF (SHA-256 per entry) + CERT.SF (digest of the manifest and of
  each manifest section) + CERT.RSA (PKCS#7 over CERT.SF).  Entries keep their
  original order and compression, uncompressed entries are padded to 4 bytes
  (what zipalign does), and META-INF is written last.

Two modes:

  apkresign.py sign   --ref ORIG.apk --in NEW.apk --out OUT.apk \
                      --pem platform.x509.pem --pk8 platform.pk8 [--alias CERT]

      Sign NEW.apk using ORIG.apk only as the reference for entry order and
      compression (typically the output of `apktool b`).

  apkresign.py patch  --ref ORIG.apk --out OUT.apk \
                      --pem ... --pk8 ... --set OFFSET:HEX

      Change bytes inside resources.arsc and re-sign, no rebuild at all.  For
      a single bool or integer this is the safe route: nothing is recompiled,
      no resource id moves, only the signature is redone.  OFFSET is relative
      to the start of resources.arsc, HEX is the replacement (e.g. 0x5fc44:01000000
      for bool false -> true).

The key matters.  framework-res.apk and org.cyanogenmod.platform-res.apk in a
CM 14.1 build are signed with the AOSP *platform* key
(C8:A2:E9:BC:CF:59:7C:2F...), shared with every app in android.uid.system.
Signing framework-res with any other key makes PackageManager drop either it
or every system app on the next boot -- see docs/DEVICE_NOTES.md section 40.2.
The platform key is public: platform_build/target/product/security/.
"""

import argparse
import base64
import hashlib
import io
import struct
import subprocess
import sys
import zipfile

CHUNK = 1 << 20


def digest_stream(f):
    h = hashlib.sha256()
    while True:
        b = f.read(CHUNK)
        if not b:
            break
        h.update(b)
    return base64.b64encode(h.digest()).decode()


def wrap(line):
    """72-byte lines, continuations prefixed with a space (JAR spec)."""
    out = []
    while True:
        out.append(line[:72])
        line = line[72:]
        if not line:
            break
        line = " " + line
    return "\r\n".join(out) + "\r\n"


def build_signature(entries, pem, pk8, tmp="/tmp"):
    """entries: list of (name, digest_b64) in manifest order."""
    manifest = "Manifest-Version: 1.0\r\nCreated-By: 1.0 (Android SignApk)\r\n\r\n"
    section = {}
    for name, d in entries:
        section[name] = "Name: %s\r\nSHA-256-Digest: %s\r\n\r\n" % (name, d)
        manifest += wrap("Name: %s" % name) + wrap("SHA-256-Digest: %s" % d) + "\r\n"

    sf = "Signature-Version: 1.0\r\nCreated-By: 1.0 (Android SignApk)\r\n"
    sf += "SHA-256-Digest-Manifest: %s\r\n\r\n" % base64.b64encode(
        hashlib.sha256(manifest.encode()).digest()).decode()
    for name, _ in entries:
        d = base64.b64encode(hashlib.sha256(section[name].encode()).digest()).decode()
        sf += wrap("Name: %s" % name) + wrap("SHA-256-Digest: %s" % d) + "\r\n"

    mf_path, sf_path, rsa_path = (tmp + "/_m.mf", tmp + "/_c.sf", tmp + "/_c.rsa")
    open(mf_path, "w").write(manifest)
    open(sf_path, "w").write(sf)
    subprocess.check_call([
        "openssl", "smime", "-sign", "-binary", "-noattr", "-md", "sha256",
        "-in", sf_path, "-signer", pem, "-inkey", pk8,
        "-outform", "DER", "-out", rsa_path])
    return manifest, sf, open(rsa_path, "rb").read()


def write_apk(out_path, order, read, ref_info, manifest, sf, rsa, alias):
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w")
    for name in order:
        zi = zipfile.ZipInfo(name, date_time=(2009, 1, 1, 0, 0, 0))
        zi.compress_type = ref_info[name].compress_type
        if zi.compress_type == zipfile.ZIP_STORED:
            # 4-byte align the data, the way zipalign does: pad with an
            # unknown extra field (id 0xd935, what zipalign itself uses).
            cur = buf.tell()
            pad = (4 - ((cur + 30 + len(name.encode())) % 4)) % 4
            if pad < 4:
                pad += 4
            zi.extra = struct.pack("<HH", 0xD935, pad - 4) + b"\0" * (pad - 4)
        z.writestr(zi, read(name))
    for name, data in (("META-INF/MANIFEST.MF", manifest),
                       ("META-INF/%s.SF" % alias, sf),
                       ("META-INF/%s.RSA" % alias, rsa)):
        z.writestr(zipfile.ZipInfo(name, (2009, 1, 1, 0, 0, 0)), data,
                   zipfile.ZIP_DEFLATED)
    z.close()
    open(out_path, "wb").write(buf.getvalue())
    return len(buf.getvalue())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["sign", "patch"])
    ap.add_argument("--ref", required=True, help="original apk (order, compression)")
    ap.add_argument("--in", dest="inp", help="rebuilt apk (mode=sign)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pem", required=True)
    ap.add_argument("--pk8", required=True)
    ap.add_argument("--alias", default="CERT")
    ap.add_argument("--set", action="append", default=[],
                    help="OFFSET:HEX, offset inside resources.arsc (mode=patch)")
    ap.add_argument("--arsc", help="use this resources.arsc verbatim (mode=patch); "
                                   "takes precedence over --set")
    a = ap.parse_args()

    ref = zipfile.ZipFile(a.ref)
    ref_info = {i.filename: i for i in ref.infolist()}

    if a.mode == "patch":
        if a.arsc:
            arsc = bytearray(open(a.arsc, "rb").read())
            print("  resources.arsc <- %s (%d bytes)" % (a.arsc, len(arsc)))
        else:
            arsc = bytearray(ref.read("resources.arsc"))
        for spec in a.set:
            off, hexval = spec.split(":")
            off = int(off, 0)
            val = bytes.fromhex(hexval)
            print("  %#x: %s -> %s" % (off, arsc[off:off + len(val)].hex(), hexval))
            arsc[off:off + len(val)] = val

        def read(name):
            return bytes(arsc) if name == "resources.arsc" else ref.read(name)
    else:
        src = zipfile.ZipFile(a.inp)
        src_names = set(src.namelist())

        def read(name):
            return src.read(name)

    names = [i.filename for i in ref.infolist()
             if not i.filename.startswith("META-INF/")]
    if a.mode == "sign":
        names = [n for n in names if n in src_names]
        names += [n for n in src.namelist()
                  if n not in ref_info and not n.startswith("META-INF/")]
    else:
        # patched apk keeps the original entry list exactly
        names = [n for n in ref.namelist() if not n.startswith("META-INF/")]

    entries = []
    for n in names:
        if a.mode == "patch":
            import io as _io
            entries.append((n, base64.b64encode(
                hashlib.sha256(read(n)).digest()).decode()))
        else:
            entries.append((n, digest_stream(src.open(n))))
    manifest, sf, rsa = build_signature(entries, a.pem, a.pk8)
    size = write_apk(a.out, names, read, ref_info, manifest, sf, rsa, a.alias)
    print("wrote %s (%d bytes, %d entries signed)" % (a.out, size, len(entries)))


if __name__ == "__main__":
    main()
