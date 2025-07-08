# US005 - Python LSP Integration - Task Breakdown

## User Story
**As a developer** I want accurate symbol definitions and references through Python LSP so that I get semantic understanding rather than text matching.

## Acceptance Criteria
- Launch and manage pyright server instance per repository (with pluggable LSP architecture)
- LEVERAGES existing virtual environment settings from `repositories.json`
- `find_definition(symbol, repository_id)` tool returns precise location
- `find_references(symbol, repository_id)` tool returns all usage locations
- Handle Python imports, classes, functions, and variables correctly
- Abstract LSP interface allows easy switching between pyright/pylsp

## Task Breakdown

### Task 1: Abstract LSP Client Infrastructure
**Description**: Create the core abstract LSP client infrastructure that can communicate with any language server using the Language Server Protocol, with pluggable implementations.

**Implementation Details**:
- Create `AbstractLSPClient` base class for generic LSP communication
- Create `LSPServerManager` interface for pluggable server implementations
- Implement JSON-RPC 2.0 protocol for LSP communication
- Handle LSP initialization, capabilities negotiation, and shutdown
- Add proper error handling and connection management
- Support for both stdio and TCP communication modes
- Factory pattern for creating specific LSP server instances

**Changes Required**:
- Add `lsp_client.py` module with base LSP client implementation
- Add LSP protocol constants and message types
- Extend existing error handling in `exit_codes.py` for LSP errors
- Add LSP-specific logging configuration

**Tests Required**:
- Unit tests for LSP message serialization/deserialization
- Mock LSP server for testing protocol communication
- Connection error handling and recovery tests
- Capability negotiation tests

**Acceptance Criteria**:
- LSP client can establish connection with mock LSP server
- Proper handling of LSP initialization sequence
- Error recovery on connection failures
- All tests pass without warnings

### Task 2: Pyright LSP Server Management
**Description**: Implement Python-specific LSP server management that launches and manages pyright instances using repository configuration, with pluggable architecture.

**Implementation Details**:
- Create `PyrightLSPManager` class implementing the `LSPServerManager` interface
- Launch pyright server using configured Python path from `repositories.json`
- Handle Python-specific LSP capabilities (hover, definition, references, type checking)
- Implement server lifecycle management (start, stop, restart)
- Add workspace folder configuration for Python projects
- Support for pyright-specific configuration (pyrightconfig.json)

**Changes Required**:
- Add `pyright_lsp_manager.py` module
- Modify repository configuration validation to check pyright availability
- Add LSP server process management utilities
- Extend existing repository manager to include LSP managers
- Add pyright configuration file generation

**Tests Required**:
- Unit tests for Python LSP server launching
- Mock pyright server for testing Python-specific features
- Repository configuration validation tests
- Process lifecycle management tests
- Pyright configuration generation tests

**Acceptance Criteria**:
- pyright server launches successfully with configured Python path
- Server responds to basic LSP requests (initialize, capabilities)
- Proper cleanup on server shutdown
- Superior type checking and IntelliSense compared to basic text matching
- All tests pass without warnings

### Task 3: Core LSP Tools Implementation
**Description**: Implement the core MCP tools that provide symbol definition and reference lookup using the abstract LSP client with hybrid indexing approach.

**Implementation Details**:
- Add `find_definition` MCP tool that calls LSP textDocument/definition
- Add `find_references` MCP tool that calls LSP textDocument/references
- Implement hybrid approach: fast symbol index + live LSP queries for precision
- Implement coordinate conversion between LSP and user-friendly formats
- Add proper error handling for LSP request failures
- Support for both absolute and relative file paths
- Fallback to symbol index when LSP is unavailable

**Changes Required**:
- Add LSP tool implementations to existing MCP server
- Extend tool registration in the MCP server setup
- Add file path resolution utilities
- Modify existing symbol search to optionally use LSP data

**Tests Required**:
- Unit tests for definition and reference lookup
- Integration tests with real Python files
- File path resolution tests
- Error handling tests for invalid symbols/files

**Acceptance Criteria**:
- `find_definition` returns accurate file location and line number
- `find_references` returns all usage locations for a symbol
- Tools work with Python imports, classes, functions, and variables
- All tests pass without warnings

### Task 4: Repository Integration
**Description**: Integrate LSP management into the existing repository management system to ensure each repository gets its own LSP server instance.

**Implementation Details**:
- Extend `RepositoryManager` to manage LSP server instances
- Add LSP server startup/shutdown to repository lifecycle
- Implement repository-specific LSP workspace configuration
- Add LSP server health monitoring and automatic restart
- Handle virtual environment detection and configuration

**Changes Required**:
- Modify existing `repository_manager.py` to include LSP managers
- Add LSP server configuration to repository validation
- Extend repository status tracking to include LSP state
- Add LSP server management to worker startup/shutdown

**Tests Required**:
- Integration tests for repository with LSP server
- Repository configuration validation tests
- LSP server health monitoring tests
- Virtual environment detection tests

**Acceptance Criteria**:
- Each repository gets its own LSP server instance
- LSP servers use correct Python path from repository configuration
- Repository status includes LSP server health
- All tests pass without warnings

### Task 5: Error Handling and Resilience
**Description**: Implement comprehensive error handling and resilience features for LSP server failures and communication issues.

**Implementation Details**:
- Add automatic LSP server restart on crashes
- Implement request timeout handling
- Add fallback mechanisms when LSP is unavailable
- Implement graceful degradation for LSP failures
- Add detailed error logging and diagnostics

**Changes Required**:
- Add LSP server monitoring and restart logic
- Extend existing error handling patterns
- Add LSP-specific error codes and messages
- Implement request queuing during server restart

**Tests Required**:
- LSP server crash and restart tests
- Request timeout and failure handling tests
- Graceful degradation tests
- Error logging and diagnostics tests

**Acceptance Criteria**:
- LSP server automatically restarts on crashes
- Clear error messages for common configuration issues
- System continues to function when LSP is temporarily unavailable
- All tests pass without warnings

### Task 6: End-to-End Integration Testing
**Description**: Implement comprehensive end-to-end tests that validate the complete LSP integration functionality across the entire system.

**Implementation Details**:
- Create test repositories with various Python constructs
- Test complete workflow from repository configuration to symbol lookup
- Validate LSP integration with existing MCP server infrastructure
- Test interaction with existing repository management features
- Performance testing for LSP operations

**Changes Required**:
- Add comprehensive test fixtures with Python codebases
- Create end-to-end test scenarios
- Add performance benchmarks for LSP operations
- Integrate with existing test infrastructure

**Tests Required**:
- End-to-end symbol definition and reference tests
- Multi-repository LSP integration tests
- Performance benchmarks for LSP operations
- Compatibility tests with existing features

**Acceptance Criteria**:
- Complete user story workflow works end-to-end
- LSP integration doesn't break existing functionality
- Performance meets sub-second response requirements
- All acceptance criteria for US005 are met

## Implementation Order

1. **Task 1**: LSP Client Infrastructure (Foundation)
2. **Task 2**: Python LSP Server Management (Python-specific implementation)
3. **Task 3**: Core LSP Tools Implementation (MCP tool interface)
4. **Task 4**: Repository Integration (Integration with existing system)
5. **Task 5**: Error Handling and Resilience (Robustness)
6. **Task 6**: End-to-End Integration Testing (Validation)

## Dependencies

- **US004 completed**: Single Repository Symbol Search provides the foundation for repository management
- **pyright package**: Must be available in the Python environment (npm install -g pyright)
- **Existing repository configuration**: Leverages `repositories.json` schema
- **Node.js**: Required for pyright installation and execution

## Success Metrics

- LSP server startup time: < 2 seconds
- Symbol definition lookup time: < 200ms
- Symbol reference lookup time: < 500ms
- Server restart time on crash: < 5 seconds
- Test coverage: > 90% for new LSP components

## Notes

- Each task builds incrementally on the previous tasks
- The server remains functional throughout implementation
- New LSP features are additive and don't break existing functionality
- **Abstract LSP architecture** enables easy addition of other language servers (Swift, TypeScript, etc.)
- **Pyright provides superior type analysis** compared to pylsp, including better IntelliSense and type checking
- **Hybrid approach** combines fast indexing with live LSP queries for optimal performance
- Virtual environment support is crucial for Python LSP accuracy
- Error handling is prioritized to ensure system reliability
