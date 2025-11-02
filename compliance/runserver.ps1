# ============================
# runserver.ps1 - Start Flask Server
# ============================

Write-Host "Starting Compliance Flask App..." -ForegroundColor Cyan

# Step 1: Move to script directory (project root)
Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Definition)

# Step 2: Activate the virtual environment
Write-Host "Activating virtual environment..."
& .\.venv\Scripts\Activate.ps1

# Step 3: Set environment variables for Flask
Write-Host "⚙ Setting environment variables..."
$env:FLASK_APP="__init__:create_app"
$env:FLASK_DEBUG="1"

# Optional: Clear the console for a clean run
Clear-Host

# Step 4: Run the Flask development server
Write-Host "Flask development server starting at http://127.0.0.1:5000" -ForegroundColor Green
python -m flask run
