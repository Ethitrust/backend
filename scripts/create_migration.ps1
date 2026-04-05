Get-ChildItem components -Directory | ForEach-Object {
    Push-Location $_.FullName
    $env:DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ethitrust_$($_.Name)"
    alembic revision --autogenerate -m "Initial tables"
    Pop-Location
}