-- AppleScript to run the Slack Reconciliation GUI
-- To convert to .app: Save As > File Format: Application

on run
    set appPath to POSIX path of (path to me)
    set scriptPath to POSIX path of (path to me as string)
    set scriptDir to do shell script "dirname " & quoted form of scriptPath
    
    tell application "Terminal"
        activate
        do script "cd " & quoted form of scriptDir & " && source .venv/bin/activate && PYTHONPATH=src python gui_app.py"
    end tell
end run

