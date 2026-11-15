param([switch]$Approved)
# Supervised trusted-operator feasibility test. No application receives this token.
# Does not apply RBAC: approve and create windows-test-rbac.yaml separately first.
$ErrorActionPreference = 'Stop'
if (-not $Approved) { throw 'Explicit approval of temporary RBAC, test and cleanup is required.' }
$run = 'm1-win-20261111'
$identity = 'm1-client-20261111'
$base = 'https://127.0.0.1:16443'
$ca = Join-Path $env:USERPROFILE '.kube/katavm-ca.crt'
if (-not (Test-Path -LiteralPath $ca)) { throw 'Cluster CA missing; do not bypass TLS verification.' }
$token = $null
$tunnel = $null
$madeJob = $false
$madeInput = $false
$bodyPath = Join-Path $PSScriptRoot 'windows-request.tmp.json'
if (Test-Path -LiteralPath $bodyPath) { throw 'Temporary request path already exists.' }
function Request-Kube([string]$Method, [string]$Path, $Body = $null) {
    # Token is passed to curl through stdin, never through command-line arguments.
    $config = "silent`nshow-error`nfail-with-body`nheader = `"Authorization: Bearer $token`"`n"
    $curlArgs = @('--config', '-', '--ssl-revoke-best-effort', '--cacert', $ca,
                  '--connect-timeout', '5', '--max-time', '20', '-X', $Method, "$base$Path")
    if ($null -ne $Body) {
        [IO.File]::WriteAllText($bodyPath, ($Body | ConvertTo-Json -Depth 40), [Text.UTF8Encoding]::new($false))
        $curlArgs += @('-H', 'Content-Type: application/json', '--data-binary', "@$bodyPath")
    }
    $response = $config | & curl.exe @curlArgs
    if ($LASTEXITCODE -ne 0) { throw "HTTPS API request failed: $Method $Path" }
    return ($response -join "`n")
}
try {
    if (-not (Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 16443 -State Listen -ErrorAction SilentlyContinue)) {
        $tunnel = Start-Process -FilePath ssh.exe -ArgumentList @('-o','BatchMode=yes','-o','ExitOnForwardFailure=yes',
            '-N','-L','127.0.0.1:16443:127.0.0.1:6443','katavm') -WindowStyle Hidden -PassThru
        Start-Sleep -Seconds 2
        if ($tunnel.HasExited) { throw 'SSH tunnel failed.' }
    }
    # SSH stdout is captured directly into memory and never printed or persisted.
    $token = ((& ssh -o BatchMode=yes katavm "kubectl -n kata-lab create token $identity --duration=10m") -join '').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'Short-lived token request failed.' }
    $claimsPart = $token.Split('.')[1].Replace('-','+').Replace('_','/')
    $claimsPart = $claimsPart.PadRight($claimsPart.Length + ((4 - $claimsPart.Length % 4) % 4), '=')
    $claims = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($claimsPart)) | ConvertFrom-Json
    Write-Output "Granted credential lifetime seconds: $($claims.exp - $claims.iat)"
    $claims = $null; $claimsPart = $null
    $version = Request-Kube GET '/version' | ConvertFrom-Json
    Write-Output "Verified TLS API version: $($version.gitVersion)"
    $null = Request-Kube GET '/api/v1/namespaces/kata-lab/pods'
    Write-Output 'Namespace Pod listing: allowed'
    $cm = @{apiVersion='v1'; kind='ConfigMap'; metadata=@{name="$run-inputs"; namespace='kata-lab'};
        data=@{'data.csv'=[IO.File]::ReadAllText((Join-Path $PSScriptRoot 'data.csv'));
               'trusted_csv.py'=[IO.File]::ReadAllText((Join-Path $PSScriptRoot 'trusted_csv.py'))}}
    $inputObject = Request-Kube POST '/api/v1/namespaces/kata-lab/configmaps' $cm | ConvertFrom-Json
    $madeInput = $true
    Write-Output "Input ConfigMap UID: $($inputObject.metadata.uid)"
    # Convert the checked-in template to JSON on katavm; this is client-side
    # serialization only, not privileged workload submission.
    $yaml = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'job.template.yaml')).Replace('RUN_NAME',$run).Replace(
        'PYTHON_IMAGE_DIGEST','docker.io/library/python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b')
    $manifest = ($yaml | & ssh -o BatchMode=yes katavm 'kubectl create --dry-run=client -f - -o json') -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'Manifest serialization failed.' }
    $job = Request-Kube POST '/apis/batch/v1/namespaces/kata-lab/jobs' ($manifest | ConvertFrom-Json) | ConvertFrom-Json
    $madeJob = $true
    Write-Output "Windows-created Job: $($job.metadata.name), UID: $($job.metadata.uid)"
    $deadline = [DateTime]::UtcNow.AddSeconds(210)
    do {
        Start-Sleep -Seconds 3
        $job = Request-Kube GET "/apis/batch/v1/namespaces/kata-lab/jobs/$run" | ConvertFrom-Json
        if ($job.status.failed -gt 0) { throw 'Trusted Job failed.' }
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Timed out waiting for Job.' }
    } until ($job.status.succeeded -eq 1)
    $pods = Request-Kube GET "/api/v1/namespaces/kata-lab/pods?labelSelector=kataai-m1-run%3D$run" | ConvertFrom-Json
    if (@($pods.items).Count -ne 1) { throw 'Unexpected Pod count.' }
    $pod = $pods.items[0]
    if ($pod.metadata.ownerReferences[0].uid -ne $job.metadata.uid) { throw 'Pod owner mismatch.' }
    if ($pod.spec.runtimeClassName -ne 'kata-qemu-runtime-rs') { throw 'Wrong RuntimeClass.' }
    if ($pod.status.containerStatuses[0].state.terminated.exitCode -ne 0) { throw 'Nonzero exit.' }
    $logs = Request-Kube GET "/api/v1/namespaces/kata-lab/pods/$($pod.metadata.name)/log"
    $values = @($logs -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
    $result = @($values | Where-Object { $_.product -eq 'Notebook' })
    $diag = @($values | Where-Object { $_.uid -eq 10001 })
    if ($result.Count -ne 1 -or $result[0].october_units -ne 120 -or $result[0].november_units -ne 80 -or $result[0].change_units -ne -40) { throw 'Result mismatch.' }
    if ($diag.Count -ne 1 -or -not $diag[0].input_write_denied -or -not $diag[0].serviceaccount_token_absent) { throw 'Guest controls mismatch.' }
    Write-Output "Pod: $($pod.metadata.name), UID: $($pod.metadata.uid), exit: 0"
    Write-Output $logs
    Write-Output 'Windows create/status/result: VERIFIED'
} finally {
    try {
        if ($madeJob) { $null = Request-Kube DELETE "/apis/batch/v1/namespaces/kata-lab/jobs/$run" @{apiVersion='v1';kind='DeleteOptions';propagationPolicy='Foreground'} }
        if ($madeInput) { $null = Request-Kube DELETE "/api/v1/namespaces/kata-lab/configmaps/$run-inputs" }
        if ($madeJob) {
            $deadline = [DateTime]::UtcNow.AddSeconds(60)
            do {
                $remaining = Request-Kube GET "/api/v1/namespaces/kata-lab/pods?labelSelector=kataai-m1-run%3D$run" | ConvertFrom-Json
                if (@($remaining.items).Count -eq 0) { break }
                Start-Sleep -Seconds 2
            } while ([DateTime]::UtcNow -lt $deadline)
            if (@($remaining.items).Count -ne 0) { throw 'Windows cleanup: Pod still present.' }
            Write-Output 'Windows DELETE requests accepted; dependent Pod absent. Confirm Job/ConfigMap absence separately.'
        }
    } finally {
        $token = $null
        if (Test-Path -LiteralPath $bodyPath) { Remove-Item -LiteralPath $bodyPath }
        if ($null -ne $tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id }
    }
}
