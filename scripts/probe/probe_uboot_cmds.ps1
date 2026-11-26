param(
  [string]$Port = 'COM14',
  [int]$WaitForPort = 240,
  [int]$ProbeWaitMs = 1200,
  [string]$LogDir = 'out\probe'
)
# probe_uboot_cmds.ps1 — 批量探测精简版 U-Boot 的可用命令
#
# 原理：该 U-Boot 的输出路径被大面积裁剪（help 裸敲、md、printenv <name> 等都没有回显），
#       但 hush 的 echo 通道可用。因此用
#           if <cmd>; then echo PB_OK_<n>; else echo PB_NO_<n>; fi
#       让 U-Boot 自己回一个标记，绕开“无回显”的干扰。
#
# 用法：
#   pwsh -NoProfile -File scripts\probe\probe_uboot_cmds.ps1 -Port COM14
#
# 注意：
#   - 只探测“无副作用、不阻塞”的命令。reset/reboot/fastboot/update/loadb/loady/
#     store erase|write|scrub/efuse write 等危险命令不在自动列表里，见 docs/02。
#   - 串口必须独占，运行前关闭其它串口工具。
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$tag = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $LogDir "probe-$tag.log"

# 安全探测集合（裸命令应当只打印 usage 或立即返回）
$probes = @(
  'printenv', 'echo', 'test', 'sleep', 'md', 'md.b', 'md.w',
  'cp.b', 'cmp.b', 'crc32', 'base',
  'store', 'imgread', 'mmcinfo', 'usb', 'fatload',
  'vout', 'hdmitx', 'osd', 'bmp', 'jpeg', 'cvbs',
  'i2c', 'gpio', 'efuse', 'keyman', 'irkey', 'getCom',
  'bootm', 'go', 'get_rebootmode', 'fdt', 'autoscr'
)

# 已知存在但会阻塞/改状态，不自动执行
$known = @(
  @{ Cmd = 'setenv';  Note = '改环境变量' },
  @{ Cmd = 'saveenv'; Note = '写 env 分区' },
  @{ Cmd = 'run';     Note = '执行变量脚本' },
  @{ Cmd = 'mw / mw.b'; Note = '写内存' },
  @{ Cmd = 'reset';   Note = '立即重启' },
  @{ Cmd = 'reboot';  Note = '按模式重启' },
  @{ Cmd = 'fastboot'; Note = '进入 USB 等待，阻塞' },
  @{ Cmd = 'update';  Note = 'USB 烧录等待，阻塞' },
  @{ Cmd = 'sdc_burn'; Note = 'SD 烧录' },
  @{ Cmd = 'loadb / loady'; Note = '串口下载，阻塞' },
  @{ Cmd = 'wipeisb'; Note = '语义未知，慎用' },
  @{ Cmd = 'tftpboot'; Note = '网络下载，需要 serverip' }
)

# 等待串口空闲
$deadline = (Get-Date).AddSeconds($WaitForPort)
$free = $false
while ((Get-Date) -lt $deadline) {
  $probe = [System.IO.Ports.SerialPort]::new($Port, 115200)
  try { $probe.Open(); $probe.Close(); $free = $true } catch { }
  $probe.Dispose()
  if ($free) { break }
  Start-Sleep -Milliseconds 900
}
if (-not $free) { "TIMEOUT: $Port busy"; exit 2 }

$sp = [System.IO.Ports.SerialPort]::new($Port, 115200, 'None', 8, 'One')
$sp.ReadTimeout = 250
$sp.DtrEnable = $true
$sp.RtsEnable = $true
$sp.Open()
Start-Sleep -Milliseconds 300
$sp.DiscardInBuffer()

function Write-Slow {
  param([string]$text, [int]$chunk = 20, [int]$ms = 25)
  $b = [Text.Encoding]::ASCII.GetBytes($text)
  for ($i = 0; $i -lt $b.Length; $i += $chunk) {
    $n = [Math]::Min($chunk, $b.Length - $i)
    $sp.Write([Text.Encoding]::ASCII.GetString($b, $i, $n))
    Start-Sleep -Milliseconds $ms
  }
  $sp.Write("`r")
}

function Read-Until {
  param([string]$marker, [int]$timeoutMs)
  $acc = [System.Text.StringBuilder]::new()
  $end = (Get-Date).AddMilliseconds($timeoutMs)
  while ((Get-Date) -lt $end) {
    try {
      $d = $sp.ReadExisting()
      if ($d.Length) {
        [void]$acc.Append($d)
        if ($acc.ToString() -match [regex]::Escape($marker)) { break }
      }
    } catch { }
    Start-Sleep -Milliseconds 80
  }
  return $acc.ToString()
}

$lines = [System.Collections.Generic.List[string]]::new()
function Log { param([string]$s) $lines.Add($s); Write-Host $s }

Log "=== probe start $tag port=$Port ==="
$sp.Write("`r")
Start-Sleep -Milliseconds 600
Log ("ready: " + (($sp.ReadExisting() -replace "`r", ' ').Trim()))

$idx = 0
$ok = 0; $no = 0; $unknown = 0
foreach ($cmd in $probes) {
  $idx++
  $mOk = "PB_OK_$idx"
  $mNo = "PB_NO_$idx"
  $expr = "if $cmd; then echo $mOk; else echo $mNo; fi"
  Write-Slow $expr
  $out = Read-Until -marker $mOk -timeoutMs $ProbeWaitMs
  $text = $out.ToString()
  if ($text -match [regex]::Escape($mOk)) {
    Log ("[OK]   {0,-14} {1}" -f $cmd, $mOk)
    $ok++
  } elseif ($text -match [regex]::Escape($mNo)) {
    Log ("[NO]   {0,-14} {1}" -f $cmd, $mNo)
    $no++
  } else {
    Log ("[?]    {0,-14} (no marker; output may be trimmed)" -f $cmd)
    $unknown++
  }
  Start-Sleep -Milliseconds 150
}

Log ""
Log "=== summary: OK=$ok NO=$no UNKNOWN=$unknown ==="
Log ""
Log "known-but-not-probed (would block or change state):"
foreach ($k in $known) { Log ("  - {0,-16} {1}" -f $k.Cmd, $k.Note) }

$sp.Close()
[IO.File]::WriteAllLines($log, $lines)
"LOG=$log"
