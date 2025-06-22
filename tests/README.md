# Shutdown System Test Suite

This directory contains a comprehensive test suite for the MCP server shutdown system. The tests are organized to provide thorough coverage of all shutdown scenarios, edge cases, and integration points.

## Test Organization

### Unit Tests
- **`test_exit_codes.py`** - Tests exit code system and error classification
- **`test_health_monitor.py`** - Tests health monitoring and status reporting
- **`test_shutdown_manager.py`** - Tests the consolidated shutdown manager

### Integration Tests  
- **`test_shutdown_integration.py`** - End-to-end shutdown scenarios with mock processes
- **`test_abstracts.py`** - Abstract base classes for mocking system operations

### Edge Case Tests
- **`test_edge_cases.py`** - Unusual scenarios, race conditions, and error handling

### Test Infrastructure
- **`conftest.py`** - Pytest configuration and shared fixtures
- **`test_runner.py`** - Comprehensive test runner with reporting
- **`README.md`** - This documentation

## Running Tests

### Quick Start
```bash
# Run all core tests
python tests/test_runner.py

# Verbose output
python tests/test_runner.py -v

# Run specific test suites
python tests/test_runner.py --unit
python tests/test_runner.py --integration
python tests/test_runner.py --edge-cases
```

### Comprehensive Testing
```bash
# Run everything including performance and coverage
python tests/test_runner.py --all

# Just add performance tests
python tests/test_runner.py --performance

# Just add coverage analysis
python tests/test_runner.py --coverage
```

### Using Pytest Directly
```bash
# Activate virtual environment
source .venv/bin/activate

# Run specific test file
python -m pytest tests/test_exit_codes.py -v

# Run with coverage
python -m pytest tests/ --cov=../ --cov-report=html

# Run only integration tests
python -m pytest tests/ -m integration

# Run only fast tests (exclude slow/edge cases)
python -m pytest tests/ -m "not slow"
```

## Test Categories

### Markers
Tests are marked with the following categories:
- `@pytest.mark.integration` - Integration tests with mock processes
- `@pytest.mark.edge_case` - Edge case and stress tests  
- `@pytest.mark.slow` - Tests that may take several seconds

### Test Scenarios Covered

#### Happy Path Scenarios
- ✅ Clean shutdown with cooperative workers
- ✅ Clean shutdown with cooperative clients  
- ✅ Clean resource cleanup
- ✅ Proper port release
- ✅ Health monitoring integration

#### Error Scenarios
- ✅ Worker timeout and force termination
- ✅ Unresponsive client connections
- ✅ Port release failures
- ✅ Resource cleanup failures
- ✅ Zombie process detection

#### Edge Cases
- ✅ Rapid signal delivery
- ✅ Concurrent shutdown attempts
- ✅ Process resurrection scenarios
- ✅ Permission denied errors
- ✅ System resource limits
- ✅ Race conditions in state updates

#### Integration Scenarios
- ✅ Master mode shutdown (4 phases)
- ✅ Worker mode shutdown (3 phases)
- ✅ Mixed cooperative/unresponsive processes
- ✅ Partial failure recovery
- ✅ Health monitoring throughout shutdown

## Mock Process System

The test suite uses a sophisticated mock process system defined in `test_abstracts.py`:

### Mock Process Types
- **`CooperativeMockProcess`** - Responds to signals gracefully
- **`UnresponsiveMockProcess`** - Ignores shutdown signals
- **`ZombieMockProcess`** - Becomes zombie instead of terminating
- **`CooperativeMockPort`** - Releases cleanly when requested
- **`StickyMockPort`** - Refuses to release (simulates stuck ports)
- **`CooperativeMockClient`** - Disconnects when requested
- **`UnresponsiveMockClient`** - Ignores disconnect requests

### Mock Registry
The `MockProcessRegistry` manages all mock objects and provides:
- Process creation with different behaviors
- Automatic cleanup after tests
- Simulation of various system conditions
- Thread-safe concurrent operations

## Test Coverage Goals

The test suite aims for:
- **100% line coverage** on shutdown components
- **All exit codes** tested and verified
- **All shutdown phases** tested in isolation and integration
- **All error paths** covered with appropriate mocking
- **Performance characteristics** validated
- **Concurrency safety** verified

## Expected Test Results

### Success Criteria
All tests should pass with:
- No hanging tests (all complete within timeouts)
- No resource leaks (threads, files, ports)
- Consistent results across multiple runs
- Clear error messages for any failures

### Performance Expectations
- Unit tests: < 1 second each
- Integration tests: < 10 seconds each  
- Edge case tests: < 30 seconds each
- Full suite: < 5 minutes total

## Debugging Failed Tests

### Common Issues
1. **Import errors** - Ensure all dependencies are installed
2. **Port conflicts** - Tests use high port numbers to avoid conflicts
3. **Threading issues** - Tests include automatic thread cleanup
4. **Mock setup** - Check that process registry is properly initialized

### Debug Strategies
```bash
# Run single test with full output
python -m pytest tests/test_shutdown_manager.py::TestShutdownManager::test_clean_shutdown -v -s

# Run with Python debugger
python -m pytest tests/test_shutdown_manager.py --pdb

# Show test duration details
python -m pytest tests/ --durations=0
```

### Log Analysis
Tests create detailed logs for analysis:
- Mock process state transitions
- Shutdown phase progression
- Error condition handling
- Resource cleanup verification

## Test Development Guidelines

### Adding New Tests
1. Use appropriate test category (unit/integration/edge_case)
2. Follow naming convention: `test_<scenario>_<condition>`
3. Use provided fixtures for consistent setup
4. Include both positive and negative test cases
5. Add proper cleanup in fixtures

### Mock Usage
1. Use `MockProcessRegistry` for process simulation
2. Configure mock behavior to match test scenario
3. Verify mock state after test completion
4. Include error injection for negative tests

### Performance Testing
1. Mark slow tests with `@pytest.mark.slow`
2. Use timeout protection for potentially hanging operations
3. Verify resource cleanup in performance tests
4. Test concurrent operations safely

## Continuous Integration

The test suite is designed to run in CI environments:
- No external dependencies (uses mocks)
- Deterministic results (no random timing)
- Comprehensive reporting
- Clear pass/fail criteria
- Suitable for automated deployment gates

## Contributing

When adding new shutdown functionality:
1. Add corresponding unit tests
2. Add integration test scenarios
3. Consider edge cases and add appropriate tests
4. Update test documentation
5. Verify test suite still completes in reasonable time
