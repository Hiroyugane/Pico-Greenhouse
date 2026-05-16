# â”€â”€ .vscode/micropico-port.ps1 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Helper functions for tasks.json: release and re-acquire the serial
# port held by the MicroPico VS Code extension (paulober.pico-w-go).
#
# Dot-source in any task command that calls mpremote:
#   . .vscode\micropico-port.ps1; Disconnect-MicroPico; mpremote ...; Connect-MicroPico
#
# HOW IT WORKS
#   Uses Windows SendKeys to drive VS Code's Command Palette
#   (Ctrl+Shift+P â†’ type command name â†’ Enter).
#
# REQUIREMENTS
#   â€¢ Windows (System.Windows.Forms + WScript.Shell)
#   â€¢ VS Code must be running and focus-able (not minimised)
#   â€¢ MicroPico extension installed
#
# If VS Code cannot be focused the functions print a warning and
# continue so mpremote still gets a chance to run.
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

Add-Type -AssemblyName System.Windows.Forms

function Invoke-VscPalette([string]$Label) {
    <#
    .SYNOPSIS Open Command Palette, type a command label, press Enter.
    #>
    $wsh = New-Object -ComObject WScript.Shell

    # Bring VS Code to the foreground
    if (-not $wsh.AppActivate('Visual Studio Code')) {
        Write-Host "!!! Could not focus VS Code - skipping: $Label" -ForegroundColor Yellow
        return
    }
    Start-Sleep -Milliseconds 300

    # Open the Command Palette
    [System.Windows.Forms.SendKeys]::SendWait('^+p')
    Start-Sleep -Milliseconds 800

    # Type the command name (narrows the palette to the exact match)
    [System.Windows.Forms.SendKeys]::SendWait($Label)
    Start-Sleep -Milliseconds 500

    # Execute the selected command
    [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
    Start-Sleep -Seconds 2
}

function Disconnect-MicroPico {
    <#
    .SYNOPSIS Release the serial port held by MicroPico.
    #>
    Write-Host '>>> Disconnecting MicroPico ...' -ForegroundColor Cyan
    Invoke-VscPalette 'MicroPico: Disconnect'
}

function Connect-MicroPico {
    <#
    .SYNOPSIS Re-acquire the serial port for MicroPico.
    #>
    Write-Host '>>> Reconnecting MicroPico ...' -ForegroundColor Cyan
    Invoke-VscPalette 'MicroPico: Connect'
}
