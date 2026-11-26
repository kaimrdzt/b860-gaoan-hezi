# check-burnmode.ps1 — 判定最近一次烧录走的是"冷 BootROM 模式"还是"U-Boot 从模式"
# 用法: pwsh -NoProfile -File D:\b860\scripts\check-burnmode.ps1
param([string]$LogRoot = 'C:\Amlogic\Aml_Burn_Tool\V2\log')

$enc = [System.Text.Encoding]::GetEncoding(936)
$f = Get-ChildItem $LogRoot -Recurse -Filter '*.txt' -ErrorAction SilentlyContinue |
     Where-Object { $_.Name -match '^\d{4}\.\d{2}\.\d{2}-\d+\.txt$' } |
     Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $f) { "未找到烧录日志: $LogRoot"; exit 1 }

# 日志常被烧录工具以独占方式持有，用 ReadWrite 共享方式打开
$fs = [IO.File]::Open($f.FullName, 'Open', 'Read', 'ReadWrite')
$ms = [IO.MemoryStream]::new()
$fs.CopyTo($ms); $fs.Close()
$lines = $enc.GetString($ms.ToArray()) -split "`r?`n" | Where-Object { $_.Trim() }

$start = -1
for ($i = $lines.Count - 1; $i -ge 0; $i--) { if ($lines[$i] -match 'User click start button') { $start = $i; break } }
$block = $lines
if ($start -ge 0) { $block = $lines[$start..($lines.Count - 1)] }

$img  = $block | Where-Object { $_ -match 'OpenImg' } | Select-Object -Last 1
if (-not $img) { $img = $lines | Where-Object { $_ -match 'OpenImg' } | Select-Object -Last 1 }
$mode = $block | Where-Object { $_ -match '--(0-7|2-4)-\d+-' } | Select-Object -First 1
$ddr  = $block | Where-Object { $_ -match 'Download DDR_ENC\.USB,\s*size' } | Select-Object -First 1
$nodl = $block | Where-Object { $_ -match 'No need download' } | Select-Object -First 1
$ddrp = $block | Where-Object { $_ -match 'store ddr_parameter erase' } | Select-Object -First 1
$err  = $block | Where-Object { $_ -match '\[Err\]--failed' } | Select-Object -Last 1

$imgTxt = '(未记录)'
if ($img) { $imgTxt = ($img -split 'path\s+')[-1] }
$modeTxt = '(无)'
if ($mode) { $modeTxt = ($mode -replace '.*\]--', '').Trim() }

"日志: $($f.FullName)"
"镜像: $imgTxt"
"模式行: $modeTxt"
""

if ($ddr) {
  "判定: 冷 BootROM 模式（已下载 DDR_ENC.USB 49152B）—— 这是要的模式"
} elseif ($nodl) {
  "判定: U-Boot 从模式（设备已在运行 U-Boot，工具复用它）—— 不是要的模式，必须彻底断电重来"
} else {
  "判定: 无法识别（日志里既无 DDR 下载也无 No need download）"
}

""
if ($ddrp) { "本次触发: store ddr_parameter erase —— 这台 U-Boot 无此子命令，必失败" }
elseif ($err) { "本次错误: " + ($err -replace '.*\]--', '').Trim() }
else { "本次未出现 ddr_parameter，也未见 failed 行" }
