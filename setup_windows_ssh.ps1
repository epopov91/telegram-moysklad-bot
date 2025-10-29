# PowerShell скрипт для автоматической настройки SSH на Windows
# Запустите от имени Администратора!

Write-Host "===========================================`n" -ForegroundColor Cyan
Write-Host "  SSH Setup для удаленного управления`n" -ForegroundColor Cyan
Write-Host "===========================================`n" -ForegroundColor Cyan

# Проверка прав администратора
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "❌ Этот скрипт нужно запустить от имени Администратора!" -ForegroundColor Red
    Write-Host "`nНажмите Win+X и выберите 'Windows PowerShell (Администратор)'" -ForegroundColor Yellow
    pause
    exit 1
}

Write-Host "✅ Права администратора подтверждены`n" -ForegroundColor Green

# Установка OpenSSH Server
Write-Host "📦 Установка OpenSSH Server..." -ForegroundColor Blue
try {
    $capability = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
    if ($capability.State -ne "Installed") {
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
        Write-Host "✅ OpenSSH Server установлен`n" -ForegroundColor Green
    } else {
        Write-Host "✅ OpenSSH Server уже установлен`n" -ForegroundColor Green
    }
} catch {
    Write-Host "❌ Ошибка при установке OpenSSH: $_" -ForegroundColor Red
    pause
    exit 1
}

# Запуск службы SSH
Write-Host "🚀 Запуск службы SSH..." -ForegroundColor Blue
try {
    Start-Service sshd
    Write-Host "✅ Служба SSH запущена`n" -ForegroundColor Green
} catch {
    Write-Host "⚠️  Служба SSH уже запущена или возникла ошибка`n" -ForegroundColor Yellow
}

# Автозапуск SSH
Write-Host "⚙️  Настройка автозапуска SSH..." -ForegroundColor Blue
Set-Service -Name sshd -StartupType 'Automatic'
Write-Host "✅ SSH будет запускаться автоматически`n" -ForegroundColor Green

# Настройка брандмауэра
Write-Host "🔥 Настройка брандмауэра..." -ForegroundColor Blue
$firewallRule = Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
if (-not $firewallRule) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
    Write-Host "✅ Правило брандмауэра создано`n" -ForegroundColor Green
} else {
    Write-Host "✅ Правило брандмауэра уже существует`n" -ForegroundColor Green
}

# Получение IP адреса
Write-Host "===========================================`n" -ForegroundColor Cyan
Write-Host "  Информация для подключения`n" -ForegroundColor Cyan
Write-Host "===========================================`n" -ForegroundColor Cyan

$ipAddress = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.InterfaceAlias -notlike "*Loopback*" -and $_.IPAddress -notlike "169.254.*"} | Select-Object -First 1).IPAddress
$username = $env:USERNAME

Write-Host "IP адрес Windows: " -NoNewline -ForegroundColor Yellow
Write-Host "$ipAddress" -ForegroundColor White

Write-Host "Имя пользователя: " -NoNewline -ForegroundColor Yellow
Write-Host "$username" -ForegroundColor White

Write-Host "`nПароль: " -NoNewline -ForegroundColor Yellow
Write-Host "Ваш пароль Windows" -ForegroundColor White

Write-Host "`n⚠️  ВАЖНО: У вашего пользователя должен быть установлен пароль!" -ForegroundColor Red
Write-Host "Если пароля нет, создайте его через Панель управления > Учетные записи пользователей`n" -ForegroundColor Yellow

# Проверка Python
Write-Host "===========================================`n" -ForegroundColor Cyan
Write-Host "  Проверка дополнительных компонентов`n" -ForegroundColor Cyan
Write-Host "===========================================`n" -ForegroundColor Cyan

Write-Host "Проверка Python..." -ForegroundColor Blue
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python установлен: $pythonVersion`n" -ForegroundColor Green
} catch {
    Write-Host "❌ Python НЕ установлен!" -ForegroundColor Red
    Write-Host "Скачайте с https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "⚠️  При установке поставьте галочку 'Add Python to PATH'`n" -ForegroundColor Yellow
}

# Проверка Git
Write-Host "Проверка Git..." -ForegroundColor Blue
try {
    $gitVersion = git --version 2>&1
    Write-Host "✅ Git установлен: $gitVersion`n" -ForegroundColor Green
} catch {
    Write-Host "❌ Git НЕ установлен!" -ForegroundColor Red
    Write-Host "Скачайте с https://git-scm.com/download/win`n" -ForegroundColor Yellow
}

# Проверка SSH
Write-Host "Проверка SSH..." -ForegroundColor Blue
$sshStatus = Get-Service sshd
if ($sshStatus.Status -eq "Running") {
    Write-Host "✅ SSH сервис работает!`n" -ForegroundColor Green
} else {
    Write-Host "❌ SSH сервис не запущен!`n" -ForegroundColor Red
}

Write-Host "===========================================`n" -ForegroundColor Cyan
Write-Host "  🎉 Настройка завершена!`n" -ForegroundColor Cyan
Write-Host "===========================================`n" -ForegroundColor Cyan

Write-Host "Скопируйте данные для подключения:" -ForegroundColor Yellow
Write-Host "IP: $ipAddress" -ForegroundColor White
Write-Host "Пользователь: $username" -ForegroundColor White
Write-Host "Пароль: [ваш пароль Windows]`n" -ForegroundColor White

Write-Host "Отправьте эти данные в Cursor AI, и всё будет работать автоматически!`n" -ForegroundColor Green

pause

