# 09 - Testing Your Agent

This guide covers how to test your agent locally before submitting to the benchmark.

---

## Why Test Locally?

1. **Faster feedback** - No waiting for benchmark queue
2. **Easier debugging** - Full access to logs and state
3. **Cost savings** - Fewer wasted LLM calls
4. **Iteration speed** - Quick fix-test cycles

---

## Basic Testing Setup

### Minimal Test Script

```python
#!/usr/bin/env python3
"""test_agent.py - Basic agent testing"""

from my_agent import MyAgent

def test_basic():
    """Test agent initialization and basic functionality."""
    agent = MyAgent()
    
    # Test setup
    agent.setup()
    print("Setup: OK")
    
    # Test cleanup
    agent.cleanup()
    print("Cleanup: OK")

def test_simple_task():
    """Test a simple task."""
    # Any est duck-typed (a shell(), cwd, instruction, done())
    
    agent = MyAgent()
    agent.setup()
    
    # Create mock context
    ctx = Any(instruction="List all files in the current directory")
    
    # Run agent
    agent.run(ctx)
    
    print(f"Steps: {ctx.step}")
    print(f"Done: {ctx.is_done}")
    
    agent.cleanup()

if __name__ == "__main__":
    test_basic()
    test_simple_task()
```

### Running Tests

```bash
# Run basic test
python test_agent.py

# Run with verbose output
python -u test_agent.py 2>&1 | tee test.log

# Run in mock mode (no gateway URL or token needed)
BASEAGENT_MOCK_LLM=1 python test_agent.py
```

---

## Using the SDK Test Harness

### Single Task Test

```bash
# Test against a single task
term bench agent -a ./my_agent.py -t ./tasks/simple-task

# With verbose output
term bench agent -a ./my_agent.py -t ./tasks/simple-task --verbose

# With specific timeout
term bench agent -a ./my_agent.py -t ./tasks/simple-task --timeout 300
```

### Multiple Tasks

```bash
# Test against multiple tasks
term bench agent -a ./my_agent.py -t ./tasks/task1 ./tasks/task2

# Test against a task directory
term bench agent -a ./my_agent.py -t ./tasks/

# With parallel execution
term bench agent -a ./my_agent.py -t ./tasks/ --parallel 4
```

---

## Creating Test Tasks

### Task Directory Structure

```
my-test-task/
├── task.yaml       # Task definition
├── setup/          # Initial files (optional)
│   └── ...
└── expected/       # Expected outputs (for manual verification)
    └── ...
```

### Task Definition (task.yaml)

```yaml
name: my-test-task
description: A simple test task
instruction: |
  Create a file named hello.txt containing "Hello, World!"

timeout: 60
max_steps: 50

# Optional: files to create before running
setup_files:
  - path: README.md
    content: |
      # Test Project
      This is a test project.

# Optional: environment variables
environment:
  DEBUG: "1"
```

### Simple Test Task Example

```yaml
# tasks/create-file/task.yaml
name: create-file
description: Test basic file creation
instruction: Create a file named output.txt containing the text "test passed"
timeout: 30
max_steps: 10
```

### Complex Test Task Example

```yaml
# tasks/fix-python/task.yaml
name: fix-python
description: Test Python debugging
instruction: |
  The file main.py has a syntax error. Fix it so it runs correctly.
  The program should print "Hello, World!" when executed.

timeout: 120
max_steps: 30

setup_files:
  - path: main.py
    content: |
      def main()
          print("Hello, World!")
      
      if __name__ == "__main__":
          main()
```

---

## Mock Testing

### Mock LLM for Fast Tests

```python
class MockLLM:
    """Mock LLM for testing without API calls."""
    
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.call_count = 0
    
    def ask(self, prompt: str, **kwargs) -> MockResponse:
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return MockResponse(response)
        return MockResponse('{"task_complete": true}')
    
    def chat(self, messages: list, **kwargs) -> MockResponse:
        return self.ask(messages[-1]["content"])

class MockResponse:
    def __init__(self, text: str):
        self.text = text
    
    def json(self):
        import json
        try:
            return json.loads(self.text)
        except:
            return None

# Usage
def test_with_mock():
    mock_llm = MockLLM([
        '{"analysis": "Need to list files", "commands": [{"command": "ls -la"}]}',
        '{"analysis": "Found files", "task_complete": true}'
    ])
    
    agent = MyAgent()
    agent.llm = mock_llm  # Inject mock
    agent.setup()
    
    # Run test...
```

### Mock Shell for Isolated Tests

```python
class MockShell:
    """Mock shell for testing without actual execution."""
    
    def __init__(self):
        self.commands = []
        self.responses = {}
    
    def add_response(self, pattern: str, output: str, exit_code: int = 0):
        self.responses[pattern] = (output, exit_code)
    
    def __call__(self, command: str, **kwargs) -> MockShellResult:
        self.commands.append(command)
        
        for pattern, (output, code) in self.responses.items():
            if pattern in command:
                return MockShellResult(command, output, code)
        
        return MockShellResult(command, "", 0)

class MockShellResult:
    def __init__(self, command: str, output: str, exit_code: int):
        self.command = command
        self.stdout = output
        self.stderr = ""
        self.output = output
        self.exit_code = exit_code
        self.ok = exit_code == 0
        self.failed = exit_code != 0
        self.timed_out = False

# Usage
mock_shell = MockShell()
mock_shell.add_response("ls", "file1.txt\nfile2.txt\n")
mock_shell.add_response("cat", "file contents")
```

---

## Debugging Techniques

### Verbose Logging

```python
import os

DEBUG = os.environ.get("DEBUG", "0") == "1"

def debug_log(msg: str):
    if DEBUG:
        print(f"[DEBUG] {msg}", flush=True)

class MyAgent(Agent):
    def run(self, ctx: Any):
        debug_log(f"Starting task: {ctx.instruction}")
        
        # ... agent logic ...
        
        debug_log(f"LLM response: {response.text[:200]}")
        debug_log(f"Parsed data: {data}")
```

### State Inspection

```python
class DebuggableAgent(Agent):
    def __init__(self):
        self.state_history = []
    
    def save_state(self, label: str):
        state = {
            "label": label,
            "step": self.ctx.step,
            "history_length": len(self.messages),
            "last_command": self.last_command,
            "last_output": self.last_output[:500] if self.last_output else None
        }
        self.state_history.append(state)
    
    def dump_history(self):
        for state in self.state_history:
            print(f"[{state['label']}] Step {state['step']}")
            print(f"  History: {state['history_length']} messages")
            if state.get('last_command'):
                print(f"  Command: {state['last_command'][:80]}")
```

### Conversation Logging

```python
class ConversationLogger:
    def __init__(self, filepath: str = "conversation.log"):
        self.filepath = filepath
        self.fp = open(filepath, "w")
    
    def log_message(self, role: str, content: str):
        self.fp.write(f"\n{'='*60}\n")
        self.fp.write(f"[{role.upper()}]\n")
        self.fp.write(f"{content}\n")
        self.fp.flush()
    
    def close(self):
        self.fp.close()

# Usage
logger = ConversationLogger()

for msg in messages:
    logger.log_message(msg["role"], msg["content"])

response = llm.chat(messages)
logger.log_message("assistant", response.text)
```

---

## Test Checklist

Before submitting, verify these items:

### 1. Basic Functionality

```bash
# Does it start?
python -c "from my_agent import MyAgent; a = MyAgent(); a.setup(); a.cleanup()"

# Does it handle empty tasks?
# (Create a task with minimal instruction)

# Does it terminate?
# (Ensure # Task complete is always called)
```

### 2. Error Handling

```python
def test_error_handling():
    """Test that agent handles errors gracefully."""
    
    agent = MyAgent()
    agent.setup()
    
    # Test invalid command
    ctx = Any(instruction="Run the command: nonexistent_command_xyz")
    agent.run(ctx)
    assert ctx.is_done, "Agent should complete even with errors"
    
    agent.cleanup()
```

### 3. Context Management

```python
def test_long_task():
    """Test that agent handles long tasks without context overflow."""
    
    agent = MyAgent()
    agent.setup()
    
    # Task that generates lots of output
    ctx = Any(instruction="List all files recursively and show their contents")
    agent.run(ctx)
    
    assert ctx.is_done
    assert ctx.step < 100, "Should complete in reasonable steps"
    
    agent.cleanup()
```

### 4. Output Verification

```python
def test_output_files():
    """Test that agent creates expected output files."""
    import os
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        os.chdir(tmpdir)
        
        agent = MyAgent()
        agent.setup()
        
        ctx = Any(instruction="Create a file named result.txt with content 'success'")
        agent.run(ctx)
        
        assert os.path.exists("result.txt"), "Output file should exist"
        with open("result.txt") as f:
            assert "success" in f.read(), "Output should contain expected content"
        
        agent.cleanup()
```

---

## Automated Test Suite

### pytest Setup

```python
# tests/test_agent.py
import pytest
from my_agent import MyAgent

@pytest.fixture
def agent():
    a = MyAgent()
    a.setup()
    yield a
    a.cleanup()

def test_setup_cleanup(agent):
    """Agent initializes and cleans up correctly."""
    assert agent is not None

def test_simple_task(agent, tmp_path):
    """Agent completes simple task."""
    import os
    os.chdir(tmp_path)
    
    ctx = Any(instruction="Create hello.txt")
    agent.run(ctx)
    
    assert ctx.is_done

@pytest.mark.parametrize("instruction", [
    "List files",
    "Show current directory",
    "Create a file",
])
def test_various_tasks(agent, tmp_path, instruction):
    """Agent handles various task types."""
    import os
    os.chdir(tmp_path)
    
    ctx = Any(instruction=instruction)
    agent.run(ctx)
    
    assert ctx.is_done
```

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with verbose output
pytest tests/ -v

# Run specific test
pytest tests/test_agent.py::test_simple_task

# Run with coverage
pytest tests/ --cov=my_agent
```

---

## Pre-Submission Checklist

```markdown
## Before Submitting

### Code Quality
- [ ] No syntax errors
- [ ] No import errors
- [ ] Passes basic smoke test

### Functionality
- [ ] Completes simple tasks
- [ ] Handles errors gracefully
- [ ] Always calls # Task complete
- [ ] Manages context size

### Performance
- [ ] Completes tasks in reasonable time
- [ ] Doesn't exceed step limits
- [ ] Manages LLM costs

### Compliance
- [ ] No hardcoded task solutions
- [ ] No pattern matching on instructions
- [ ] No test file access
- [ ] Uses LLM for all decisions
```

---

## Summary

| Testing Phase | Purpose |
|---------------|---------|
| Unit tests | Verify components work |
| Mock tests | Fast iteration |
| Integration tests | Full agent flow |
| Task tests | Real task execution |
| Stress tests | Edge cases and limits |
