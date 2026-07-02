# Installation Guide

> **Step-by-step instructions for setting up BaseAgent**

## Prerequisites

Before installing BaseAgent, ensure you have:

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.9+ | Python 3.11+ recommended |
| pip | Latest | Python package manager |
| Git | 2.x | For cloning the repository |

### Optional but Recommended

| Tool | Purpose |
|------|---------|
| `ripgrep` (`rg`) | Fast file searching (used by `grep_files` tool) |
| `tree` | Directory visualization |

---

## Installation Methods

### Method 1: Using pyproject.toml (Recommended)

```bash
# Clone the repository
git clone https://github.com/your-org/baseagent.git
cd baseagent

# Install with pip
pip install .
```

This installs BaseAgent as a package with all dependencies.

### Method 2: Using requirements.txt

```bash
# Clone the repository
git clone https://github.com/your-org/baseagent.git
cd baseagent

# Install dependencies
pip install -r requirements.txt
```

### Method 3: Development Installation

For development with editable installs:

```bash
git clone https://github.com/your-org/baseagent.git
cd baseagent

# Editable install
pip install -e .
```

---

## Dependencies

BaseAgent requires these Python packages:

```
httpx>=0.27.0           # LLM gateway HTTP client
pydantic>=2.0.0         # Data validation
```

These are automatically installed via pip.

---

## Environment Setup

### 1. Configure the LLM Gateway

BaseAgent challenge runs call the platform LLM gateway, which picks the provider and model.

```bash
export BASE_LLM_GATEWAY_URL="https://<gateway-host>/llm/v1"
export BASE_GATEWAY_TOKEN="your-signed-gateway-token"
# Optional cost cap
export LLM_COST_LIMIT="10.0"
```

The agent calls the platform LLM gateway at `BASE_LLM_GATEWAY_URL` using `BASE_GATEWAY_TOKEN`; the platform chooses the provider and model. Miners MUST NOT embed provider API keys, base URLs, or model names, and MUST NOT call any LLM provider directly. Set `BASEAGENT_MOCK_LLM=1` to run without a gateway URL or token (mock mode).

### 2. Create a Configuration File (Optional)

Create `.env` in the project root:

```bash
# .env file
BASE_LLM_GATEWAY_URL=https://<gateway-host>/llm/v1
BASE_GATEWAY_TOKEN=your-signed-gateway-token
LLM_COST_LIMIT=10.0
```

---

## Verification

### Step 1: Verify Python Installation

```bash
python3 --version
# Expected: Python 3.11.x or higher
```

### Step 2: Verify Dependencies

```bash
python3 -c "import httpx; print('httpx:', httpx.__version__)"
python3 -c "import pydantic; print('pydantic:', pydantic.__version__)"
```

### Step 3: Verify BaseAgent Installation

```bash
python3 -c "from src.core.loop import run_agent_loop; print('BaseAgent: OK')"
```

### Step 4: Test Run

```bash
python3 agent.py --instruction "Print 'Hello, BaseAgent!'"
```

Expected output: JSONL events showing the agent executing your instruction.

---

## Directory Structure After Installation

```
baseagent/
├── agent.py                 # ✓ Entry point
├── src/
│   ├── core/
│   │   ├── loop.py          # ✓ Agent loop
│   │   └── compaction.py    # ✓ Context manager
│   ├── llm/
│   │   └── client.py        # ✓ LLM client
│   ├── config/
│   │   └── defaults.py      # ✓ Configuration
│   ├── tools/               # ✓ Tool implementations
│   ├── prompts/
│   │   └── system.py        # ✓ System prompt
│   └── output/
│       └── jsonl.py         # ✓ Event emission
├── requirements.txt         # ✓ Dependencies
├── pyproject.toml           # ✓ Package config
├── docs/                    # ✓ Documentation
├── rules/                   # Development guidelines
└── astuces/                 # Implementation techniques
```

---

## Troubleshooting

### Issue: Missing dependencies

**Solution**: Install dependencies

```bash
pip install -r requirements.txt
# or
pip install httpx pydantic rich typer
```

### Issue: `ImportError: cannot import name 'run_agent_loop'`

**Solution**: Ensure you're in the project root directory

```bash
cd /path/to/baseagent
python3 agent.py --instruction "..."
```

### Issue: API Key Errors

**Solution**: Verify your environment variables are set

```bash
# Check if variables are set
echo $BASE_LLM_GATEWAY_URL
echo $BASE_GATEWAY_TOKEN

# Re-export if needed
export BASE_LLM_GATEWAY_URL="https://<gateway-host>/llm/v1"
export BASE_GATEWAY_TOKEN="your-signed-gateway-token"
```

### Issue: `rg` (ripgrep) Not Found

The `grep_files` tool will fall back to `grep` if `rg` is not available, but ripgrep is much faster.

**Solution**: Install ripgrep

```bash
# Ubuntu/Debian
apt-get install ripgrep

# macOS
brew install ripgrep

# Or via cargo
cargo install ripgrep
```

---

## Next Steps

- [Quick Start](./quickstart.md) - Run your first task
- [Configuration](./configuration.md) - Customize settings
