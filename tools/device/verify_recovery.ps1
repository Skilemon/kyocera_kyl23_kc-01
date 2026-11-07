# =============================================================
#  verify_recovery.ps1  —  KC-01 / KYL23  recovery 分区刷写校验
#
#  原理：直接从 eMMC 把 recovery 分区读回来，和本地镜像逐字节比对。
#        不依赖 recovery 界面长什么样（裁剪版和原厂界面完全一样，
#        肉眼永远分不出来，只能读分区）。
#
#  用法（设备正常开机、adb 在线、已有 root）：
#      powershell -ExecutionPolicy Bypass -File .\verify_recovery.ps1
#      powershell -ExecutionPolicy Bypass -File .\verify_recovery.ps1 -Full
#
#  -Full  额外把整个 16MB 分区读一遍（慢，约 1-2 分钟），
#         确认分区尾部也没被动过。
# =============================================================
param([switch]$Full)

# ---- 常量：与本地 test_trimmed.img 对应，勿改 ----
$PART        = "/dev/block/platform/msm_sdcc.1/by-name/recovery"
$LOCAL_LEN   = 7360512
$LOCAL_MD5   = "f4f23ccb29c983c557e58a47d8cee750"   # test_trimmed.img 前 7.36MB
$STOCK_MD5   = "512a258d5abc56cd618e9d62f0ff4d95"   # 原厂 recovery 前 7.36MB
$FULL_MD5    = "37891b50deedaf945866e514e9f11840"   # 期望整 16MB
$DT_OFF      = 7036928
$DT_SKIP     = 439808                               # $DT_OFF / 16
$EXPECT_CNT  = 8                                    # 裁剪后 QCDT 条目数
$EXPECT_ESZ  = 24
$STOCK_CNT   = 184                                  # 原厂 QCDT 条目数
$STOCK_ESZ   = 145                                  # 原厂该字段是怪值 0x91

function Sh([string]$c) {
    $r = adb shell "su -c '$c'" 2>&1
    return (($r | Out-String).Trim())
}

function Md5Of([string]$c) {
    foreach ($tool in @("md5", "md5sum", "busybox md5sum")) {
        $h = Sh "$c | $tool"
        if ($h -match '[0-9a-fA-F]{32}') { return $Matches[0].ToLower() }
    }
    return ""
}

function Line { Write-Host ("-" * 64) }

Line
Write-Host " 0. 设备与权限"
Line
$id = Sh "id"
Write-Host "  id       : $id"
if ($id -notmatch "uid=0") {
    Write-Host ""
    Write-Host "  [X] 不是 root 或 adb 不通。"
    Write-Host "      如果你现在停在 recovery 界面，原厂 recovery 默认关 adb，"
    Write-Host "      先长按电源重启进系统，再跑这个脚本。"
    exit 1
}
$sz = Sh "blockdev --getsize64 $PART 2>/dev/null || echo UNKNOWN"
Write-Host "  分区大小 : $sz"
if ($sz -match '^\d+$' -and [int64]$sz -ne 16777216) {
    Write-Host "  [!] 不是 16,777,216 字节，确认一下分区表"
}

Line
Write-Host " 1. 读回 dt 段头部 —— 不用传文件，只看 16 个字节"
Line
$hex = Sh "dd if=$PART bs=16 skip=$DT_SKIP count=1 2>/dev/null | od -An -tx1"
Write-Host "  原始     : $hex"
$b = @()
foreach ($t in ($hex -split '\s+')) {
    if ($t -match '^[0-9a-fA-F]{2}$') { $b += [Convert]::ToByte($t, 16) }
}
if ($b.Count -lt 16) {
    Write-Host "  [X] 读不到 dt 段，dd 失败"
} else {
    $magic = -join ($b[0..3] | ForEach-Object { [char]$_ })
    $cnt = [int]$b[8] + ([int]$b[9] -shl 8) + ([int]$b[10] -shl 16) + ([int]$b[11] -shl 24)
    $esz = [int]$b[12] + ([int]$b[13] -shl 8) + ([int]$b[14] -shl 16) + ([int]$b[15] -shl 24)
    Write-Host "  magic=$magic  条目数=$cnt  条目长度=$esz"
    Write-Host ""
    if ($magic -ne "QCDT") {
        Write-Host "  [X] dt 段不是 QCDT —— 位置算错，或分区里是别的镜像"
    } elseif ($cnt -eq $EXPECT_CNT -and $esz -eq $EXPECT_ESZ) {
        Write-Host "  [OK] 条目数=$cnt 条目长度=$esz  →  就是裁剪版 test_trimmed.img"
    } elseif ($cnt -eq $STOCK_CNT) {
        Write-Host "  [X] 条目数=$cnt  →  这是原厂 recovery，被还原了或压根没写进去"
    } else {
        Write-Host "  [?] 条目数=$cnt  →  既不是裁剪版也不是原厂，分区被别的镜像占了"
    }
}

Line
Write-Host " 2. 读回前 $LOCAL_LEN 字节算 md5 —— 逐字节比对"
Line
Write-Host "  读取中（约 20-40 秒）..."
$m = Md5Of "dd if=$PART bs=2048 count=3594 2>/dev/null"
Write-Host "  设备读回 : $m"
Write-Host "  裁剪版   : $LOCAL_MD5"
Write-Host "  原厂     : $STOCK_MD5"
Write-Host ""
if ($m -eq $LOCAL_MD5) {
    Write-Host "  [OK] 完全一致，一个字节都没差"
} elseif ($m -eq $STOCK_MD5) {
    Write-Host "  [X] 等于原厂 —— 没刷进去，或刷完被还原"
} elseif ($m -eq "") {
    Write-Host "  [X] 设备上没有 md5/md5sum，算不了"
} else {
    Write-Host "  [?] 不匹配任何已知镜像"
}

Line
Write-Host " 3. 还原机制检查 —— 回答「会不会被自动写回原厂」"
Line
$rf = Sh "if [ -f /system/recovery-from-boot.p ]; then echo YES; else echo NO; fi"
$ir = Sh "if [ -f /system/etc/install-recovery.sh ]; then echo YES; else echo NO; fi"
Write-Host "  /system/recovery-from-boot.p     : $rf"
Write-Host "  /system/etc/install-recovery.sh  : $ir"
if ($rf -match "YES" -or $ir -match "YES") {
    Write-Host "  [!] 存在还原机制，每次开机可能把 recovery 写回原厂。"
    Write-Host "      这个机制只在你重启回系统时才触发，能进 recovery 说明当时还没被写回。"
} else {
    Write-Host "  [OK] 没有还原机制，刷进去不会被系统改写"
}

if ($Full) {
    Line
    Write-Host " 4. 整分区 16MB 校验"
    Line
    Write-Host "  读取中（约 1-2 分钟）..."
    $mf = Md5Of "dd if=$PART bs=2048 count=8192 2>/dev/null"
    Write-Host "  设备读回 : $mf"
    Write-Host "  期望     : $FULL_MD5"
    if ($mf -eq $FULL_MD5) {
        Write-Host "  [OK] 整分区一致：前 7.36MB 是新镜像，后 9.42MB 保持原厂残留"
    } else {
        Write-Host "  [?] 整分区不一致（尾部可能是更早的残留，不一定是问题）"
    }
}

Line
Write-Host " 判读：第 1 节能对上就是刷进去了；第 1、2 节同时对上，"
Write-Host "       说明分区内容与本地文件逐字节相同，不存在「写了一半」或「被还原」。"
Line
