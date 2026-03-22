# push.ps1 for Windows
# Usage: .\push.ps1

# 한글 출력을 위해 출력 인코딩 설정
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$msg = Read-Host -Prompt "Enter Update comment (if empty, 'Self Update')"
if (-not $msg) { $msg = "Self Update" }

git add .
git commit -m $msg
git push origin main

Write-Host "`n[SUCCESS] Local changes pushed to GitHub." -ForegroundColor Green
Write-Host "Now run ./update.sh on your GCP VM server."
