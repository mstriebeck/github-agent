# MCP Codebase Intelligence Server - Design Document

## Overall Goal

**PRIMARY GOAL: Replace slow, inaccurate grep-based code discovery with fast, semantic code intelligence.**

Currently, AI agents waste significant time grep'ing through codebases to find classes, methods, references, and usage patterns. This MCP server eliminates that inefficiency by maintaining a live, queryable index of code semantics.

The server will:

- **Provide instant semantic search** - Find classes, methods, variables by name across the entire codebase without file scanning
- **Deliver accurate symbol resolution** - Navigate to definitions, find all references, understand inheritance hierarchies
- **Maintain real-time indexes** - Track local changes and GitHub state to keep code intelligence current
- **Support cross-language queries** - Unified search across Python and Swift codebases
- **Scale to production codebases** - Sub-second query response times even for large, complex projects

All other features (Git integration, caching, etc.) serve this primary goal of fast, accurate code discovery.

## Expected Benefits and Impact

### Speed Improvements

**Current grep-based approach:**
- Agent searches through 10k+ files looking for a class definition
- Takes 5-30 seconds depending on codebase size
- Often requires multiple search iterations to find the right symbol
- Frequently misses overloaded methods or inheritance relationships

**With semantic index:**
- Symbol lookup: **50-200ms** (database query + LSP semantic data)
- No file scanning required
- Single query finds all related symbols (inheritance, overrides, references)
- **10-100x faster** for typical code discovery tasks

### Accuracy Improvements

**Grep limitations:**
- Finds text matches, not semantic matches
- Misses dynamic imports, decorators, metaclasses
- Can't distinguish between definition vs usage
- No understanding of scope, inheritance, or type relationships

**Semantic index benefits:**
- **True symbol resolution** through LSP servers
- Understands Python imports, Swift protocols, inheritance chains
- Distinguishes definitions from references
- Follows semantic relationships (method overrides, protocol conformance)

### Cost Reduction (The Big Win)

**Current token costs:**
```
Typical agent workflow:
1. grep search → send 2-5 file snippets (2k-10k tokens)
2. Need more context → send full files (5k-20k tokens)  
3. Find related code → send more files (10k-50k tokens)
Total: ~20k-80k tokens per code discovery task
```

**With semantic index:**
```
Semantic query response:
{
  "symbol": "UserManager.authenticate",
  "definition": {"file": "auth.py", "line": 45},
  "signature": "authenticate(username: str, password: str) -> Optional[User]", 
  "references": [{"file": "views.py", "line": 123}, ...],
  "related": ["User", "AuthenticationError"]
}
~200-500 tokens per response
```

**Cost savings: 95-99% token reduction** for code discovery tasks.

### Real-World Impact

**For a typical agent session:**
- **Before**: 3-5 code discovery tasks × 30k tokens = 90k-150k tokens
- **After**: 3-5 semantic queries × 300 tokens = 1k-1.5k tokens
- **Cost reduction**: ~99% for code intelligence portions
- **Time savings**: 2-10 minutes per session
- **Accuracy boost**: Fewer wrong assumptions about code structure

**Conservative estimate**: If 30% of agent interactions involve code discovery, you're looking at **70-90% total token savings** and **5-10x faster code-related responses**.

The semantic compression is the real game-changer - instead of dumping entire files into the context, agents get precisely the symbols and relationships they need.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP Server Interface                     │
├─────────────────────────────────────────────────────────────┤
│                   Query Orchestrator                       │
├─────────────────────────────────────────────────────────────┤
│  Python LSP Client  │  Swift LSP Client  │  Cross-Lang Index │
├─────────────────────────────────────────────────────────────┤
│              File System Monitor & Git Watcher             │
├─────────────────────────────────────────────────────────────┤
│           Repository Manager & Sync Engine                 │
├─────────────────────────────────────────────────────────────┤
│               Persistent Index Storage                     │
└─────────────────────────────────────────────────────────────┘
```

### Core Components

1. **MCP Server Interface** - Exposes standardized tools for code intelligence queries
2. **Query Orchestrator** - Routes queries to appropriate language servers and aggregates results
3. **Language Server Clients** - Manage connections to Python and Swift LSP servers
4. **Cross-Language Index** - Maintains fast lookup tables for symbols, files, and dependencies
5. **File System Monitor** - Watches for local file changes and triggers incremental updates
6. **Git Integration** - Tracks branch changes and syncs with remote repositories
7. **Repository Manager** - Handles multi-repo setups and workspace management
8. **Persistent Storage** - Stores indexed data for fast startup and cross-session persistence

## Detailed Design

### Repository Management

**Configuration-Based Repository Setup:**
- Use existing `repositories.json` configuration file with minimal extensions
- Each repository entry includes: path, language, description, and LSP configuration
- GitHub repo info (owner, repo) read from Git remote during validation
- Support for multiple local clients of the same GitHub repository
- No auto-detection - explicit configuration for predictable behavior

**Enhanced Configuration Schema:**
```json
{
  "repositories": {
    "github-agent-main": {
      "path": "/Volumes/Code/github-agent",
      "port": 8081,
      "description": "GitHub Agent repository - main workspace",
      "language": "python",
      "python_path": "/Volumes/Code/github-agent/.venv/bin/python"
    }
  }
}
```

**Configuration Notes:**
- `python_path`: Path to Python executable (may be in virtual environment)
- GitHub owner/repo extracted from `git remote get-url origin` during startup validation
- LSP server type determined by language field (pylsp for Python, sourcekit-lsp for Swift)

**Multi-Client Support:**
- Track each local repository instance separately based on local working directory
- Branch determined by current Git HEAD in each workspace
- Maintain independent indexes for different workspaces of same GitHub repo
- Cross-reference GitHub repository state with local changes

### Language Server Integration

**Python LSP Management:**
- Launch and manage pylsp or pyright language server instances
- Handle Python-specific features: imports, decorators, type hints, virtual environments
- Support multiple Python versions and project configurations
- Extract semantic information: class hierarchies, method signatures, variable types

**Swift LSP Management:**
- Launch and manage sourcekit-lsp instances
- Handle Swift Package Manager projects and Xcode workspaces
- Support for Swift/Objective-C interop analysis
- Extract semantic information: protocols, extensions, computed properties

**LSP Client Architecture:**
- Persistent LSP connections with automatic reconnection
- Request queuing and batching for efficiency
- Capability negotiation and feature detection
- Error handling and fallback strategies

### Indexing Strategy

**Incremental Indexing:**
- File-level change detection using filesystem events
- Symbol-level incremental updates through LSP didChange notifications
- Dependency graph maintenance for impact analysis
- Timestamp-based invalidation and cache management

**Cross-Language Symbol Resolution:**
- Build unified symbol table across Python and Swift codebases
- Handle import/dependency relationships between languages
- Support for FFI (Foreign Function Interface) bindings
- Module and package-level dependency tracking

**Index Storage Schema:**
```
Symbols: {name, kind, signature, location, definition, references[], repository_id}
Classes: {name, base_classes[], methods[], properties[], location, repository_id}
Methods: {name, class_name, signature, parameters[], return_type, location, repository_id}
Variables: {name, type, scope, location, repository_id}
Dependencies: {from_symbol, to_symbol, dependency_type, repository_id}
Files: {path, language, last_modified, git_hash, repository_id}
Git_State: {repository_id, current_branch, commit_hash, modified_files[]}
```

**Index Rebuild Capability:**
- Complete index reconstruction from current repository state
- Fast rebuild process that doesn't require historical data
- Atomic index replacement to avoid corruption during rebuild
- Automatic rebuild triggers on major Git operations (branch switch, merge, etc.)

### File System Monitoring

**Change Detection:**
- Use `watchdog` Python library for cross-platform file watching
- Filter relevant file types (.py, .swift, .pyi, .swiftinterface)
- Per-repository monitoring based on configured paths
- Debounce rapid changes to avoid index thrashing

**Local vs GitHub State Tracking:**
- Monitor local file modifications independently of GitHub state
- Track differences between local working directory and last known GitHub commit
- Handle scenarios where multiple local clients track the same GitHub repo
- Maintain separate change sets for each configured repository instance

### Query Interface (MCP Tools)

**Symbol Queries:**
- `find_definition(symbol, file=None)` - Navigate to symbol definition across all repositories
- `find_references(symbol, file=None)` - Find all symbol usage locations
- `find_implementations(interface, file=None)` - Locate concrete implementations
- `get_type_info(symbol, file=None)` - Retrieve type information and documentation

**Code Navigation:**
- `get_call_hierarchy(function, file=None)` - Build call graphs up/down
- `find_related_symbols(symbol)` - Discover related classes, methods, inheritance chains
- `search_symbols(query, kind=None)` - Fuzzy symbol search across all repositories
- `get_symbol_outline(symbol)` - Extract symbol structure and relationships

**Object/Method/Variable Analysis:**
- `analyze_class_hierarchy(class_name)` - Map inheritance and composition relationships
- `find_method_overrides(method_name, class_name=None)` - Locate method overrides and implementations
- `get_variable_usage(variable_name, scope=None)` - Track variable assignments and references
- `find_unused_symbols()` - Detect unused classes, methods, variables across codebase

**Code Intelligence:**
- `get_diagnostics(file)` - Retrieve linting errors and warnings
- `suggest_refactorings(selection)` - Propose code improvements
- `find_similar_code(snippet)` - Locate similar code patterns
- `get_test_coverage(file)` - Map test coverage information

### Caching and Performance

**Multi-Level Caching:**
- In-memory LRU cache for frequently accessed symbols
- Persistent SQLite database for index storage
- File-level caching with content-based invalidation
- Query result caching with smart invalidation

**Performance Optimizations:**
- Lazy loading of large symbol tables
- Background indexing for non-critical updates
- Query batching and deduplication
- Connection pooling for LSP servers

## Required Frameworks and Infrastructure

### Core Runtime
- **Node.js 18+** or **Python 3.9+** - Runtime environment
- **TypeScript** or **Python with type hints** - Primary development language

### MCP Framework
- **@modelcontextprotocol/sdk** - Official MCP SDK for server implementation
- **JSON-RPC 2.0** - MCP transport protocol implementation

### Language Server Integration
- **pylsp** or **pyright** - Python language server
- **sourcekit-lsp** - Swift language server  
- **vscode-languageserver-protocol** - LSP client implementation library

### File System and Git
- **chokidar** (Node.js) or **watchdog** (Python) - Cross-platform file watching
- **simple-git** (Node.js) or **GitPython** (Python) - Git repository management
- **ignore** - Gitignore-style file filtering

### Storage and Caching
- **better-sqlite3** (Node.js) or **sqlite3** (Python) - Embedded database for indexing
- **node-lru-cache** (Node.js) or **cachetools** (Python) - In-memory caching
- **msgpack** - Efficient binary serialization for cache storage

### Utilities
- **glob** - File pattern matching and discovery
- **minimatch** - Pattern matching for file filtering
- **semver** - Version parsing and comparison
- **chalk** (Node.js) or **colorama** (Python) - Terminal output formatting

### Development and Testing
- **Jest** (Node.js) or **pytest** (Python) - Testing framework
- **eslint/tslint** (Node.js) or **ruff** (Python) - Code linting
- **prettier** (Node.js) or **black** (Python) - Code formatting

## Testing Strategy

### Unit Testing

**Component-Level Tests:**
- LSP client communication and error handling
- File system monitoring accuracy and performance
- Git integration and branch switching
- Index storage and retrieval operations
- Query parsing and routing logic

**Mock Dependencies:**
- Mock LSP servers for controlled testing
- Simulated file system events
- Mock Git repositories with known states
- Controlled codebase fixtures for consistent testing

### Integration Testing

**End-to-End Scenarios:**
- Full repository indexing from scratch
- Incremental updates on file modification
- Branch switching and index synchronization
- Cross-language dependency resolution
- Query accuracy across different project structures

**Multi-Language Test Suites:**
- Python projects: Django apps, FastAPI services, data science notebooks
- Swift projects: iOS apps, command-line tools, Swift packages
- Mixed repositories with Python/Swift interop

### Performance Testing

**Scalability Benchmarks:**
- Large repository indexing (>10k files, >1M LOC)
- Query response time under various load conditions
- Memory usage during sustained operation
- Concurrent query handling capacity

**Real-World Validation:**
- Test against popular open-source repositories
- Measure indexing time vs repository size correlation
- Validate query accuracy against known codebases
- Performance comparison with IDE indexing speeds

### Regression Testing

**Continuous Integration:**
- Automated test runs on code changes
- Performance regression detection
- Cross-platform compatibility testing (macOS, Linux, Windows)
- Language server version compatibility validation

## Deployment Strategy

### Integration with Existing Setup

**Enhanced System Setup:**
The MCP codebase server integrates with the existing `setup/setup_system.sh` script:

```bash
# Run enhanced setup script (extended with codebase server)
./setup/setup_system.sh --with-codebase-server

# This will:
# 1. Install existing Python dependencies
# 2. Install LSP servers (pylsp, sourcekit-lsp)
# 3. Setup codebase indexing dependencies
# 4. Configure repositories.json with codebase settings
# 5. Setup master/worker architecture with codebase indexing
```

**Enhanced Repository CLI:**
The existing `repository_cli.py` gets new commands for codebase management:

```bash
# Enable codebase indexing for a repository
python3 repository_cli.py enable-codebase github-agent-main

# Start codebase indexing for all enabled repositories
python3 repository_cli.py start-codebase

# Check indexing status
python3 repository_cli.py codebase-status

# Rebuild indexes
python3 repository_cli.py rebuild-index --repo github-agent-main
```

**Master/Worker Architecture Integration:**
- **Existing Master**: `github_mcp_master.py` enhanced to manage codebase workers
- **New Codebase Worker**: `mcp_codebase_worker.py` for each repository with indexing enabled
- **Existing Worker**: `github_mcp_worker.py` continues handling GitHub API operations
- **Unified Management**: Single master process coordinates both GitHub and codebase services

**Configuration Management:**
- **EXTENDS** existing `repositories.json` format with codebase-specific fields
- **REUSES** existing environment variable patterns and validation
- **MAINTAINS** compatibility with existing repository management workflows

### Production Deployment

**Local Machine Deployment:**
Since the service needs access to local code and your UTM VM can't run Docker:

```bash
# System service installation
pip install mcp-codebase-server

# Create service configuration
sudo cp scripts/mcp-codebase.service /etc/systemd/system/
sudo systemctl enable mcp-codebase
sudo systemctl start mcp-codebase

# Or run as user process
python -m mcp_codebase --config ~/.config/mcp-codebase/repositories.json
```

**Optional Docker Support:**
For development machines that support Docker:
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y git
COPY . /app
WORKDIR /app
RUN pip install -e .
# Mount local code directories as volumes
VOLUME ["/code"]
EXPOSE 3000
CMD ["python", "-m", "mcp_codebase", "--config", "/config/repositories.json"]
```

### Distribution Options

**PyPI Package Distribution:**
```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "mcp-codebase-server"
version = "0.1.0"
description = "MCP server for codebase intelligence"
dependencies = [
    "mcp>=0.1.0",
    "watchdog>=3.0.0",
    "GitPython>=3.1.0",
    "pylsp>=1.8.0",
    "cachetools>=5.0.0"
]

[project.scripts]
mcp-codebase = "mcp_codebase.cli:main"
```

**Integration with Existing GitHub MCP Server:**
Since you mentioned potentially merging both servers, the architecture supports:
- Shared configuration file (`repositories.json`)
- Common GitHub integration patterns
- Modular design for easy integration
- Separate MCP tool namespaces (`github.*` vs `codebase.*`)

### Operational Considerations

**Monitoring and Logging:**
- Structured logging with configurable levels
- Health check endpoints for monitoring systems
- Metrics collection: query latency, indexing time, error rates
- LSP server health monitoring and automatic restart

**Resource Management:**
- Configurable memory limits for large repositories
- Disk space monitoring and cleanup policies
- CPU usage throttling during intensive indexing
- Graceful degradation under resource constraints

**Security Considerations:**
- Sandbox LSP server processes
- Validate repository access permissions
- Secure handling of sensitive code information
- Rate limiting for query endpoints

**Backup and Recovery:**
- Index backup and restoration procedures
- Configuration backup strategies
- Disaster recovery documentation
- Data migration procedures for upgrades