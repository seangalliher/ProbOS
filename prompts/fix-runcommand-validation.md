# Fix: run_command Should Verify Command Exists Before Executing

## Problem

The decomposer routes tasks like "create a QR code" to `run_command` with commands like `qr 'https://probos.dev'` — commands that don't exist on the system. The command fails, the user sees an error, and self-mod never triggers because the decomposer thinks `run_command` handled it.

Despite AD-262's prompt hardening (anti-scripting rule, QR gap example), the LLM keeps finding new ways to route to `run_command`. More prompt rules won't fix this — the LLM will always find workarounds.

## Fix: Pre-execution command validation in ShellCommandAgent

**File:** `src/probos/agents/shell_command.py`

Before executing a command, verify that the primary binary/command exists on the system:

```python
import shutil

async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
    if intent.intent not in self._handled_intents:
        return None
    
    command = intent.params.get("command", "").strip()
    if not command:
        return IntentResult(...)
    
    # Extract the primary command (first word, before args)
    primary_cmd = command.split()[0].strip('"').strip("'")
    
    # Skip validation for shell builtins and common utilities
    SHELL_BUILTINS = {
        'echo', 'cd', 'set', 'dir', 'type', 'copy', 'move', 'del',
        'mkdir', 'rmdir', 'cls', 'exit', 'where', 'if', 'for',
        # PowerShell cmdlets
        'Get-Date', 'Get-Process', 'Get-ChildItem', 'Get-Content',
        'Write-Output', 'Write-Host', 'Select-Object', 'Format-Table',
        'Invoke-WebRequest', 'Invoke-RestMethod', 'Test-Path',
        'New-Item', 'Remove-Item', 'Set-Location', 'Get-Location',
        'Measure-Object', 'Sort-Object', 'Where-Object',
        # Common utilities guaranteed to exist
        'powershell', 'cmd', 'python', 'pip', 'git', 'node', 'npm',
        'curl', 'wget', 'tar', 'ssh', 'scp',
    }
    
    # PowerShell cmdlets are always available (they contain a hyphen)
    if '-' in primary_cmd:
        pass  # PowerShell cmdlet — always valid
    elif primary_cmd.lower() in {b.lower() for b in SHELL_BUILTINS}:
        pass  # Known builtin — always valid
    elif shutil.which(primary_cmd) is None:
        # Command not found on the system
        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=False,
            error=f"Command '{primary_cmd}' not found on this system. This task may need a dedicated agent — try asking ProbOS to build one.",
            confidence=self.confidence,
        )
    
    # Command exists — proceed with normal execution
    ...
```

This way:
- `Get-Date` → PowerShell cmdlet, executes normally ✅
- `python -m ...` → found via `shutil.which`, executes normally ✅  
- `qr 'https://...'` → `shutil.which('qr')` returns None → returns error suggesting self-mod ✅
- The error message hints the user should ask ProbOS to build an agent

## Also: Failed run_command should suggest self-mod

**File:** `src/probos/api.py` or `src/probos/runtime.py`

When a DAG execution completes with a `run_command` failure that says "Command not found", the response should suggest self-mod:

Instead of just showing the error, add: "I couldn't find that command. Would you like me to build an agent for this? Try: 'Build me an agent that can create QR codes'"

## After fix

1. Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
2. Test: "Create a QR code for probos.dev" → should fail `run_command` gracefully with "command not found" message suggesting self-mod, NOT a raw shell error
3. Test: "What time is it?" → should still work (Get-Date is a valid PowerShell cmdlet)
4. Test: "List files in current directory" → should still work (Get-ChildItem is valid)
