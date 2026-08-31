# PowerShell port of download_lom.py — same scraping logic, runs without Python.
# Usage:
#   .\download_lom.ps1 -Test                       # 5 records per category
#   .\download_lom.ps1 -All                        # full download
#   .\download_lom.ps1 -Categories updated         # one category
#   .\download_lom.ps1 -Categories updated -Limit 50

[CmdletBinding()]
param(
    [switch]$All,
    [switch]$Test,
    [string]$Categories = "",
    [int]$Limit = 0
)

$ErrorActionPreference = 'Stop'
$Base       = 'https://lom.agc.gov.my'
$UserAgent  = 'Mozilla/5.0 (LOM-RAG-Corpus-Builder; personal research)'
$RateLimit  = 1.0     # seconds between requests
$PageSize   = 200
$OutRoot    = Join-Path $PSScriptRoot 'pdfs'
$Manifest   = Join-Path $PSScriptRoot 'manifest.csv'
$LogFile    = Join-Path $PSScriptRoot 'download.log'

$Categories_All = @(
    @{ key='updated';      label='Principal Acts (Updated)';        endpoint='/json-updated-2024.php';      needsLang=$true  },
    @{ key='repealed';     label='Principal Acts (Repealed)';       endpoint='/json-repealed-2024.php';     needsLang=$true  },
    @{ key='translated';   label='Principal Acts (Translated)';     endpoint='/json-translated-2024.php';   needsLang=$true  },
    @{ key='revised';      label='Principal Acts (Revised)';        endpoint='/json-revised-2024.php';      needsLang=$true  },
    @{ key='amendment';    label='Amendment Acts';                  endpoint='/json-amendment-2024.php';    needsLang=$true  },
    @{ key='fc_amendment'; label='Federal Constitution Amendments'; endpoint='/json-amendment-fc-2024.php'; needsLang=$true  },
    @{ key='ordinance';    label='Ordinances';                      endpoint='/json-ordinance-2024.php';    needsLang=$false }
)
$FederalConstitution = @(
    @{ lang='BI'; path='/ilims/upload/portal/akta/LOM/EN/Federal Constitution (Reprint 2020).pdf' },
    @{ lang='BM'; path='/ilims/upload/portal/akta/LOM/MY/Perlembagaan Persekutuan (Cetakan Semula 2020).pdf' }
)

$script:LastRequest = [DateTime]::MinValue
function Throttle {
    $elapsed = ([DateTime]::Now - $script:LastRequest).TotalSeconds
    if ($elapsed -lt $RateLimit) { Start-Sleep -Milliseconds ([int](($RateLimit - $elapsed) * 1000)) }
    $script:LastRequest = [DateTime]::Now
}

function Write-Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format HH:mm:ss), $msg
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Get-Json([string]$endpoint, [int]$start, [int]$length, [string]$language) {
    Throttle
    $body = @{
        draw = 1; start = $start; length = $length;
        'search[value]' = ''; 'order[0][column]' = 0; 'order[0][dir]' = 'desc'
    }
    if ($language) { $body['language'] = $language }
    $resp = Invoke-WebRequest -Uri "$Base$endpoint" -Method POST -Body $body `
        -UseBasicParsing -UserAgent $UserAgent -TimeoutSec 60
    return $resp.Content | ConvertFrom-Json
}

function Get-PdfUrls([object]$record) {
    $urls = New-Object System.Collections.Generic.List[string]
    foreach ($prop in $record.PSObject.Properties) {
        $v = $prop.Value
        if ($v -isnot [string]) { continue }
        foreach ($m in [regex]::Matches($v, 'href="((?:\.\./)+ilims/[^"]+?\.pdf)"', 'IgnoreCase')) {
            $rel = $m.Groups[1].Value
            $abs = $Base + '/' + ($rel -replace '^(\./|\.\./)+', '')
            if (-not $urls.Contains($abs)) { $urls.Add($abs) }
        }
    }
    # ',' prevents PowerShell from unwrapping an empty List to $null on return.
    return ,$urls
}

# For categories (repealed, translated) whose JSON returns only metadata, fetch
# the per-act detail page and extract PDFs embedded via the pdfjs viewer URL.
$script:DetailCache = @{}
function Get-DetailPageUrls([object]$record) {
    $detailUrls = New-Object System.Collections.Generic.List[string]
    # (1) Any explicit act-detail.php links embedded in string fields.
    foreach ($prop in $record.PSObject.Properties) {
        $v = $prop.Value
        if ($v -isnot [string]) { continue }
        foreach ($m in [regex]::Matches($v, 'act-detail\.php\?act=([^&"#]+)&lang=([A-Z]+)', 'IgnoreCase')) {
            $u = "$Base/act-detail.php?act=$($m.Groups[1].Value)&lang=$($m.Groups[2].Value)"
            if (-not $detailUrls.Contains($u)) { $detailUrls.Add($u) }
        }
    }
    # (2) Otherwise, construct from a field whose name looks like an act-number key.
    if ($detailUrls.Count -eq 0) {
        $actNo = $null
        foreach ($name in @('ILA_ACT_NO','lgt_act_no','lgt_act_id','ACTNO_LEGISLATION','NOMBOR_ORDINAN','NO_ORDINAN')) {
            $prop = $record.PSObject.Properties[$name]
            if ($null -eq $prop) { continue }
            $v = $prop.Value
            if ($null -ne $v -and "$v".Length -gt 0) { $actNo = [string]$v; break }
        }
        if ($actNo) {
            $encoded = [System.Uri]::EscapeDataString($actNo)
            foreach ($lang in @('BI','BM')) {
                $detailUrls.Add("$Base/act-detail.php?act=$encoded&lang=$lang")
            }
        }
    }
    return ,$detailUrls
}

function Get-PdfUrlsFromDetail([string]$detailUrl) {
    if ($script:DetailCache.ContainsKey($detailUrl)) { return $script:DetailCache[$detailUrl] }
    $urls = New-Object System.Collections.Generic.List[string]
    try {
        Throttle
        $r = Invoke-WebRequest -Uri $detailUrl -UseBasicParsing -UserAgent $UserAgent -TimeoutSec 60
        # pdfjs viewer references the actual PDF via ?file=<rel-path>.pdf
        foreach ($m in [regex]::Matches($r.Content, 'pdfjs/web/viewer\.html\?file=((?:\.\./)+ilims/[^"&]+?\.pdf)', 'IgnoreCase')) {
            $rel = $m.Groups[1].Value
            $abs = $Base + '/' + ($rel -replace '^(\./|\.\./)+', '')
            if (-not $urls.Contains($abs)) { $urls.Add($abs) }
        }
        # Some detail pages also use plain hrefs to .pdf
        foreach ($m in [regex]::Matches($r.Content, 'href="((?:\.\./)+ilims/[^"]+?\.pdf)"', 'IgnoreCase')) {
            $rel = $m.Groups[1].Value
            $abs = $Base + '/' + ($rel -replace '^(\./|\.\./)+', '')
            if (-not $urls.Contains($abs)) { $urls.Add($abs) }
        }
    } catch {
        Write-Log "  ERROR fetching $detailUrl : $($_.Exception.Message)"
    }
    $script:DetailCache[$detailUrl] = $urls
    return ,$urls
}

function Get-LangTag([string]$url) {
    $u = $url.ToUpper()
    if ($u -match '_BI/' -or $u -match '/EN/') { return 'EN' }
    if ($u -match '_BM/' -or $u -match '/MY/') { return 'MS' }
    return 'UNK'
}

function Get-SafeFilename([string]$name) {
    $name = [System.Uri]::UnescapeDataString($name)
    $name = $name -replace '[\\/:*?"<>|]', '_'
    if ($name.Length -gt 200) { $name = $name.Substring(0, 200) }
    if (-not $name) { $name = 'untitled.pdf' }
    return $name.Trim()
}

function Save-Pdf([string]$url, [string]$destPath) {
    if ([System.IO.File]::Exists($destPath) -and ([System.IO.FileInfo]::new($destPath)).Length -gt 0) {
        return @{ downloaded=$false; size=([System.IO.FileInfo]::new($destPath)).Length }
    }
    $destDir = [System.IO.Path]::GetDirectoryName($destPath)
    [System.IO.Directory]::CreateDirectory($destDir) | Out-Null
    Throttle
    # Percent-encode characters that some servers reject (brackets, spaces handled by Uri ctor).
    $safeUrl = $url -replace '\[', '%5B' -replace '\]', '%5D'
    try {
        # Use HttpWebRequest + stream copy to avoid Invoke-WebRequest's wildcard
        # interpretation of '[' and ']' in -OutFile paths.
        $req = [System.Net.HttpWebRequest]::Create($safeUrl)
        $req.UserAgent  = $UserAgent
        $req.Timeout    = 120000
        $req.ReadWriteTimeout = 120000
        $resp = $req.GetResponse()
        try {
            $in  = $resp.GetResponseStream()
            $out = [System.IO.File]::Open($destPath, [System.IO.FileMode]::Create,
                                          [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
            try {
                $buf = New-Object byte[] 65536
                while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {
                    $out.Write($buf, 0, $n)
                }
            } finally {
                $out.Dispose()
                $in.Dispose()
            }
        } finally {
            $resp.Close()
        }
    } catch {
        Write-Log "  ERROR $url : $($_.Exception.Message)"
        if ([System.IO.File]::Exists($destPath)) { [System.IO.File]::Delete($destPath) }
        return @{ downloaded=$false; size=0 }
    }
    return @{ downloaded=$true; size=([System.IO.FileInfo]::new($destPath)).Length }
}

function Add-ManifestRow($row) {
    $newFile = -not (Test-Path $Manifest)
    if ($newFile) {
        'category,language,source_url,local_path,size_bytes' | Out-File -FilePath $Manifest -Encoding UTF8
    }
    $line = '"{0}","{1}","{2}","{3}",{4}' -f $row.category, $row.language,
            $row.source_url, $row.local_path.Replace('"','""'), $row.size_bytes
    Add-Content -Path $Manifest -Value $line -Encoding UTF8
}

function Invoke-CategoryDownload($cat, [int]$limitArg) {
    Write-Log "=== $($cat.label) ==="
    $outDir = Join-Path $OutRoot $cat.key
    if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }

    $language = if ($cat.needsLang) { 'BI' } else { $null }
    $head = Get-Json -endpoint $cat.endpoint -start 0 -length 1 -language $language
    $total = [int]$head.recordsTotal
    if ($limitArg -gt 0) { $total = [Math]::Min($total, $limitArg) }
    Write-Log "  $total records to scan via $($cat.endpoint)"

    $seen = @{}
    $start = 0
    while ($start -lt $total) {
        $length = [Math]::Min($PageSize, $total - $start)
        $payload = Get-Json -endpoint $cat.endpoint -start $start -length $length -language $language
        if (-not $payload.records) { break }
        foreach ($rec in $payload.records) {
            $pdfUrls = Get-PdfUrls $rec
            if ($pdfUrls.Count -eq 0) {
                # Fallback: fetch per-act detail page(s) and extract PDFs from pdfjs viewer.
                foreach ($detail in (Get-DetailPageUrls $rec)) {
                    foreach ($u in (Get-PdfUrlsFromDetail $detail)) {
                        if (-not $pdfUrls.Contains($u)) { $pdfUrls.Add($u) }
                    }
                }
            }
            foreach ($url in $pdfUrls) {
                if ($seen.ContainsKey($url)) { continue }
                $seen[$url] = $true
                $fname = Get-SafeFilename ($url.Split('/')[-1])
                $lang  = Get-LangTag $url
                $dest  = Join-Path $outDir (Join-Path $lang $fname)
                $res   = Save-Pdf $url $dest
                $tag   = if ($res.downloaded) { 'GOT ' } else { 'skip' }
                Write-Log ("  [{0}] {1}\{2}\{3} ({4} B)" -f $tag, $cat.key, $lang, $fname, $res.size)
                Add-ManifestRow @{
                    category=$cat.key; language=$lang; source_url=$url;
                    local_path=$dest; size_bytes=$res.size
                }
            }
        }
        $start += $length
    }
    Write-Log "  done: $($seen.Count) unique URLs"
}

function Invoke-ConstitutionDownload {
    Write-Log "=== Federal Constitution (reprint) ==="
    $outDir = Join-Path $OutRoot 'federal_constitution'
    foreach ($item in $FederalConstitution) {
        $url   = $Base + $item.path
        $fname = Get-SafeFilename ($item.path.Split('/')[-1])
        $lang  = if ($item.lang -eq 'BI') { 'EN' } else { 'MS' }
        $dest  = Join-Path $outDir (Join-Path $lang $fname)
        $res   = Save-Pdf $url $dest
        $tag   = if ($res.downloaded) { 'GOT ' } else { 'skip' }
        Write-Log ("  [{0}] federal_constitution\{1}\{2} ({3} B)" -f $tag, $lang, $fname, $res.size)
        Add-ManifestRow @{
            category='federal_constitution'; language=$lang; source_url=$url;
            local_path=$dest; size_bytes=$res.size
        }
    }
}

# --- main ---
if (-not (Test-Path $OutRoot)) { New-Item -ItemType Directory -Path $OutRoot -Force | Out-Null }
Write-Log "Output: $OutRoot"

if (-not ($All -or $Test -or $Categories)) {
    Write-Host "Specify -Test, -All, or -Categories <key,key>"
    exit 1
}

$effLimit = if ($Test) { 5 } else { $Limit }

if ($Categories) {
    $keys = $Categories.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }
} else {
    $keys = @('federal_constitution') + ($Categories_All | ForEach-Object { $_.key })
}

foreach ($key in $keys) {
    if ($key -eq 'federal_constitution') { Invoke-ConstitutionDownload; continue }
    $cat = $Categories_All | Where-Object { $_.key -eq $key } | Select-Object -First 1
    if (-not $cat) { Write-Log "Unknown category: $key"; continue }
    Invoke-CategoryDownload -cat $cat -limitArg $effLimit
}
Write-Log "All done."
