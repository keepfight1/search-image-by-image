param(
    [Parameter(Mandatory = $true)]
    [string]$DocumentPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$resolvedDocument = (Resolve-Path -LiteralPath $DocumentPath).Path
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($resolvedOutput) | Out-Null

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$word.AutomationSecurity = 3

try {
    $document = $word.Documents.Open($resolvedDocument, $false, $true)
    try {
        $pageCount = $document.ComputeStatistics(2)
        for ($page = 1; $page -le $pageCount; $page++) {
            $startRange = $document.GoTo(1, 1, $page)
            $start = $startRange.Start
            if ($page -lt $pageCount) {
                $nextRange = $document.GoTo(1, 1, $page + 1)
                $end = $nextRange.Start - 1
            }
            else {
                $end = $document.Content.End
            }

            $range = $document.Range($start, $end)
            $range.Select()
            $bits = $word.Selection.EnhMetaFileBits
            $emfPath = Join-Path $resolvedOutput ("page-{0:D2}.emf" -f $page)
            $pngPath = Join-Path $resolvedOutput ("page-{0:D2}.png" -f $page)
            [System.IO.File]::WriteAllBytes($emfPath, $bits)
            $image = [System.Drawing.Image]::FromFile($emfPath)
            try {
                $bitmap = New-Object System.Drawing.Bitmap($image.Width, $image.Height)
                try {
                    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
                    try {
                        $graphics.Clear([System.Drawing.Color]::White)
                        $graphics.DrawImage($image, 0, 0, $image.Width, $image.Height)
                    }
                    finally {
                        $graphics.Dispose()
                    }
                    $bitmap.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)
                }
                finally {
                    $bitmap.Dispose()
                }
            }
            finally {
                $image.Dispose()
            }
            Write-Output $pngPath
        }
    }
    finally {
        $document.Close($false)
    }
}
finally {
    $word.Quit()
}
