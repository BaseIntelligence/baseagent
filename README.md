<p align="center">
  <h1 align="center">BaseAgent</h1>
  <p align="center"><strong>High-performance autonomous agent for <a href="https://term.challenge">Term Challenge</a></strong></p>
  <p align="center">Fully autonomous with <strong>DeepSeek API</strong>, powered by <strong>deepseek-v4-pro</strong></p>
</p>

---

## Related Projects

| Project | Description |
|---------|-------------|
| [Basilica](https://github.com/one-covenant/basilica) | Secure TEE Container Runtime |
| [DeepSeek API](https://api.deepseek.com) | DeepSeek LLM API |
| [Platform Network](https://github.com/PlatformNetwork/platform) | Platform Network Core |
| [How to Mine on subnet 100 with this Agent](https://www.platform.network/docs) | Mining Documentation |
## Architecture at a Glance

```mermaid
graph TB
    subgraph Basilica["Basilica TEE Container"]
        subgraph TermChallenge["Term Challenge Agent"]
            CLI["agent.py"]
            
            subgraph Core["Core Engine"]
                Loop["Agent Loop"]
                Context["Context Manager"]
                Cache["Prompt Cache"]
            end
            
            subgraph Tools["Tool System"]
                Registry["Tool Registry"]
                Shell["shell_command"]
                Files["read_file / write_file"]
                Search["grep_files / list_dir"]
            end
        end
    end
    
    subgraph LLM["LLM Layer (External)"]
        subgraph DeepSeek["DeepSeek API"]
            Client["DeepSeek API Client"]
            Model["deepseek-v4-pro"]
        end
        
        subgraph BasilicaLLM["Basilica (Soon)"]
            GPUServer["GPU Inference Server"]
            cLLM["cLLM Engine"]
        end
    end
    
    CLI --> Loop
    Loop --> Context
    Loop --> Cache
    Loop --> Client
    Client --> Model
    Loop --> Registry
    Registry --> Shell
    Registry --> Files
    Registry --> Search
    
    style Basilica fill:#1a1a2e,color:#fff
    style TermChallenge fill:#16213e,color:#fff
```

---

## Key Features

- **Fully Autonomous** - No user confirmation required; makes decisions independently
- **LLM-Driven** - All decisions made by the language model, not hardcoded logic
- **Prompt Caching** - 90%+ cache hit rate for significant cost reduction
- **Context Management** - Intelligent pruning and compaction for long tasks
- **Self-Verification** - Automatic validation before task completion
- **DeepSeek API** - challenge runs use `deepseek-v4-pro` through the DeepSeek API

## Challenge API Policy

Challenge API policy: this agent is configured to use only the DeepSeek API for cost reasons. Challenge runs must use DEEPSEEK_API_KEY and the configured DeepSeek model. Do not add or rely on Chutes, OpenRouter, Anthropic, OpenAI, or other provider fallbacks for challenge execution.

---

## Installation

```bash
# Via pyproject.toml
pip install .

# Via requirements.txt
pip install -r requirements.txt
```

## Usage

```bash
export DEEPSEEK_API_KEY="your-token"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export LLM_MODEL="deepseek-v4-pro"
python agent.py --instruction "Your task here..."
```

## Agent-Challenge ZIP Entrypoint

Agent-challenge Harbor runners should import `agent:Agent` from the root `agent.py` file in the submitted ZIP. The same file also remains available for local `--instruction` runs. Harbor execution uses `src/tools/harbor_registry.py` so task tools run through `environment.exec` in the remote task workspace. The default task working directory is `/app`; `/workspace/agent` is treated as the mounted agent artifact, not the task filesystem.

Forward only DeepSeek runtime configuration into Harbor: `DEEPSEEK_API_KEY`, optional `DEEPSEEK_BASE_URL`, optional `LLM_MODEL`, and optional `LLM_COST_LIMIT`. BaseAgent does not use OpenRouter, Anthropic, OpenAI, Chutes, or Harbor as runtime dependencies.

---

## Project Structure

```
baseagent/
├── agent.py                 # Harbor ZIP entrypoint (`agent:Agent`) and local CLI entry point
├── src/
│   ├── core/
│   │   ├── loop.py          # Main agent loop
│   │   └── compaction.py    # Context management
│   ├── llm/
│   │   └── client.py        # LLM client (DeepSeek API)
│   ├── config/
│   │   └── defaults.py      # Configuration
│   ├── tools/               # Tool implementations
│   ├── prompts/
│   │   └── system.py        # System prompt
│   └── output/
│       └── jsonl.py         # JSONL event emission
├── rules/                   # Development guidelines
├── astuces/                 # Implementation techniques
└── docs/                    # Full documentation
```

---

## Agent Loop Workflow

```mermaid
flowchart TB
    Start([Start]) --> Init[Initialize Session]
    Init --> BuildMsg[Build Initial Messages]
    BuildMsg --> GetState[Get Terminal State]
    
    GetState --> LoopStart{Iteration < Max?}
    
    LoopStart -->|Yes| ManageCtx[Manage Context<br/>Prune/Compact if needed]
    ManageCtx --> ApplyCache[Apply Prompt Caching]
    ApplyCache --> CallLLM[Call deepseek-v4-pro]
    
    CallLLM --> HasCalls{Has Tool Calls?}
    
    HasCalls -->|Yes| ExecTools[Execute Tool Calls]
    ExecTools --> AddResults[Add Results to Messages]
    AddResults --> LoopStart
    
    HasCalls -->|No| CheckPending{pending_completion?}
    
    CheckPending -->|No| SetPending[Set pending_completion = true]
    SetPending --> InjectVerify[Inject Verification Prompt]
    InjectVerify --> LoopStart
    
    CheckPending -->|Yes| Complete[Task Complete]
    
    LoopStart -->|No| Timeout[Max Iterations Reached]
    
    Complete --> End([End])
    Timeout --> End
```

---

## Available Tools

```mermaid
flowchart LR
    subgraph ToolRegistry["Tool Registry"]
        direction TB
        
        subgraph FileOps["File Operations"]
            read["read_file<br/>Read with pagination"]
            write["write_file<br/>Create/overwrite files"]
            patch["apply_patch<br/>Apply unified diffs"]
        end
        
        subgraph Search["Search & Navigation"]
            grep["grep_files<br/>Ripgrep search"]
            list["list_dir<br/>Directory listing"]
            search["search_files<br/>Glob patterns"]
        end
        
        subgraph Execution["Execution"]
            shell["shell_command<br/>Run shell commands"]
        end
        
        subgraph Media["Media"]
            image["view_image<br/>Analyze images"]
        end
    end
    
    Agent[Agent Loop] --> ToolRegistry
    ToolRegistry --> Results[Tool Results]
    Results --> Agent
```

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `shell_command` | Execute shell commands | `command`, `timeout_ms` |
| `read_file` | Read files with pagination | `file_path`, `offset`, `limit` |
| `write_file` | Create/overwrite files | `file_path`, `content` |
| `apply_patch` | Apply unified diff patches | `patch` |
| `grep_files` | Search with ripgrep | `pattern`, `path`, `include` |
| `list_dir` | List directory contents | `path`, `recursive`, `depth` |
| `search_files` | Search files by glob pattern | `pattern`, `path` |
| `view_image` | Analyze image files | `file_path` |

---

## Tool Execution Flow

```mermaid
sequenceDiagram
    participant Agent as Agent Loop
    participant Registry as Tool Registry
    participant Tool as Tool Implementation
    participant FS as File System

    Agent->>Registry: execute(tool_name, args)
    Registry->>Registry: Validate arguments
    Registry->>Registry: Check cache
    
    alt Cache Hit
        Registry-->>Agent: Cached ToolResult
    else Cache Miss
        Registry->>Tool: execute(**args)
        Tool->>FS: Perform operation
        FS-->>Tool: Result
        Tool-->>Registry: ToolResult
        Registry->>Registry: Cache result
        Registry-->>Agent: ToolResult
    end
```

---

## LLM Client (DeepSeek API)

```python
from src.llm.client import LLMClient

llm = LLMClient(
    model="deepseek-v4-pro",
    temperature=1.0,
    max_tokens=16384,
)

response = llm.chat(messages, tools=tool_specs)
```

### Reasoning Responses

DeepSeek handles complex reasoning through `deepseek-v4-pro`:

```mermaid
sequenceDiagram
    participant User
    participant Model as deepseek-v4-pro
    participant Response

    User->>Model: Complex task instruction
    
    rect rgb(230, 240, 255)
        Note over Model: Reasoning Active
        Model->>Model: Analyze problem
        Model->>Model: Consider approaches
        Model->>Model: Evaluate options
    end
    
    Model->>Response: <think>Reasoning process...</think>
    Model->>Response: Final answer/action
```

---

## Context Management

```mermaid
flowchart LR
    subgraph Input
        Msgs[Messages<br/>~150K tokens]
    end
    
    subgraph Detection
        Est[Estimate Tokens]
        Check{> 85% of<br/>context?}
    end
    
    subgraph Pruning
        Scan[Scan backwards]
        Protect[Protect last 40K<br/>tool tokens]
        Clear[Clear old outputs]
    end
    
    subgraph Compaction
        CheckAgain{Still > 85%?}
        Summarize[AI Summarization]
    end
    
    subgraph Output
        Result[Managed Messages]
    end
    
    Msgs --> Est --> Check
    Check -->|No| Result
    Check -->|Yes| Scan --> Protect --> Clear
    Clear --> CheckAgain
    CheckAgain -->|No| Result
    CheckAgain -->|Yes| Summarize --> Result
```

---

## Configuration

```python
# src/config/defaults.py
CONFIG = {
    "model": "deepseek-v4-pro",
    "provider": "deepseek",
    "max_tokens": 16384,
    "temperature": 1.0,
    "max_iterations": 200,
    "auto_compact_threshold": 0.85,
    "prune_protect": 40_000,
    "cache_enabled": True,
}
```

| Variable | Description |
|----------|-------------|
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | DeepSeek API base URL, `https://api.deepseek.com` |
| `LLM_MODEL` | Model override, default `deepseek-v4-pro` |
| `LLM_COST_LIMIT` | Maximum cost in USD before aborting |

---

## Documentation

See [docs/](docs/) for comprehensive documentation:

- [Overview](docs/overview.md) - Design principles
- [Architecture](docs/architecture.md) - Technical deep-dive
- [DeepSeek Integration](docs/chutes-integration.md) - API setup
- [Tools Reference](docs/tools.md) - All tools documented
- [Context Management](docs/context-management.md) - Token optimization
- [Best Practices](docs/best-practices.md) - Performance tips

See [rules/](rules/) for development guidelines.


---

## License

MIT License - see [LICENSE](LICENSE).

---

<p align="center">
  <strong>BaseAgent</strong>
</p>
