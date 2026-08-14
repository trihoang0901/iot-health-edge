[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string]$InputDocx,
    [Parameter(Mandatory)] [string]$OutputDir,
    [int]$Dpi = 120,
    [string]$PythonExe = ''
)

$ErrorActionPreference = 'Stop'
$inputPath = (Resolve-Path -LiteralPath $InputDocx).Path
if (Test-Path -LiteralPath $OutputDir) {
    if (@(Get-ChildItem -LiteralPath $OutputDir -Force).Count -gt 0) {
        throw "OutputDir phai moi va rong de tranh page PNG cu"
    }
}
else {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}
$outputPath = (Resolve-Path -LiteralPath $OutputDir).Path
$pdfPath = Join-Path $outputPath (([IO.Path]::GetFileNameWithoutExtension($inputPath)) + '.pdf')

$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    # Open writable so cached TOC/PAGE fields and document statistics survive
    # the render step in the delivered DOCX, not only in the exported PDF.
    $document = $word.Documents.Open($inputPath, $false, $false)
    $document.Fields.Update() | Out-Null
    foreach ($toc in @($document.TablesOfContents)) {
        $toc.Update() | Out-Null
    }
    $document.Repaginate()
    $document.Fields.Update() | Out-Null
    $document.Save()
    $document.ExportAsFixedFormat($pdfPath, 17)
}
finally {
    if ($document) {
        $document.Close($false)
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($document) | Out-Null
    }
    if ($word) {
        $word.Quit()
        [Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) | Out-Null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $projectPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $projectPython) {
        $PythonExe = $projectPython
    }
    else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCommand) {
            $PythonExe = $pythonCommand.Source
        }
    }
}
if ([string]::IsNullOrWhiteSpace($PythonExe) -or -not (Test-Path -LiteralPath $PythonExe)) {
    throw "Khong tim thay Python. Cai .[artifact] vao .venv hoac truyen -PythonExe."
}
& $PythonExe -c 'import pypdfium2'
if ($LASTEXITCODE -ne 0) {
    throw "Python da chon thieu pypdfium2; cai dependency group .[artifact]."
}

$rasterScript = @'
import sys
from pathlib import Path
from pypdfium2 import PdfDocument

pdf_path = Path(sys.argv[1])
output_dir = Path(sys.argv[2])
dpi = int(sys.argv[3])
scale = dpi / 72.0
pdf = PdfDocument(pdf_path)
try:
    for index in range(len(pdf)):
        page = pdf[index]
        bitmap = page.render(scale=scale)
        bitmap.to_pil().convert("RGB").save(output_dir / f"page-{index + 1}.png")
        bitmap.close()
        page.close()
    print(f"PAGES={len(pdf)}")
finally:
    pdf.close()
'@

$rasterScript | & $PythonExe - $pdfPath $outputPath $Dpi
if ($LASTEXITCODE -ne 0) {
    throw "Raster PDF that bai: exit $LASTEXITCODE"
}

$pdfPageCount = & $PythonExe -c 'import sys; from pypdfium2 import PdfDocument; p=PdfDocument(sys.argv[1]); print(len(p)); p.close()' $pdfPath
if ($LASTEXITCODE -ne 0) {
    throw "Khong dem duoc so trang PDF"
}
$pngCount = @(Get-ChildItem -LiteralPath $outputPath -Filter 'page-*.png').Count
if ($pngCount -ne [int]$pdfPageCount) {
    throw "So PNG ($pngCount) khong khop so trang PDF ($pdfPageCount)"
}

Write-Host "PDF=$pdfPath"
