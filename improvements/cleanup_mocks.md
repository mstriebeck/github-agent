# Mock Cleanup Tasks

## Overview
Clean up test mocking to follow proper practices:
- Use real loggers instead of mock loggers
- Create explicit mock objects for our own classes
- Use mock.patch only for external resources or invocation counting
- Consolidate duplicated fixtures

## Tasks

### 1. Remove All Mock Logger Usage

**Files to modify:**
- [ ] `tests/conftest.py` - Remove `mock_logger` fixture (line 22)
- [ ] `tests/test_edge_cases.py` - Remove `mock_logger` fixture (line 25), use real logger
- [ ] `tests/test_health_monitor.py` - Remove `mock_logger` fixture (line 52), use real logger  
- [ ] `tests/test_exit_codes.py` - Remove `mock_logger` fixture (line 56), use real logger
- [ ] `tests/test_shutdown_manager.py` - Remove `mock_logger` fixture (line 17), use real logger
- [ ] `tests/test_shutdown_integration.py` - Remove `mock_logger` fixture (line 26), use real logger

**Action:** Replace all `mock_logger` parameters with `caplog` fixture from pytest, or use real logger instances.

### 2. Create fixtures.py for Shared Fixtures

**Create `tests/fixtures.py` with:**
- [ ] Common manager fixtures (shutdown_manager, health_monitor, etc.)
- [ ] Real logger fixtures if needed (though prefer caplog)
- [ ] Temp directory fixtures (consolidate the many temp_dir usages)

**Files with duplicated fixtures to consolidate:**
- Manager fixtures in `test_shutdown_manager.py`, `test_edge_cases.py`, `test_shutdown_integration.py`
- Temp directory setups in multiple test files

### 3. Clean Up conftest.py Unused Fixtures

**Remove unused fixtures from conftest.py:**
- [ ] `isolated_logger` (line 68) - not found in usage
- [ ] `timeout_protection` (line 97) - not found in usage  
- [ ] `mock_time` (line 190) - not found in usage
- [ ] `captured_signals` (line 210) - not found in usage

**Keep these conftest.py fixtures:**
- `temp_dir` - used by other fixtures
- `process_registry` - used in integration tests
- `cleanup_threads` - autouse cleanup

### 4. Replace Internal Method Mocking with Explicit Mocks

**Priority files to refactor:**

#### test_shutdown_manager.py
- [ ] Lines 99-103: Replace `patch.object` on internal methods (`_shutdown_all_workers`, `disconnect_all`, `cleanup_all`, `_verify_clean_shutdown`) with explicit mock objects
- [ ] Lines 133-136: Same pattern for worker shutdown
- [ ] Lines 164-166: Same pattern for shutdown with issues

#### test_shutdown_integration.py  
- [ ] Lines 86-89: Replace patching of internal component methods
- [ ] Lines 182-186: Same pattern
- [ ] Lines 263-267: Same pattern

#### test_health_monitor.py
- [ ] Lines 338, 364: Replace `patch.object` on internal `_update_resource_status`

**Approach:** Create abstract base classes for components that need mocking, then create explicit mock implementations.

### 5. Create Abstract Base Classes for Mockable Components

**New files to create:**
- [ ] Abstract base class for client tracker
- [ ] Abstract base class for resource tracker  
- [ ] Abstract base class for health monitor
- [ ] Mock implementations of above classes

**Pattern:**
```python
# abstracts/client_tracker.py
class AbstractClientTracker(ABC):
    @abstractmethod
    async def disconnect_all(self) -> bool:
        pass

# mocks/client_tracker.py  
class MockClientTracker(AbstractClientTracker):
    def __init__(self):
        self.disconnect_all_called = False
        self.disconnect_all_result = True
    
    async def disconnect_all(self) -> bool:
        self.disconnect_all_called = True
        return self.disconnect_all_result
```

### 6. Keep Appropriate External Resource Mocks

**These are correct and should remain:**
- [ ] `patch.dict(os.environ)` - environment variables
- [ ] `@patch('psutil.Process')` - system resources  
- [ ] `@patch('health_monitor.psutil.Process')` - external psutil calls

### 7. Acceptable Invocation Tracking

**These mock.patch usages are OK (just counting calls/side effects):**
- [ ] `test_edge_cases.py` line 43 - tracking shutdown calls
- [ ] `test_health_monitor.py` line 388 - monitoring loop side effects
- [ ] `test_worker_manager.py` various lines - port availability checking

### 8. Update Test Assertions

**After removing mock loggers:**
- [ ] Replace `mock_logger.info.assert_called_with()` with `caplog` assertions
- [ ] Replace `mock_logger.error.assert_called_once_with()` with caplog checks
- [ ] Update all logger assertion patterns

**Pattern:**
```python
# Before
mock_logger.info.assert_called_with("Server status changed: starting -> running")

# After  
assert "Server status changed: starting -> running" in caplog.text
# or
assert any("Server status changed" in record.message for record in caplog.records)
```

### 9. Dependency Injection Updates

**Files that need dependency injection updates:**
- [ ] Core classes that currently expect concrete dependencies
- [ ] Update constructors to accept abstract base classes
- [ ] Update production code to inject real implementations
- [ ] Update tests to inject mock implementations

## Testing Strategy

1. **Phase 1:** Remove mock loggers, use caplog
2. **Phase 2:** Create abstract base classes  
3. **Phase 3:** Create explicit mock implementations
4. **Phase 4:** Replace patch.object calls with explicit mocks
5. **Phase 5:** Clean up duplicated fixtures

## Success Criteria

- [ ] No `Mock()` or `MagicMock()` usage for internal classes
- [ ] No `mock_logger` fixtures anywhere
- [ ] `mock.patch` only used for external resources or invocation counting
- [ ] All tests still pass
- [ ] Fixtures consolidated in `fixtures.py`
- [ ] Unused conftest.py fixtures removed
