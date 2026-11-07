<#
.SYNOPSIS
    USB / PET observer for the KYL23 keycombo recovery test.

.DESCRIPTION
    watch : record when USB devices appear and disappear, with elapsed seconds.
    dump  : pull the PET reset table (p22) and print it, plus cmdline and last_kmsg.
    See docs/KEYCOMBO_TEST.md for how to read the result.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\keytest.ps1 -Mode watch

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\keytest.ps1 -Mode dump
#>
param(
    [ValidateSet('watch', 'dump')]
    [string]$Mode = 'watch',

    # target poll interval; Get-PnpDevice itself takes 1-2 s per round
    [int]$IntervalMs = 500,

    [string]$Out = 'usbtrace.csv'
)

$ErrorActionPreference = 'Continue'

function Stamp([double]$s) {
    return ([Math]::Round($s, 2)).ToString('0.00').PadLeft(7)
}

# ---------------------------------------------------------------- watch

function Invoke-Watch {
    $known = @{}
    $t0 = Get-Date
    $sw = New-Object IO.StreamWriter -ArgumentList $Out, $true
    $sw.AutoFlush = $true

    Write-Host ''
    Write-Host '  USB trace running, log -> ' $Out
    Write-Host '  Ctrl+C to stop. Press the key combo now.'
    Write-Host ''
    Write-Host '  18D1 = recovery  (D001 adb-only, 4EE2 mtp+adb)'
    Write-Host '  0482 = Android system (Kyocera)'
    Write-Host '  05C6 = fastboot / EDL'
    Write-Host ''

    try {
        while ($true) {
            $cur = @{}
            $devs = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
                    Where-Object { $_.InstanceId -like 'USB\VID_*' }

            foreach ($d in $devs) {
                $id = $d.InstanceId
                $cur[$id] = $true
                if (-not $known.ContainsKey($id)) {
                    $known[$id] = $true
                    $ts = Stamp (((Get-Date) - $t0).TotalSeconds)
                    Write-Host ($ts + '  ADD  ' + $id.PadRight(50) + '  ' + $d.FriendlyName)
                    $sw.WriteLine($ts.Trim() + ',ADD,' + $id + ',' + $d.FriendlyName)
                }
            }

            foreach ($id in @($known.Keys)) {
                if (-not $cur.ContainsKey($id)) {
                    $known.Remove($id)
                    $ts = Stamp (((Get-Date) - $t0).TotalSeconds)
                    Write-Host ($ts + '  DEL  ' + $id)
                    $sw.WriteLine($ts.Trim() + ',DEL,' + $id + ',')
                }
            }

            Start-Sleep -Milliseconds $IntervalMs
        }
    }
    finally {
        $sw.Close()
        Write-Host ''
        Write-Host '  saved: ' $Out
    }
}

# ---------------------------------------------------------------- dump

function Get-ShellText([string]$cmd) {
    $r = & adb shell $cmd 2>&1
    return (($r | Out-String).Trim())
}

function Invoke-Dump {
    & adb get-state 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  adb is not online. Boot the device normally and connect it first.'
        return
    }

    Write-Host ''
    Write-Host '==== device ===='
    Write-Host ('  ' + (Get-ShellText 'getprop ro.product.device') + ' / ' +
                (Get-ShellText 'getprop ro.serialno') + ' / ' +
                (Get-ShellText 'getprop ro.build.id'))

    Write-Host ''
    Write-Host '==== /proc/cmdline ===='
    Write-Host (Get-ShellText 'cat /proc/cmdline')

    Write-Host ''
    Write-Host '==== PET table (one record per reset) ===='
    Write-Host '  layout: KERNEL / reason / time / build / platform'

    # first 8 KB is enough, the PET table sits at offset 0
    & adb shell "su -c 'dd if=/dev/block/mmcblk0p22 of=/data/local/tmp/pet.bin bs=4096 count=2'" 2>&1 | Out-Null
    $tmp = Join-Path ([IO.Path]::GetTempPath()) 'pet.bin'
    & adb pull /data/local/tmp/pet.bin $tmp 2>&1 | Out-Null
    & adb shell "su -c 'rm -f /data/local/tmp/pet.bin'" 2>&1 | Out-Null

    if (Test-Path $tmp) {
        $bytes = [IO.File]::ReadAllBytes($tmp)
        $sb = New-Object Text.StringBuilder
        foreach ($b in $bytes) {
            if ($b -ge 32 -and $b -lt 127) { [void]$sb.Append([char]$b) }
            else { [void]$sb.Append([char]10) }
        }
        $lines = $sb.ToString() -split [char]10 |
                 ForEach-Object { $_.Trim() } |
                 Where-Object { $_.Length -gt 2 }

        # PET record is 5 lines: KERNEL / reason / time / build / platform
        $start = 0
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -eq 'KERNEL') { $start = $i; break }
        }

        $i = $start
        $group = 0
        while ($i -lt $lines.Count -and $lines[$i] -eq 'KERNEL' -and $group -lt 8) {
            for ($j = 0; $j -lt 5 -and ($i + $j) -lt $lines.Count; $j++) {
                Write-Host ('  ' + $lines[$i + $j])
            }
            Write-Host ''
            $i += 5
            $group++
        }
        Remove-Item $tmp -Force
    }
    else {
        Write-Host '  pull failed - su probably not granted.'
    }

    Write-Host ''
    Write-Host '==== tail of /proc/last_kmsg ===='
    $k = Get-ShellText "su -c 'tail -25 /proc/last_kmsg'"
    if ($k -match 'No such file') { Write-Host '  (not present, kernel was built without it)' }
    else { Write-Host $k }

    Write-Host ''
    Write-Host '  Read the result with section 5 of docs/KEYCOMBO_TEST.md.'
}

# ---------------------------------------------------------------- main

if ($Mode -eq 'watch') { Invoke-Watch } else { Invoke-Dump }
