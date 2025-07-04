# MCP Codebase Server - User Stories Development Plan

## Phase 1: Foundation and Basic Setup

### US001 - Basic MCP Server Setup - DONE
**Moved to**: [`improvements/mcp_server_user_stories/US001-Basic-MCP-Server-Setup.md`](file:///Volumes/Code/github-agent/improvements/mcp_server_user_stories/US001-Basic-MCP-Server-Setup.md)

### US002 - Repository Configuration - DONE
**As an administrator** I want to define repositories in a configuration file so that the system knows which codebases to index.

**Acceptance Criteria:**
- Extend existing `repositories.json` schema with `python_path` field for Python repositories
- Server validates configuration on startup with clear error messages:
  - **Syntactic validation**: JSON structure, required parameters present (path, language, description, python_path), parameter values have correct types
  - **Semantic validation**: path points to existing directory, directory contains a Git repository, python_path points to valid Python executable, extract GitHub owner/repo from git remote
- Support for both absolute and relative paths (already exists)
- Manual editing of `repositories.json` file

### US003 - Single Python Repository Discovery
**As a developer** I want to search for Python symbols by name in a single repository so that I can quickly locate classes and functions without grep.

**Acceptance Criteria:**
- Index a single Python repository on startup
- Basic symbol search tool: `search_symbols(query, repository_id)`
- Return symbol name, type (class/function/variable), file location
- Sub-second response time for simple queries

## Phase 2: Core Language Server Integration

### US004 - Single Repository Symbol Search
**As a developer** I want to search for Python symbols by name in a single repository so that I can quickly locate classes and functions without grep.

**Acceptance Criteria:**
- Index a single Python repository using existing repository configuration
- Basic symbol search tool: `search_symbols(query, repository_id)`
- Return symbol name, type (class/function/variable), file location
- Sub-second response time for simple queries
- Integration with existing repository port assignments

### US005 - Python LSP Integration
**As a developer** I want accurate symbol definitions and references through Python LSP so that I get semantic understanding rather than text matching.

**Acceptance Criteria:**
- Launch and manage pylsp server instance per repository
- LEVERAGES existing virtual environment settings from `repositories.json`
- `find_definition(symbol, repository_id)` tool returns precise location
- `find_references(symbol, repository_id)` tool returns all usage locations
- Handle Python imports, classes, functions, and variables correctly

### US005 - Symbol Type Information
**As a developer** I want to retrieve type information and signatures for Python symbols so that I understand how to use them correctly.

**Acceptance Criteria:**
- `get_type_info(symbol, repository_id)` returns function signatures, parameter types
- Support for Python type hints and docstrings
- Class hierarchy information (base classes, methods)
- Variable type inference from context

### US006 - Error Handling and Resilience
**As a developer** I want the system to gracefully handle LSP server failures so that temporary issues don't break my workflow.

**Acceptance Criteria:**
- Automatic LSP server restart on crashes
- Fallback to cached data when LSP is unavailable
- Clear error messages for common configuration issues
- Graceful degradation when language server is unresponsive

## Phase 3: Multi-Repository Support

### US007 - Multiple Python Repositories
**As an administrator** I want to configure multiple Python repositories so that I can search across all my projects simultaneously.

**Acceptance Criteria:**
- Support multiple repositories in `repositories.json`
- Each repository gets unique identifier
- Cross-repository symbol search
- Repository-specific queries when needed

### US008 - Cross-Repository Symbol Search
**As a developer** I want to search for symbols across all configured repositories so that I can find code regardless of which project it's in.

**Acceptance Criteria:**
- `search_symbols(query)` without repository_id searches all repos
- Results include repository information
- Ranking/prioritization of results across repositories
- Filter results by repository if needed

### US009 - Repository State Management
**As a developer** I want the system to track which repositories are indexed and their status so that I know when data might be stale.

**Acceptance Criteria:**
- Repository status API showing indexed/error/indexing states
- Last index timestamp for each repository
- Clear indication when repository is out of sync
- Manual re-index capability per repository

## Phase 4: Real-Time Updates and File Monitoring

### US010 - File Change Detection
**As a developer** I want the index to automatically update when I modify Python files so that my searches always reflect current code.

**Acceptance Criteria:**
- File system monitoring using watchdog
- Incremental index updates on file save
- Detect file additions, deletions, and modifications
- Debounce rapid changes to avoid thrashing

### US011 - Incremental Indexing
**As a developer** I want fast index updates that only process changed files so that I don't wait for full re-indexing after small changes.

**Acceptance Criteria:**
- Only re-index modified files and their dependencies
- Dependency impact analysis (if A imports B, update A when B changes)
- Preserve index data for unchanged files
- Background processing doesn't block queries

### US012 - Git Integration Basics
**As a developer** I want the system to detect when I switch Git branches so that the index reflects the current branch's code.

**Acceptance Criteria:**
- Monitor Git HEAD changes
- Trigger full re-index on branch switch
- Track current branch in repository status
- Handle merge conflicts gracefully

## Phase 5: Advanced Code Intelligence

### US013 - Class and Inheritance Analysis
**As a developer** I want to analyze Python class hierarchies and method overrides so that I understand object-oriented relationships.

**Acceptance Criteria:**
- `analyze_class_hierarchy(class_name)` returns inheritance tree
- `find_method_overrides(method_name)` finds parent and child implementations
- Support for multiple inheritance and mixins
- Method resolution order (MRO) information

### US014 - Call Hierarchy and Dependencies
**As a developer** I want to build call graphs to understand how functions and methods relate so that I can trace code execution paths.

**Acceptance Criteria:**
- `get_call_hierarchy(function)` returns callers and callees
- Support for both "calls to" and "calls from" analysis
- Handle dynamic calls where possible
- Visualize dependency chains

### US015 - Advanced Symbol Relationships
**As a developer** I want to find related symbols (imports, usage patterns) so that I can understand code context and dependencies.

**Acceptance Criteria:**
- `find_related_symbols(symbol)` returns imports, exports, usage patterns
- Decorator and metaclass relationship tracking
- Module-level dependency analysis
- Symbol usage frequency and patterns

## Phase 6: Swift Language Support

### US016 - Swift Repository Configuration
**As an administrator** I want to configure Swift repositories with appropriate LSP settings so that I can index iOS and macOS codebases.

**Acceptance Criteria:**
- Extend `repositories.json` to support Swift language configuration
- Support for Xcode projects and Swift Package Manager
- sourcekit-lsp server integration
- Swift-specific project discovery

### US017 - Swift Symbol Search and Navigation
**As a developer** I want to search Swift symbols and navigate to definitions so that I have the same capabilities for Swift as Python.

**Acceptance Criteria:**
- All basic tools work with Swift: `search_symbols`, `find_definition`, `find_references`
- Swift-specific constructs: protocols, extensions, computed properties
- Support for Swift/Objective-C interop
- Generic type resolution

### US018 - Cross-Language Project Support
**As a developer** I want to work with projects that contain both Python and Swift code so that I can manage polyglot codebases.

**Acceptance Criteria:**
- Mixed-language repositories in single configuration
- Cross-language symbol search
- Language-specific filtering when needed
- Handle language-specific build systems (requirements.txt, Package.swift)

## Phase 7: Performance and Scalability

### US019 - Large Codebase Performance
**As a developer** I want sub-second query responses even for large codebases (>10k files) so that the system remains usable for production projects.

**Acceptance Criteria:**
- Query response time <200ms for simple symbol lookups
- Indexing time scales reasonably with codebase size
- Memory usage remains bounded during operation
- Background indexing doesn't impact query performance

### US020 - Persistent Index Storage
**As a developer** I want the system to remember indexed data between restarts so that I don't wait for full re-indexing every time.

**Acceptance Criteria:**
- SQLite database for persistent symbol storage
- Fast startup using cached index data
- Incremental updates to persistent storage
- Corruption detection and recovery

### US021 - Caching and Query Optimization
**As a developer** I want frequently accessed symbols to be cached in memory so that repeated queries are instant.

**Acceptance Criteria:**
- LRU cache for hot symbols and query results
- Smart cache invalidation on file changes
- Query result deduplication
- Cache hit ratio monitoring

## Phase 8: Advanced Features and Polish

### US022 - Diagnostic and Code Quality
**As a developer** I want to access linting errors and warnings through the MCP interface so that I can understand code quality issues.

**Acceptance Criteria:**
- `get_diagnostics(file)` returns LSP diagnostic information
- Support for both Python (pylint, mypy) and Swift diagnostics
- Severity levels and categorization
- Integration with common linting tools

### US023 - Code Search and Pattern Matching
**As a developer** I want to find similar code patterns and unused symbols so that I can identify refactoring opportunities.

**Acceptance Criteria:**
- `find_similar_code(snippet)` for code pattern detection
- `find_unused_symbols()` for dead code identification
- Fuzzy matching for symbol names
- Regular expression support in symbol search

### US024 - GitHub Integration and Remote Sync
**As a developer** I want the system to sync with GitHub repository state so that I can track differences between local and remote code.

**Acceptance Criteria:**
- Track GitHub repository metadata in configuration
- Compare local vs remote branch states
- Handle multiple local workspaces for same GitHub repo
- Sync status and conflict detection

### US025 - Comprehensive Testing and Monitoring
**As an administrator** I want comprehensive system monitoring and health checks so that I can ensure reliable operation.

**Acceptance Criteria:**
- Health check endpoints for all components
- Performance metrics collection (query latency, index size)
- Error logging and alerting
- Resource usage monitoring (CPU, memory, disk)

### US026 - Advanced Configuration and Deployment
**As an administrator** I want flexible deployment options and advanced configuration so that I can customize the system for different environments.

**Acceptance Criteria:**
- Environment variable configuration overrides
- Service/daemon deployment scripts
- Resource limit configuration
- Security and access control options

---

## Development Notes

### Build Strategy
Each user story should be completely functional before moving to the next. This means:
- US001-US003 create a minimal but working MCP server
- US004-US006 add robust Python LSP integration
- US007-US009 scale to multiple repositories
- And so on...

### Testing Strategy
Each user story includes:
- Unit tests for new components
- Integration tests for user-facing functionality
- Performance tests for scalability stories
- Regression tests to ensure previous stories still work

### Milestone Checkpoints
- **Milestone 1** (US001-US006): Basic single-repository Python support
- **Milestone 2** (US007-US012): Multi-repository with real-time updates  
- **Milestone 3** (US013-US018): Advanced intelligence and Swift support
- **Milestone 4** (US019-US026): Production-ready with full feature set