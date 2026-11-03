# Installs Tesseract (UB Mannheim build) and copies a trimmed copy with
# Turkish + English language data into the given destination folder.
param([Parameter(Mandatory = $true)][string]$Destination)
$ErrorActionPreference = "Stop"

$installDir = "C:\Program Files\Tesseract-OCR"
if (-not (Test-Path "$installDir\tesseract.exe")) {
    choco install tesseract -y --no-progress
}
if (-not (Test-Path "$installDir\tesseract.exe")) { throw "Tesseract install failed" }

New-Item -ItemType Directory -Force -Path "$Destination\tessdata" | Out-Null
Get-ChildItem $installDir -File | Where-Object { $_.Extension -in ".exe", ".dll" } |
    Where-Object { $_.Name -notlike "unins*" } |
    Copy-Item -Destination $Destination

$tessdata = "$Destination\tessdata"
Copy-Item "$installDir\tessdata\configs" "$tessdata\configs" -Recurse -Force
Copy-Item "$installDir\tessdata\pdf.ttf" $tessdata -Force
foreach ($lang in "eng", "osd") {
    Copy-Item "$installDir\tessdata\$lang.traineddata" $tessdata -Force
}
$base = "https://github.com/tesseract-ocr/tessdata_best/raw/main"
foreach ($lang in "tur") {
    Invoke-WebRequest "$base/$lang.traineddata" -OutFile "$tessdata\$lang.traineddata"
}
& "$Destination\tesseract.exe" --version
& "$Destination\tesseract.exe" --list-langs
