# Run once in the project folder. The generated .env stays on this computer.
$ErrorActionPreference = 'Stop'
$target = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
if (Test-Path -LiteralPath $target) {
    throw '.env already exists. Keep it for the existing volume or move it aside deliberately before generating new keys.'
}

function New-Secret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([System.BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}

$identities = @(
    @{ key = (New-Secret); agent_id = 'finance-sandbox'; role = 'finance' },
    @{ key = (New-Secret); agent_id = 'support-sandbox'; role = 'support_agent' }
)
$json = ConvertTo-Json -InputObject $identities -Compress -Depth 3
$content = "AGENTGUARD_IDENTITIES=$json`nAGENTGUARD_ADMIN_KEY=$(New-Secret)`nAGENTGUARD_SIGNING_SECRET=$(New-Secret)`n"
[System.IO.File]::WriteAllText($target, $content, (New-Object System.Text.UTF8Encoding($false)))
Write-Host 'Created .env with distinct random keys. Keep it private and back it up with the database volume.'
