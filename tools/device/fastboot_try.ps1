#requires -Version 5.0
# Try to reach fastboot by writing the BCB command that aboot actually knows.
#
# aboot on this device only recognises these command names in misc:
#   boot-recovery, recovery, reboot-bootloader, update-radio
# Android 4.4 writes "bootonce-bootloader" for `adb reboot bootloader`,
# which aboot ignores, so normal boot wins every time.
#
# Usage:
#   .\fastboot_try.ps1            show current misc[0:64]
#   .\fastboot_try.ps1 -Go        write reboot-bootloader, reboot, wait for fastboot
#   .\fastboot_try.ps1 -Clear     zero the first 32 bytes of misc
#
# Pure ASCII on purpose: Windows PowerShell 5.1 mis-parses this file when it
# contains non-ASCII text.

param(
    [switch]$Go,
    [switch]$Clear,
    [int]$Wait = 30
)

$ErrorActionPreference = 'Continue'

$MISC  = '/dev/block/mmcblk0p26'
$TMP   = '/data/local/tmp/bcb.bin'
$MAGIC = 'reboot-bootloader'

function Get-AdbDevice {
    $out = & adb devices 2>$null
    foreach ($l in $out) {
        if ($l -match '^\S+\s+device$') { return $true }
    }
    return $false
}

function Invoke-Su([string]$Command) {
    # One single argument, so adb does not re-split the quotes away.
    & adb shell ("su -c '" + $Command + "'")
}

function Show-Misc {
    Write-Host ''
    Write-Host '---- misc[0:64] ----'
    Invoke-Su ("dd if=" + $MISC + " bs=1 count=64 2>/dev/null | od -A d -c")
    Write-Host ''
    Write-Host 'Look for one of: boot-recovery / recovery / reboot-bootloader / update-radio'
    Write-Host 'A leftover bootonce-bootloader would prove adb reboot bootloader never worked.'
}

if (-not (Get-AdbDevice)) {
    Write-Host 'No adb device. Connect the phone and enable USB debugging first.'
    exit 1
}

if ($Clear) {
    Write-Host 'Zeroing misc[0:32] ...'
    Invoke-Su ("dd if=/dev/zero of=" + $MISC + " bs=1 count=32 2>/dev/null")
    Invoke-Su 'sync'
    Show-Misc
    exit 0
}

if (-not $Go) {
    Show-Misc
    exit 0
}

# ---- 1. back up the current header, so a mistake is recoverable ----------
Write-Host ''
Write-Host 'Backing up misc header to /data/local/tmp/misc_head.bin ...'
Invoke-Su ("dd if=" + $MISC + " of=/data/local/tmp/misc_head.bin bs=4096 count=1 2>/dev/null")
Invoke-Su 'ls -l /data/local/tmp/misc_head.bin'

# ---- 2. build exactly 32 bytes: the string plus NUL padding --------------
# Do this on the Windows side.  Android 4.4 has no usable printf, and the
# mksh echo builtin mangles backslashes, so pushing a binary is the safe route.
$bytes = New-Object byte[] 32
$str   = [Text.Encoding]::ASCII.GetBytes($MAGIC)
[Array]::Copy($str, $bytes, $str.Length)
$local = Join-Path $env:TEMP 'bcb.bin'
[IO.File]::WriteAllBytes($local, $bytes)
Write-Host ('Built ' + $bytes.Length + ' bytes for command "' + $MAGIC + '"')

Write-Host 'Pushing ...'
& adb push $local $TMP

# ---- 3. write it into misc, no truncate needed for a block device --------
Write-Host 'Writing misc[0:32] ...'
Invoke-Su ("dd if=" + $TMP + " of=" + $MISC + " bs=1 count=32 2>/dev/null")
Invoke-Su 'sync'
Show-Misc

# ---- 4. reboot and watch for a fastboot interface ------------------------
$haveFb = $null -ne (Get-Command fastboot -ErrorAction SilentlyContinue)
if (-not $haveFb) {
    Write-Host ''
    Write-Host 'WARNING: fastboot.exe is not on PATH. Reboot manually and run it yourself.'
}

Write-Host ''
Write-Host 'Rebooting. Watching for a fastboot device ...'
& adb reboot

$start = Get-Date
$seen  = $false
while (((Get-Date) - $start).TotalSeconds -lt $Wait) {
    Start-Sleep -Milliseconds 900
    $el  = [Math]::Round(((Get-Date) - $start).TotalSeconds, 1)
    $dev = & adb devices 2>$null | Select-String 'device$'
    $fb  = $null
    if ($haveFb) { $fb = & fastboot devices 2>$null | Where-Object { $_ -match '\S' } }
    $left = 'sec ' + $el.ToString('0.0')
    if ($fb) {
        Write-Host ($left + '  FASTBOOT: ' + ($fb -join ' '))
        $seen = $true
        break
    }
    if ($dev) { Write-Host ($left + '  adb device back (normal boot)') }
}

Write-Host ''
if ($seen) {
    Write-Host '=============================='
    Write-Host ' fastboot IS reachable.'
    Write-Host '=============================='
    Write-Host 'Next:'
    Write-Host '  fastboot oem device-info'
    Write-Host '  fastboot getvar all'
    Write-Host ''
    Write-Host 'IMPORTANT - clear misc before leaving, or the phone may boot'
    Write-Host 'straight back into fastboot every time:'
    Write-Host '  fastboot erase misc'
    Write-Host '  fastboot reboot'
    Write-Host 'If that erase is refused, reboot to Android and run:'
    Write-Host '  .\fastboot_try.ps1 -Clear'
} else {
    Write-Host ('No fastboot device within ' + $Wait + ' seconds.')
    Write-Host 'If the phone came back to Android, the command was accepted but'
    Write-Host 'aboot did not enter fastboot. Then run -Clear to tidy up.'
}
