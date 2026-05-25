# 08 - Error Handling

This guide covers strategies for handling errors gracefully in generalist agents.

---

## Error Categories

### 1. LLM Errors

Errors from the language model API:

| Error | Cause | Recovery |
|-------|-------|----------|
| `rate_limit` | Too many requests | Wait and retry with backoff |
| `context_length` | Context too long | Truncate history and retry |
| `server_error` | Provider issue | Wait and retry |
| `cost_limit` | Budget exceeded | Stop gracefully |
| `invalid_response` | Malformed output | Ask for retry |

### 2. Command Errors

Errors from shell execution:

| Error | Cause | Recovery |
|-------|-------|----------|
| Non-zero exit | Command failed | Analyze and fix |
| Timeout | Command hung | Increase timeout or kill |
| Permission denied | Access issue | Try sudo or fix permissions |
| Not found | Missing command/file | Install or create |

### 3. Parse Errors

Errors parsing LLM responses:

| Error | Cause | Recovery |
|-------|-------|----------|
| Invalid JSON | Malformed response | Ask for valid JSON |
| Missing fields | Incomplete response | Ask for complete response |
| Wrong type | Unexpected data type | Provide format example |

---

## LLM Error Handling

### Comprehensive Handler

```python
import time
from src.llm.client import LLMClient, LLMError, CostLimitExceeded

class RobustLLMClient:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.llm = LLMClient(model="deepseek-v4-pro")
        self.max_retries = 3
        self.base_delay = 5
    
    def chat(self, messages: list) -> Response | None:
        """Chat with retry logic."""
        
        for attempt in range(self.max_retries):
            try:
                return self.llm.chat(messages)
            
            except CostLimitExceeded as e:
                self.print(f"FATAL: Cost limit exceeded (${e.used:.2f}/${e.limit:.2f})")
                return None  # Can't recover
            
            except LLMError as e:
                self.print(f"LLM error (attempt {attempt + 1}): {e.code} - {e.message}")
                
                if not self._should_retry(e, attempt):
                    return None
                
                delay = self._get_delay(e, attempt)
                self.print(f"Retrying in {delay}s...")
                time.sleep(delay)
                
                # Apply recovery action
                messages = self._apply_recovery(e, messages)
        
        self.print("Max retries exceeded")
        return None
    
    def _should_retry(self, error: LLMError, attempt: int) -> bool:
        """Determine if we should retry this error."""
        retryable = {"rate_limit", "server_error", "service_unavailable", "context_length"}
        return error.code in retryable and attempt < self.max_retries - 1
    
    def _get_delay(self, error: LLMError, attempt: int) -> int:
        """Calculate retry delay with exponential backoff."""
        if error.code == "rate_limit":
            return min(60, self.base_delay * (2 ** attempt) * 3)  # Longer for rate limits
        return self.base_delay * (2 ** attempt)
    
    def _apply_recovery(self, error: LLMError, messages: list) -> list:
        """Apply recovery action for the error type."""
        if error.code == "context_length":
            return self._truncate_messages(messages)
        return messages
    
    def _truncate_messages(self, messages: list) -> list:
        """Truncate messages to reduce context."""
        if len(messages) <= 3:
            # Can't truncate further, try truncating content
            return [
                {**m, "content": m["content"][:5000]}
                for m in messages
            ]
        
        # Keep system + first user + last N messages
        system = messages[0] if messages[0]["role"] == "system" else None
        result = messages[-6:]  # Keep last 6
        
        if system and result[0] != system:
            result.insert(0, system)
        
        return result
```

---

## Command Error Handling

### Shell Execution with Recovery

```python
class CommandExecutor:
    def __init__(self, ctx: Any, llm: RobustLLMClient):
        self.ctx = ctx
        self.llm = llm
    
    def execute(
        self,
        command: str,
        timeout: int = 30,
        max_retries: int = 2,
        allow_llm_recovery: bool = True
    ) -> ShellResult:
        """Execute command with error recovery."""
        
        for attempt in range(max_retries + 1):
            result = self.shell(command, timeout=timeout)
            
            if result.ok:
                return result
            
            self.print(f"Command failed (attempt {attempt + 1}): exit {result.exit_code}")
            
            # Check for recoverable errors
            recovery = self._try_recovery(result, attempt, allow_llm_recovery)
            
            if recovery is None:
                # No recovery possible
                break
            
            if recovery.get("retry_same"):
                # Just retry the same command
                time.sleep(recovery.get("delay", 1))
                continue
            
            if recovery.get("new_command"):
                # Try a different command
                command = recovery["new_command"]
                continue
        
        return result
    
    def _try_recovery(self, result: ShellResult, attempt: int, allow_llm: bool) -> dict | None:
        """Attempt to recover from command failure."""
        
        error_lower = result.output.lower()
        
        # Transient network errors - retry
        if any(x in error_lower for x in ["connection refused", "connection reset", "timeout"]):
            return {"retry_same": True, "delay": 5 * (attempt + 1)}
        
        # Permission denied - try sudo
        if "permission denied" in error_lower:
            if not result.command.startswith("sudo "):
                return {"new_command": f"sudo {result.command}"}
        
        # Command not found - try installing
        if "command not found" in error_lower or "not found" in error_lower:
            cmd_name = self._extract_command_name(result.command)
            if cmd_name:
                install_result = self._try_install(cmd_name)
                if install_result.ok:
                    return {"retry_same": True, "delay": 1}
        
        # Let LLM suggest recovery
        if allow_llm and attempt < 2:
            return self._llm_recovery(result)
        
        return None
    
    def _extract_command_name(self, command: str) -> str | None:
        """Extract the main command name."""
        parts = command.strip().split()
        if parts:
            return parts[0]
        return None
    
    def _try_install(self, cmd_name: str) -> ShellResult:
        """Try to install a missing command."""
        # Common package managers
        installers = [
            f"apt-get install -y {cmd_name}",
            f"yum install -y {cmd_name}",
            f"pip install {cmd_name}",
            f"npm install -g {cmd_name}",
        ]
        
        for installer in installers:
            result = self.shell(installer, timeout=60)
            if result.ok:
                return result
        
        return result  # Return last attempt
    
    def _llm_recovery(self, result: ShellResult) -> dict | None:
        """Ask LLM for recovery suggestion."""
        response = self.llm.chat([
            {"role": "system", "content": "You are a Linux troubleshooting assistant."},
            {"role": "user", "content": f"""Command failed:
$ {result.command}
Exit code: {result.exit_code}
Output: {result.output[-2000:]}

Suggest ONE recovery command, or say "no_recovery" if not fixable.
Respond with JSON: {{"recovery_command": "..."}} or {{"no_recovery": true}}"""}
        ])
        
        if not response:
            return None
        
        data = parse_json(response.text)
        if data and data.get("recovery_command"):
            return {"new_command": data["recovery_command"]}
        
        return None
```

---

## Parse Error Handling

### Robust JSON Parsing

```python
class ResponseParser:
    def __init__(self, ctx: Any, llm: RobustLLMClient):
        self.ctx = ctx
        self.llm = llm
    
    def parse(self, response_text: str, required_fields: list = None) -> dict | None:
        """Parse LLM response with error handling."""
        
        # Try standard parsing
        data = self._try_parse(response_text)
        
        if data:
            # Validate required fields
            if required_fields:
                missing = [f for f in required_fields if f not in data]
                if missing:
                    self.print(f"Missing required fields: {missing}")
                    return None
            return data
        
        return None
    
    def _try_parse(self, text: str) -> dict | None:
        """Try various parsing strategies."""
        
        # Strategy 1: Direct parse
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        
        # Strategy 2: Extract JSON from markdown code blocks
        # Pattern: triple backticks, optional "json", content, triple backticks
        code_block_pattern = r'`{3}(?:json)?\s*([\s\S]*?)`{3}'
        json_match = re.search(code_block_pattern, text)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass
        
        # Strategy 3: Extract JSON object
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        # Strategy 4: Fix common issues
        fixed = self._fix_json(text)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
        
        return None
    
    def _fix_json(self, text: str) -> str:
        """Attempt to fix common JSON issues."""
        # Extract potential JSON
        match = re.search(r'\{[\s\S]*\}', text)
        if not match:
            return text
        
        json_str = match.group()
        
        # Fix trailing commas
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        
        # Fix missing quotes on keys
        json_str = re.sub(r'(\{|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', json_str)
        
        return json_str
    
    def parse_with_retry(
        self,
        messages: list,
        required_fields: list = None,
        max_attempts: int = 3
    ) -> tuple[dict | None, list]:
        """Parse response, retrying with LLM if needed."""
        
        for attempt in range(max_attempts):
            response = self.llm.chat(messages)
            if not response:
                return None, messages
            
            data = self.parse(response.text, required_fields)
            
            if data:
                messages.append({"role": "assistant", "content": response.text})
                return data, messages
            
            # Ask for valid JSON
            self.print(f"Parse failed (attempt {attempt + 1}), requesting valid JSON")
            
            messages.append({"role": "assistant", "content": response.text})
            messages.append({
                "role": "user",
                "content": f"Invalid JSON response. Please respond with ONLY valid JSON containing these fields: {required_fields}"
            })
        
        return None, messages
```

---

## Graceful Degradation

### Fallback Strategies

```python
class FallbackExecutor:
    def __init__(self, ctx: Any):
        self.ctx = ctx
    
    def execute_with_fallbacks(self, primary: str, fallbacks: list[str]) -> ShellResult:
        """Try primary command, then fallbacks if it fails."""
        
        result = self.shell(primary)
        if result.ok:
            return result
        
        self.print(f"Primary command failed, trying fallbacks")
        
        for i, fallback in enumerate(fallbacks):
            self.print(f"Trying fallback {i + 1}: {fallback[:50]}...")
            result = self.shell(fallback)
            if result.ok:
                return result
        
        return result  # Return last result
    
    def find_tool(self, tool_name: str, alternatives: list[str]) -> str | None:
        """Find an available tool from alternatives."""
        
        for tool in [tool_name] + alternatives:
            result = self.shell(f"which {tool}")
            if result.ok:
                return tool
        
        return None

# Usage
executor = FallbackExecutor(ctx)

# Try python3, then python, then python2
python = executor.find_tool("python3", ["python", "python2"])
if python:
    shell(f"{python} script.py")

# Try primary approach with fallbacks
result = executor.execute_with_fallbacks(
    "npm run build",
    ["yarn build", "pnpm build", "node build.js"]
)
```

---

## Error Logging

### Structured Error Logging

```python
class ErrorLogger:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self.errors = []
    
    def log_error(self, category: str, message: str, details: dict = None):
        """Log an error with context."""
        error = {
            "category": category,
            "message": message,
            "details": details or {},
            "step": self.ctx.step,
            "timestamp": time.time()
        }
        
        self.errors.append(error)
        self.print(f"[{category}] {message}")
        
        if details:
            for key, value in details.items():
                self.print(f"  {key}: {str(value)[:200]}")
    
    def get_summary(self) -> str:
        """Get error summary for debugging."""
        if not self.errors:
            return "No errors recorded"
        
        summary = [f"Total errors: {len(self.errors)}"]
        
        by_category = {}
        for e in self.errors:
            cat = e["category"]
            by_category[cat] = by_category.get(cat, 0) + 1
        
        for cat, count in by_category.items():
            summary.append(f"  {cat}: {count}")
        
        return "\n".join(summary)
```

---

## Complete Error Handling Example

```python
class ResilientAgent(Agent):
    def setup(self):
        self.llm_client = RobustLLMClient(self.ctx)
        self.executor = CommandExecutor(self.ctx, self.llm_client)
        self.parser = ResponseParser(self.ctx, self.llm_client)
        self.errors = ErrorLogger(self.ctx)
    
    def run(self, ctx: Any):
        self.ctx = ctx
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Task: {ctx.instruction}"}
        ]
        
        max_iterations = 50
        for iteration in range(max_iterations):
            print(f"Iteration {iteration + 1}")
            
            # Get LLM response with retry
            data, messages = self.parser.parse_with_retry(
                messages,
                required_fields=["commands"]
            )
            
            if not data:
                self.errors.log_error("LLM", "Failed to get valid response")
                continue
            
            if data.get("task_complete"):
                print("Task complete")
                break
            
            # Execute commands with recovery
            for cmd in data.get("commands", []):
                result = self.executor.execute(
                    cmd.get("command", ""),
                    timeout=cmd.get("timeout", 30)
                )
                
                if result.failed:
                    self.errors.log_error(
                        "COMMAND",
                        f"Command failed: {cmd.get('command', '')[:50]}",
                        {"exit_code": result.exit_code, "output": result.output[-500:]}
                    )
                
                # Add output to conversation
                messages.append({
                    "role": "user",
                    "content": f"Output:\n{result.output[-3000:]}"
                })
        
        print(self.errors.get_summary())
        # Task complete
```

---

## Summary

| Error Type | Strategy |
|------------|----------|
| Rate limit | Exponential backoff |
| Context overflow | Truncate history |
| Parse failure | Retry with format hint |
| Command failure | LLM-assisted recovery |
| Missing tool | Try alternatives |
| Permission denied | Try sudo |
| Transient errors | Simple retry |
| Fatal errors | Log and stop gracefully |
