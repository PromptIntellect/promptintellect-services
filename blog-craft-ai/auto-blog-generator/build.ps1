# Define the name of the zip file
$zipFileName = "lambda_function.zip"

# Install node modules
npm install

# Define the full path to the zip file
$zipFilePath = Join-Path -Path (Get-Location) -ChildPath $zipFileName

# Remove the existing zip file if it exists
if (Test-Path -Path $zipFilePath) {
    Remove-Item -Path $zipFilePath
}

# Compress the project files into a zip file
Add-Type -AssemblyName "System.IO.Compression.FileSystem"
[System.IO.Compression.ZipFile]::CreateFromDirectory((Get-Location).Path, $zipFilePath)

Write-Output "Zip file created at $zipFilePath"
