-- AppleScript to run the Slack Nudge Check
-- To convert to .app: Save As > File Format: Application

on run
    set scriptPath to POSIX path of (path to me as string)
    set scriptDir to do shell script "dirname " & quoted form of scriptPath
    
    tell application "Terminal"
        activate
        do script "cd " & quoted form of scriptDir & " && source .venv/bin/activate && echo '==================================' && echo '  Slack Nudge Check' && echo '==================================' && echo '' && PYTHONPATH=src python3 -m src.weekly_slack_recon.realtime_monitor && echo '' && echo 'Done! Check your Slack DMs for the summary.'"
    end tell
end run
