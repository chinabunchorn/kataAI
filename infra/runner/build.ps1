param([Parameter(Mandatory=$true)][string]$Repository)
# Build an OCI archive only. Never run the image or execute candidate fixtures.
$ErrorActionPreference = 'Stop'
if ($Repository -notmatch '^[a-zA-Z0-9][a-zA-Z0-9./:_-]*:0\.1\.1$') {
    throw 'Supply a repository tag ending in :0.1.1, with no credentials or shell text.'
}
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$output = Join-Path $root ('.m3-runs/build-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
$null = New-Item -ItemType Directory -Path $output
$archive = Join-Path $output 'runner.oci.tar'
$metadata = Join-Path $output 'build-metadata.json'
$sourceFiles = @('Dockerfile','__init__.py','contract.py','validation.py','staging.py','report.py','scratch.py','supervisor.py','entrypoint.py','job.py','collection.py','.dockerignore','requirements.txt','build.ps1','verify_artifact.py')
$hashes = [ordered]@{}
foreach ($name in $sourceFiles) {
    $hashes[$name] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $PSScriptRoot $name)).Hash.ToLowerInvariant()
}
$sourceRevision = (& git -C $root rev-parse HEAD) -join ''
if ($LASTEXITCODE -ne 0) { throw 'Could not record source revision' }
$sourceStatus = @(& git -C $root status --porcelain --untracked-files=all)
if ($LASTEXITCODE -ne 0) { throw 'Could not record worktree status' }
& docker buildx build --platform linux/amd64 --provenance=false --tag $Repository `
    --output "type=oci,dest=$archive" --metadata-file $metadata `
    --file (Join-Path $PSScriptRoot 'Dockerfile') $PSScriptRoot
if ($LASTEXITCODE -ne 0) { throw "Image build failed; partial output retained in $output" }
$inspectionText = & python -B (Join-Path $PSScriptRoot 'verify_artifact.py') $archive
if ($LASTEXITCODE -ne 0) { throw 'OCI archive inspection failed; do not deploy this artifact' }
$inspection = ($inspectionText -join [Environment]::NewLine) | ConvertFrom-Json
[IO.File]::WriteAllText((Join-Path $output 'inspection.json'), ($inspection | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
if ((Get-Item -LiteralPath $metadata).Length -gt 1MB) { throw 'Unexpected build metadata size' }
$build = Get-Content -Raw -LiteralPath $metadata | ConvertFrom-Json
$digest = $build.'containerimage.digest'
if ($digest -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Build did not return an immutable manifest digest' }
if ($inspection.manifest_digest -ne $digest) { throw 'Build metadata and inspected manifest digest differ' }
foreach ($name in $sourceFiles) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $PSScriptRoot $name)).Hash.ToLowerInvariant() -ne $hashes[$name]) {
        throw "Source changed during build: $name; discard candidate and rebuild"
    }
}
$finalRevision = (& git -C $root rev-parse HEAD) -join ''
if ($LASTEXITCODE -ne 0 -or $finalRevision -ne $sourceRevision) { throw 'Source revision changed during build' }
$version = (& docker buildx version) -join ''
if ($LASTEXITCODE -ne 0) { throw 'Could not record builder version' }
$record = [ordered]@{
    runner_version='0.1.1'; platform='linux/amd64'; built_at=[DateTime]::UtcNow.ToString('o')
    source_revision=$sourceRevision; source_worktree_status=$sourceStatus; source_sha256=$hashes; builder=$version
    artifact_inspection=$inspection
    base_image='docker.io/library/python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b'
    base_python_metadata='3.12.16'; base_os_metadata='Debian trixie'
    image=($Repository -replace ':0\.1\.1$','') + '@' + $digest
    archive_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    build_command='docker buildx build --platform linux/amd64 --provenance=false --tag <repository>:0.1.1 --output type=oci,dest=<archive> --metadata-file <metadata> --file infra/runner/Dockerfile infra/runner'
    candidate_execution_performed=$false
    live_kata_acceptance_verified=$false
}
[IO.File]::WriteAllText((Join-Path $output 'release.json'), ($record | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
Write-Output "OCI archive and release record: $output"
Write-Output "Immutable runner reference: $($record.image)"
Write-Output 'Image distribution/import and actual Kata acceptance remain separate steps.'
