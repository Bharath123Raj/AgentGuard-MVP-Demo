# Create credentials for the optional Render staging Blueprint; never commit this file.
$ErrorActionPreference = 'Stop'
$target = Join-Path (Split-Path $PSScriptRoot -Parent) '.env.render'
if (Test-Path -LiteralPath $target) {
    throw '.env.render already exists. Keep the signing secret with the existing Render database.'
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
$content = "AGENTGUARD_IDENTITIES=$json`nAGENTGUARD_ADMIN_KEY=$(New-Secret)`nAGENTGUARD_SIGNING_SECRET=$(New-Secret)`nAGENTGUARD_STAGING_PASSWORD=$(New-Secret)`n"
[System.IO.File]::WriteAllText($target, $content, (New-Object System.Text.UTF8Encoding($false)))
Write-Host 'Created .env.render. Enter its values in Render when the Blueprint asks; never commit or share the file.'
