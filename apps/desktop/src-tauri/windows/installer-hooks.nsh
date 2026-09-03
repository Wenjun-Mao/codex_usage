!macro NSIS_HOOK_PREUNINSTALL
  DetailPrint "Stopping and unregistering the Codex Usage background collector..."
  nsExec::ExecToLog '"$INSTDIR\codex-usage-agent.exe" --uninstall-service'

  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 \
    "Remove the Codex Usage ledger and settings?$\r$\n$\r$\nChoose No to preserve them for a future reinstall." \
    IDNO preserve_local_data

  DetailPrint "Removing Codex Usage ledger and settings..."
  nsExec::ExecToLog '"$INSTDIR\codex-usage-agent.exe" --reset-local-data --remove-settings'

  preserve_local_data:
!macroend
