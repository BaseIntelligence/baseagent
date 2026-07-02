# Cost Optimization - Reduce API Costs

## Cost Breakdown

Typical LLM pricing (varies by model):

| Token Type | Typical Cost per 1M |
|------------|---------------------|
| Input tokens | $1.00 - $15.00 |
| Cached input | 10-50% of input |
| Output tokens | $2.00 - $60.00 |

For a typical task:
- 50 turns
- 100k context average
- 500 output tokens per turn

For challenge runs, BaseAgent calls the platform LLM gateway, which picks the provider and model.

## Optimization Strategies

### 1. Prompt Caching (Biggest Win)

See [01-prompt-caching.md](01-prompt-caching.md) for details.

**Impact**: 80-90% reduction in input costs

### 2. Context Management

See [03-context-management.md](03-context-management.md) for details.

**Impact**: Prevents context overflow, reduces average context size

### 3. Efficient Tool Design

```python
# Bad: Returns too much
def list_files(path: str) -> str:
    return subprocess.run(f"find {path}", capture_output=True).stdout

# Good: Limited output
def list_files(path: str, max_depth: int = 2, limit: int = 100) -> str:
    result = subprocess.run(
        f"find {path} -maxdepth {max_depth} | head -{limit}",
        capture_output=True
    )
    return result.stdout
```

### 4. Avoid Redundant Operations

```python
# Bad: Re-reading files after writing
def write_and_verify(path: str, content: str):
    write_file(path, content)
    verify = read_file(path)  # Unnecessary!
    return verify == content

# Good: Trust the write operation
def write_file(path: str, content: str):
    with open(path, 'w') as f:
        f.write(content)
    return f"Wrote {len(content)} bytes to {path}"
```

### 5. Smart Search

```python
# Bad: Broad search
def find_function(name: str):
    return grep(f"def {name}", path=".")  # Searches everything

# Good: Targeted search
def find_function(name: str, file_pattern: str = "*.py"):
    return grep(f"def {name}", path=".", include=file_pattern)
```

### 6. Batch Operations

```python
# Bad: Multiple tool calls
result1 = read_file("file1.py")
result2 = read_file("file2.py")
result3 = read_file("file3.py")

# Good: Single combined operation
def read_multiple_files(paths: List[str]) -> Dict[str, str]:
    return {path: read_file(path) for path in paths}
```

### 7. Early Exit

```python
# Bad: Always run full test suite
def verify_changes():
    return run("pytest")  # Runs all tests

# Good: Run targeted tests first
def verify_changes(changed_files: List[str]):
    # Find related tests
    test_files = find_tests_for(changed_files)
    
    # Run only those
    result = run(f"pytest {' '.join(test_files)}")
    
    if result.failed:
        return result  # Early exit
    
    # Only run full suite if targeted tests pass
    return run("pytest")
```

## Monitoring Costs

Track these metrics per task:

```python
@dataclass
class TaskMetrics:
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    turns: int = 0
    
    @property
    def cache_hit_rate(self) -> float:
        if self.input_tokens == 0:
            return 0
        return self.cached_tokens / self.input_tokens
    
    @property
    def estimated_cost(self) -> float:
        uncached = self.input_tokens - self.cached_tokens
        return (
            uncached * 3.00 / 1_000_000 +
            self.cached_tokens * 0.30 / 1_000_000 +
            self.output_tokens * 15.00 / 1_000_000
        )
```

## Cost Budgets

Set limits to prevent runaway costs:

```python
MAX_COST_PER_TASK = 10.00  # $10 max

def check_budget(metrics: TaskMetrics) -> bool:
    if metrics.estimated_cost > MAX_COST_PER_TASK:
        raise CostLimitExceeded(
            f"Task exceeded ${MAX_COST_PER_TASK} budget"
        )
    return True
```

## Quick Wins Checklist

- [ ] Enable prompt caching on system + last 2 messages
- [ ] Truncate tool outputs to 50KB max
- [ ] Prune old tool results from context
- [ ] Use targeted grep instead of broad search
- [ ] Limit directory listings (depth=2, limit=100)
- [ ] Don't re-read files after writing
- [ ] Run specific tests before full suite
- [ ] Set cost limit per task

## Cost vs Quality Tradeoffs

| Optimization | Cost Saving | Quality Impact |
|--------------|-------------|----------------|
| Prompt caching | 90% input | None |
| Output truncation | 20-40% | Slight (middle content lost) |
| Context pruning | 30-50% | Slight (old context lost) |
| Smaller model | 80%+ | Significant |
| Fewer retries | Variable | May reduce success rate |

**Recommendation**: Focus on caching and truncation first. These give big savings with minimal quality impact.
