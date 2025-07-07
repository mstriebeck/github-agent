# US003 - Single Python Repository Discovery

## User Story
**As a developer** I want to search for Python symbols by name in a single repository so that I can quickly locate classes and functions without grep.

## Acceptance Criteria
- Index a single Python repository on startup
- Basic symbol search tool: `search_symbols(query, repository_id)`
- Return symbol name, type (class/function/variable), file location
- Sub-second response time for simple queries

## Task Breakdown

### Task 1: Basic Symbol Storage Schema - DONE
**Description**: Create the fundamental database schema for storing Python symbols with their locations and metadata.

**Implementation Details**:
- Create SQLite database schema for symbols table
- Define Symbol dataclass with: name, kind, file_path, line_number, column_number, repository_id
- Implement basic database operations: insert, update, delete, search symbols
- Support symbol kinds: class, function, method, variable, constant, module
- Include repository_id field for multi-repo support (future-proofing)

**Tests**:
- Unit tests for database schema creation
- Unit tests for symbol CRUD operations  
- Unit tests for symbol search by name (exact and partial matches)
- Unit tests for symbol filtering by kind
- Unit tests for repository_id filtering

**Acceptance Criteria**:
- Database schema created successfully
- Can store and retrieve symbols with all metadata
- Basic text search works for symbol names
- No breaking changes to existing functionality

### Task 2: Single Python File Parser and Symbol Extractor - DONE
**Description**: Implement Python AST-based parsing to extract symbols from a single Python file without LSP dependency.

**Implementation Details**:
- Create PythonSymbolExtractor class using Python AST module
- Extract classes, functions, methods, variables from a single Python file
- Handle nested classes and functions with proper scope tracking
- Extract docstrings and basic type information where available
- Support for imports and module-level symbols
- Handle Python-specific constructs: decorators, properties, class methods
- Return list of Symbol objects with file location information

**Tests**:
- Unit tests for parsing various Python constructs in single files
- Unit tests for nested class/function extraction
- Unit tests for import statement parsing
- Unit tests for decorator handling
- Unit tests for error handling (invalid Python syntax)
- Integration tests with sample Python files

**Acceptance Criteria**:
- Can parse a single Python file and extract all major symbol types
- Handles nested scopes correctly
- Gracefully handles malformed Python files
- Extracts accurate location information (line/column numbers)

### Task 3: Single Repository Indexing Engine - DONE
**Description**: Implement repository indexing that scans Python files and populates the symbol database.

**Implementation Details**:
- Create RepositoryIndexer class that processes a single repository
- Scan repository for Python files (.py, .pyi extensions)
- Skip common directories: __pycache__, .git, .pytest_cache, .mypy_cache
- Process files in batches to avoid memory issues
- Store indexing metadata: repository path, last indexed timestamp, file count
- Handle file reading errors gracefully
- Support for relative and absolute repository paths

**Tests**:
- Unit tests for file discovery logic
- Unit tests for directory filtering
- Unit tests for batch processing
- Integration tests with real Python repositories
- Tests for handling missing/corrupted files
- Tests for indexing progress tracking

**Acceptance Criteria**:
- Can index a complete Python repository
- Skips non-Python files and irrelevant directories
- Handles repositories of various sizes
- Provides indexing progress feedback
- Stores complete symbol inventory

### Task 4: MCP Tool Implementation - search_symbols - DONE
**Description**: Implement the MCP tool interface for symbol searching with proper error handling and response formatting.

**Implementation Details**:
- Create `search_symbols` MCP tool function
- Accept parameters: query (required), repository_id (optional)
- Return structured response with symbol details
- Implement fuzzy matching for symbol names
- Support filtering by symbol type (class, function, etc.)
- Limit results to prevent overwhelming responses (default 50 results)
- Sort results by relevance (exact match first, then fuzzy)

**Tests**:
- Unit tests for MCP tool parameter validation
- Unit tests for search query processing
- Unit tests for result formatting and limiting
- Unit tests for fuzzy matching behavior
- Integration tests with MCP server framework
- Tests for error handling (invalid repository_id, etc.)

**Acceptance Criteria**:
- MCP tool properly exposed and discoverable
- Returns well-formatted symbol search results
- Handles various query types (exact, partial, fuzzy)
- Respects result limits and sorting
- Proper error messages for invalid inputs

### Task 5: Simple CLI for Tool Testing - DONE
**Description**: Create a simple command-line interface to invoke MCP tools for easier debugging and testing without deploying to a coding agent.

**Implementation Details**:
- Create `codebase_cli.py` script for direct tool invocation
- Support for calling `search_symbols` with command-line arguments
- Pretty-print results in human-readable format
- Handle errors and display clear error messages
- Support for different output formats (JSON, table, simple text)
- Include help text and usage examples

**Tests**:
- Unit tests for CLI argument parsing
- Unit tests for output formatting
- Integration tests with actual MCP tools
- Tests for error handling and user feedback
- Tests for different output formats

**Acceptance Criteria**:
- CLI can invoke search_symbols tool directly
- Results are displayed in readable format
- Clear error messages for invalid inputs
- Help documentation is available
- Easy to use for debugging and testing

### Task 6: Repository Configuration Integration - DONE
**Description**: Integrate with existing repositories.json configuration to identify Python repositories for indexing.

**Implementation Details**:
- Read existing repositories.json configuration
- Filter repositories with language="python"
- Validate repository paths exist and contain Python files
- Extract repository metadata (name, path, description)
- Support for python_path field for virtual environment detection
- Integrate with existing configuration validation

**Tests**:
- Unit tests for configuration parsing
- Unit tests for repository filtering by language
- Unit tests for path validation
- Integration tests with real repositories.json
- Tests for handling missing/invalid configurations

**Acceptance Criteria**:
- Reads existing configuration format without breaking changes
- Identifies Python repositories correctly
- Validates repository paths and accessibility
- Integrates with existing configuration management

### Task 7: Server Startup and Indexing Orchestration - DONE
**Description**: Implement server startup sequence that automatically indexes configured Python repositories.

**Implementation Details**:
- Create startup sequence that initializes database and indexing
- Process all Python repositories from configuration on startup
- Implement indexing status tracking and logging
- Handle indexing failures gracefully (continue with other repositories)
- Provide startup completion feedback
- Support for background indexing to avoid blocking server startup

**Tests**:
- Unit tests for startup sequence
- Unit tests for indexing orchestration
- Integration tests with multiple repositories
- Tests for handling indexing failures
- Tests for startup time with various repository sizes

**Acceptance Criteria**:
- Server starts successfully and indexes all configured repositories
- Handles multiple repositories concurrently
- Provides clear logging of indexing progress
- Gracefully handles repositories that fail to index
- Server remains responsive during indexing

### Task 8: Performance Optimization and Response Time
**Description**: Optimize symbol search to achieve sub-second response times for typical queries.

**Implementation Details**:
- Add database indexes for common query patterns
- Implement in-memory caching for frequently accessed symbols
- Optimize search algorithms for large symbol sets
- Add query performance monitoring and logging
- Implement result pagination for large result sets
- Database connection pooling and query optimization

**Tests**:
- Performance tests for search response times
- Load tests with large repositories (>1000 symbols)
- Memory usage tests during peak operations
- Database query optimization verification
- Cache effectiveness tests

**Acceptance Criteria**:
- Symbol search responds in <1 second for typical queries
- Memory usage remains reasonable during operation
- Database queries are optimized with proper indexing
- System performs well with repositories containing 1000+ symbols

### Task 9: Error Handling and Resilience
**Description**: Implement comprehensive error handling and recovery mechanisms for robust operation.

**Implementation Details**:
- Handle database connection failures with retry logic
- Graceful handling of corrupted Python files
- File system permission error handling
- Memory management during large repository processing
- Proper error logging and user feedback
- Recovery mechanisms for database corruption

**Tests**:
- Unit tests for various error scenarios
- Tests for database failure recovery
- Tests for file system error handling
- Tests for memory pressure scenarios
- Integration tests for error propagation

**Acceptance Criteria**:
- System handles common error conditions gracefully
- Provides clear error messages to users
- Continues operating when individual operations fail
- Logs errors appropriately for debugging
- Implements retry logic for transient failures

### Task 10: Integration Testing and End-to-End Validation
**Description**: Comprehensive integration testing to validate the complete US003 functionality.

**Implementation Details**:
- Create comprehensive test suite for complete workflow
- Test with multiple real Python repositories
- Validate MCP tool integration and response formats
- Performance testing with realistic repository sizes
- Cross-platform compatibility testing
- Integration with existing MCP server infrastructure

**Tests**:
- End-to-end tests for complete indexing and search workflow
- Integration tests with real repositories (github-agent, sample projects)
- Performance benchmarks with various repository sizes
- MCP client integration tests
- Cross-platform compatibility tests

**Acceptance Criteria**:
- Complete workflow works from configuration to search results
- Meets performance requirements with real repositories
- Integrates properly with existing MCP server
- Works across different operating systems
- Provides reliable and consistent results

## Task Sequence Summary

1. **Basic Symbol Storage Schema** - Database foundation
2. **Single Python File Parser** - AST-based symbol extraction for one file
3. **Repository Indexing Engine** - Core indexing logic
4. **MCP Tool Implementation** - `search_symbols` tool
5. **Simple CLI for Tool Testing** - Debug and test tools easily
6. **Configuration Integration** - Works with existing `repositories.json`
7. **Server Startup Orchestration** - Automatic indexing on startup
8. **Performance Optimization** - Sub-second response times
9. **Error Handling** - Robust failure recovery
10. **Integration Testing** - End-to-end validation

## Dependencies
- Depends on US002 (Repository Configuration) being completed
- Requires existing MCP server infrastructure from US001

## Technical Notes
- Uses SQLite for symbol storage (lightweight, no external dependencies)
- Python AST parsing for initial implementation (no LSP dependency yet)
- Designed to be extended with LSP integration in future stories
- Repository configuration format remains compatible with existing setup

## Success Metrics
- Index and search a Python repository with 1000+ symbols in <10 seconds
- Symbol search responds in <1 second for typical queries
- Successfully handles repositories with various Python versions and structures
- Zero breaking changes to existing functionality
- 100% test coverage for all new components

## Future Enhancements (Out of Scope)
- LSP server integration (US005)
- Real-time file monitoring (US010)
- Cross-repository search (US008)
- Advanced symbol relationships (US015)
