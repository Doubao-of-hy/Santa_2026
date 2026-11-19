# Turnkey build + extended search using the repo's proven C++ planner.
# Requires g++ on PATH (WinLibs/MinGW-w64). Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File improve\run_cpp_search.ps1
# It never overwrites original submissions; outputs go to improve\cpp\.
$ErrorActionPreference = "Stop"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONUTF8 = "1"
New-Item -ItemType Directory -Force improve\cpp | Out-Null
New-Item -ItemType Directory -Force work\virtual | Out-Null

$gpp = (Get-Command g++ -ErrorAction SilentlyContinue).Source
if (-not $gpp) {
    $cand = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter g++.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cand) { $gpp = $cand.FullName }
}
if (-not $gpp) { throw "g++ not found. Install WinLibs: winget install -e --id BrechtSanders.WinLibs.POSIX.UCRT" }
Write-Host "Using g++: $gpp"

# Compile the proven planner (single translation unit; includes konbu.cpp).
& $gpp -O3 -march=x86-64 -static -std=c++17 virtual.cpp -o work\virtual\improve_planner.exe
if ($LASTEXITCODE -ne 0) { throw "compile failed" }

# Extended virtual-register search warm-started from the merged incumbent.
python -B virtual_search.py data/puzzles.csv improve/merged/submission.csv improve/cpp/vsearch.csv `
    --exe work/virtual/improve_planner.exe --leaves 96 --width 7 --scan 2 --joins 13 --jobs 4 --checkpoint 25
python -B elf.py data/puzzles.csv improve/cpp/vsearch.csv

# Matrix/hub reconstruction on confident models, anchored to the merged incumbent.
python -B matrix_construct.py work/virtual/confident-models.jsonl improve/cpp/matrix.csv `
    --incumbent improve/cpp/vsearch.csv --exe work/virtual/improve_planner.exe --variants 8 --workers 3 --anchored
python -B elf.py data/puzzles.csv improve/cpp/matrix.csv
Write-Host "Done. Candidates in improve/cpp/. Merge per-puzzle best before submitting."