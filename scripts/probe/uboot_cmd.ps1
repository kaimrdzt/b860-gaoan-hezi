param(
  [string]$Port = 'COM14',
  [string[]]$Cmds = @('printenv'),
  [int]$WaitForPort = 240,
  [int]$AfterMs = 2500,
  [string]$LogDir = 'D:\b860\out\probe'
)
# uboot-cmd.ps1 — 在 gxl_p211_v1# 提示符上逐条发送命令并捕获输出
# 用法: powershell -File scripts\uboot-cmd.ps1 -Port COM14 -Cmds printenv,help
#       powershell -File scripts\uboot-cmd.ps1 -Port COM14 -Cmds 'vout output 1080p60hz'
$tag = Get-Date -Format 'HHmmss'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$log = Join-Path $LogDir "ubootcmd-$tag.log"
$sb = [System.Text.StringBuilder]::new()
function Note { param([string]$s) [void]$script:sb.AppendLine($s) }

$start = Get-Date
$deadline = $start.AddSeconds($WaitForPort)
$free = $false
while ((Get-Date) -lt $deadline) {
  $probe = [System.IO.Ports.SerialPort]::new($Port, 115200)
  try { $probe.Open(); $probe.Close(); $free = $true } catch { }
  $probe.Dispose()
  if ($free) { break }
  Start-Sleep -Milliseconds 900
}
if (-not $free) {
  [IO.File]::WriteAllText($log, "$Port busy, nothing done`n")
  "TIMEOUT LOG=$log"
  exit 2
}

$sp = [System.IO.Ports.SerialPort]::new($Port, 115200, 'None', 8, 'One')
$sp.ReadTimeout = 250
$sp.DtrEnable = $true
$sp.RtsEnable = $true
$sp.Open()
Start-Sleep -Milliseconds 300
$sp.DiscardInBuffer()

function Send-Slow {
  param([string]$cmd, [int]$chunk = 20, [int]$ms = 25, [int]$wait = 800)
  Note ">>> $cmd"
  $b = [Text.Encoding]::ASCII.GetBytes($cmd)
  for ($i = 0; $i -lt $b.Length; $i += $chunk) {
    $n = [Math]::Min($chunk, $b.Length - $i)
    $sp.Write([Text.Encoding]::ASCII.GetString($b, $i, $n))
    Start-Sleep -Milliseconds $ms
  }
  $sp.Write("`r")
  Start-Sleep -Milliseconds $wait
  Note ($sp.ReadExisting())
}
function Drain {
  param([int]$ms)
  $e = (Get-Date).AddMilliseconds($ms)
  while ((Get-Date) -lt $e) {
    $d = $sp.ReadExisting()
    if ($d) { Note $d }
    Start-Sleep -Milliseconds 50
  }
}

# 先发一个回车，确认提示符活着
$sp.Write("`r")
Start-Sleep -Milliseconds 600
Note ($sp.ReadExisting())
Note '=== SESSION START ==='

foreach ($c in $Cmds) {
  Send-Slow $c
  Drain $AfterMs
}

$sp.Close()
[IO.File]::WriteAllText($log, $sb.ToString())
"DONE LOG=$log"
Get-Content $log -Tail 60
