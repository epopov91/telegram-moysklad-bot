# PowerShell script for automatic SSH setup on Windows
# Run as Administrator!

Write-Host "==========================================="
Write-Host "  SSH Setup for Remote Management"
Write-Host "==========================================="
Write-Host ""

# Check administrator rights
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "[ERROR] This script must be run as Administrator!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Press Win+X and select 'Windows PowerShell (Administrator)'" -ForegroundColor Yellow
    pause
    exit 1
}

Write-Host "[OK] Administrator rights confirmed" -ForegroundColor Green
Write-Host ""

# Install OpenSSH Server
Write-Host "Installing OpenSSH Server..." -ForegroundColor Cyan
try {
    $capability = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
    if ($capability.State -ne "Installed") {
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
        Write-Host "[OK] OpenSSH Server installed" -ForegroundColor Green
    } else {
        Write-Host "[OK] OpenSSH Server already installed" -ForegroundColor Green
    }
} catch {
    Write-Host "[ERROR] Failed to install OpenSSH: $_" -ForegroundColor Red
    pause
    exit 1
}
Write-Host ""

# Start SSH service
Write-Host "Starting SSH service..." -ForegroundColor Cyan
try {
    Start-Service sshd
    Write-Host "[OK] SSH service started" -ForegroundColor Green
} catch {
    Write-Host "[WARNING] SSH service already running or error occurred" -ForegroundColor Yellow
}
Write-Host ""

# Configure SSH autostart
Write-Host "Configuring SSH autostart..." -ForegroundColor Cyan
Set-Service -Name sshd -StartupType 'Automatic'
Write-Host "[OK] SSH will start automatically" -ForegroundColor Green
Write-Host ""

# Configure firewall
Write-Host "Configuring firewall..." -ForegroundColor Cyan
$firewallRule = Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
if (-not $firewallRule) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
    Write-Host "[OK] Firewall rule created" -ForegroundColor Green
} else {
    Write-Host "[OK] Firewall rule already exists" -ForegroundColor Green
}
Write-Host ""

# Get IP address
Write-Host "==========================================="
Write-Host "  Connection Information"
Write-Host "==========================================="
Write-Host ""

$ipAddress = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.InterfaceAlias -notlike "*Loopback*" -and $_.IPAddress -notlike "169.254.*"} | Select-Object -First 1).IPAddress
$username = $env:USERNAME

Write-Host "Windows IP Address: " -NoNewline -ForegroundColor Yellow
Write-Host "$ipAddress" -ForegroundColor White

Write-Host "Username: " -NoNewline -ForegroundColor Yellow
Write-Host "$username" -ForegroundColor White

Write-Host ""
Write-Host "Password: " -NoNewline -ForegroundColor Yellow
Write-Host "Your Windows password" -ForegroundColor White

Write-Host ""
Write-Host "[IMPORTANT] Your Windows user MUST have a password set!" -ForegroundColor Red
Write-Host "If you don't have a password, create one via Control Panel > User Accounts" -ForegroundColor Yellow
Write-Host ""

# Check Python
Write-Host "==========================================="
Write-Host "  Checking Additional Components"
Write-Host "==========================================="
Write-Host ""

Write-Host "Checking Python..." -ForegroundColor Cyan
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[OK] Python installed: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python NOT installed!" -ForegroundColor Red
    Write-Host "Download from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "IMPORTANT: Check 'Add Python to PATH' during installation" -ForegroundColor Yellow
}
Write-Host ""

# Check Git
Write-Host "Checking Git..." -ForegroundColor Cyan
try {
    $gitVersion = git --version 2>&1
    Write-Host "[OK] Git installed: $gitVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Git NOT installed!" -ForegroundColor Red
    Write-Host "Download from https://git-scm.com/download/win" -ForegroundColor Yellow
}
Write-Host ""

# Check SSH
Write-Host "Checking SSH..." -ForegroundColor Cyan
$sshStatus = Get-Service sshd
if ($sshStatus.Status -eq "Running") {
    Write-Host "[OK] SSH service is running!" -ForegroundColor Green
} else {
    Write-Host "[ERROR] SSH service is NOT running!" -ForegroundColor Red
}
Write-Host ""

Write-Host "==========================================="
Write-Host "  Setup Complete!"
Write-Host "==========================================="
Write-Host ""

Write-Host "Copy this connection information:" -ForegroundColor Yellow
Write-Host "IP: $ipAddress" -ForegroundColor White
Write-Host "Username: $username" -ForegroundColor White
Write-Host "Password: [your Windows password]" -ForegroundColor White
Write-Host ""

Write-Host "Send this information to Cursor AI and everything will work automatically!" -ForegroundColor Green
Write-Host ""

pause

