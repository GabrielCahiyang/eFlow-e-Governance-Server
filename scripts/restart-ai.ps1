param()

$repoPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$aiProcessPatterns = @(
    "*Ollama reactjs LLM DeepSeek Integration*server\main.py*",
    "*Ollama reactjs LLM DeepSeek Integration*server\public_gateway.py*",
    "*Ollama reactjs LLM DeepSeek Integration*server\start.py*",
    "*Ollama reactjs LLM DeepSeek Integration*server\tunnel_supervisor.py*",
    "*Ollama reactjs LLM DeepSeek Integration*concurrently\dist\bin\concurrently.js*",
    "*Ollama reactjs LLM DeepSeek Integration*node_modules*vite*",
    "*cloudflared*tunnel*--url http://127.0.0.1:8322*"
)

$processes = Get-CimInstance Win32_Process | Where-Object {
    $commandLine = $_.CommandLine
    $commandLine -and ($aiProcessPatterns | Where-Object {
        $commandLine -like $_
    } | Select-Object -First 1)
}

foreach ($process in $processes) {
    try {
        & taskkill.exe /F /T /PID $process.ProcessId | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "taskkill exited with code $LASTEXITCODE"
        }
        Write-Host "Stopped previous AI process $($process.ProcessId)."
    } catch {
        Write-Warning "Could not stop AI process $($process.ProcessId): $($_.Exception.Message)"
    }
}

Start-Sleep -Seconds 1
Set-Location $repoPath
& npm.cmd run dev
exit $LASTEXITCODE
