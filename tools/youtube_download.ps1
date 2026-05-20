# Скачивает YouTube видео в папку для лекций.
#
# Использование (из любой папки):
#   PowerShell -File C:\1с_dev\garmin_analytics\tools\youtube_download.ps1 "https://www.youtube.com/watch?v=XXXX"
#
# Или с активированным venv просто:
#   .\tools\youtube_download.ps1 "https://www.youtube.com/watch?v=XXXX"
#
# Что делает:
#   - Скачивает 720p mp4 (баланс качества/размера для последующего анализа)
#   - Использует cookies Chrome (обход YouTube anti-bot)
#   - Кладёт в C:\Лекции по подготовке в циклических видах спорта\Youtube\
#   - Имя файла = заголовок видео

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Url
)

$ProjectRoot = "C:\1с_dev\garmin_analytics"
$OutputDir   = "C:\Лекции по подготовке в циклических видах спорта\Youtube"

# Создаём папку если её нет
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

# Активируем venv
$Activate = Join-Path $ProjectRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $Activate) {
    . $Activate
} else {
    Write-Host "venv не найден в $Activate" -ForegroundColor Red
    exit 1
}

# Шаблон для имени файла (заголовок видео)
$OutputTemplate = Join-Path $OutputDir "%(title)s.%(ext)s"

Write-Host "Скачиваю: $Url" -ForegroundColor Cyan
Write-Host "В папку:  $OutputDir" -ForegroundColor Cyan
Write-Host ""

yt-dlp `
    --cookies-from-browser chrome `
    -f "bv*[height<=720]+ba/b[height<=720]" `
    --merge-output-format mp4 `
    -o $OutputTemplate `
    --no-mtime `
    $Url

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Готово. Файл в $OutputDir" -ForegroundColor Green
    Write-Host "Скажи Claude путь к файлу — он запустит разбор." -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Ошибка скачивания (код $LASTEXITCODE)" -ForegroundColor Red
    Write-Host "Частая причина: Chrome открыт и блокирует доступ к cookies." -ForegroundColor Yellow
    Write-Host "  Решение: закрой ВСЕ окна Chrome → повтори команду." -ForegroundColor Yellow
}
