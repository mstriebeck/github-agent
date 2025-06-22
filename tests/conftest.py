"""
Pytest configuration and shared fixtures for shutdown system tests.
"""

import pytest
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock
from test_abstracts import MockProcessRegistry


@pytest.fixture(scope="session")
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def mock_logger():
    """Create a mock logger with common assertions."""
    logger = Mock()
    
    # Add convenience methods for checking log calls
    def assert_logged(level, message_contains):
        """Assert that a message was logged at the specified level."""
        method = getattr(logger, level.lower())
        calls = method.call_args_list
        for call in calls:
            if message_contains in str(call):
                return True
        raise AssertionError(f"Expected {level} log containing '{message_contains}' not found")
    
    def assert_not_logged(level, message_contains):
        """Assert that a message was NOT logged at the specified level."""
        method = getattr(logger, level.lower())
        calls = method.call_args_list
        for call in calls:
            if message_contains in str(call):
                raise AssertionError(f"Unexpected {level} log containing '{message_contains}' found")
        return True
    
    logger.assert_logged = assert_logged
    logger.assert_not_logged = assert_not_logged
    
    return logger


@pytest.fixture
def process_registry():
    """Create a fresh process registry for each test."""
    registry = MockProcessRegistry()
    yield registry
    registry.cleanup_all()


@pytest.fixture
def temp_health_file(temp_dir):
    """Create a temporary health file path."""
    health_file = temp_dir / "health.json"
    yield str(health_file)
    # Cleanup is automatic with temp_dir


@pytest.fixture
def isolated_logger():
    """Create a real logger for tests that need actual logging."""
    import logging
    logger = logging.getLogger(f"test_{time.time()}")
    logger.setLevel(logging.DEBUG)
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Add memory handler for test verification
    log_records = []
    
    class TestHandler(logging.Handler):
        def emit(self, record):
            log_records.append(record)
    
    handler = TestHandler()
    logger.addHandler(handler)
    
    # Add log_records as an attribute for test access
    logger.log_records = log_records
    
    yield logger
    
    # Cleanup
    logger.handlers.clear()


@pytest.fixture
def timeout_protection():
    """Provide timeout protection for tests that might hang."""
    timeout_seconds = 30  # Default test timeout
    
    def run_with_timeout(func, *args, **kwargs):
        """Run a function with timeout protection."""
        result = [None]
        exception = [None]
        
        def target():
            try:
                result[0] = func(*args, **kwargs)
            except Exception as e:
                exception[0] = e
        
        thread = threading.Thread(target=target)
        thread.daemon = True  # Dies with main thread
        thread.start()
        thread.join(timeout=timeout_seconds)
        
        if thread.is_alive():
            raise TimeoutError(f"Function {func.__name__} timed out after {timeout_seconds}s")
        
        if exception[0]:
            raise exception[0]
        
        return result[0]
    
    return run_with_timeout


@pytest.fixture(autouse=True)
def cleanup_threads():
    """Automatically cleanup any daemon threads after each test."""
    # Record initial thread count
    initial_threads = set(threading.enumerate())
    
    yield
    
    # Wait for test threads to finish
    max_wait = 5.0  # seconds
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        current_threads = set(threading.enumerate())
        test_threads = current_threads - initial_threads
        
        # Filter out daemon threads and threads that are finishing
        active_test_threads = [
            t for t in test_threads 
            if t.is_alive() and not t.daemon and t != threading.current_thread()
        ]
        
        if not active_test_threads:
            break
            
        time.sleep(0.1)
    
    # Force cleanup any remaining threads
    current_threads = set(threading.enumerate())
    remaining_threads = current_threads - initial_threads
    for thread in remaining_threads:
        if thread.is_alive() and not thread.daemon and thread != threading.current_thread():
            try:
                # Try to join with short timeout
                thread.join(timeout=0.1)
            except:
                pass  # Best effort cleanup


class MockTimeProvider:
    """Mock time provider for testing time-dependent behavior."""
    
    def __init__(self, start_time=0.0):
        self.current_time = start_time
        self._lock = threading.Lock()
    
    def time(self):
        """Get current mock time."""
        with self._lock:
            return self.current_time
    
    def advance(self, seconds):
        """Advance mock time by specified seconds."""
        with self._lock:
            self.current_time += seconds
    
    def sleep(self, seconds):
        """Mock sleep that advances time instead of waiting."""
        self.advance(seconds)


@pytest.fixture
def mock_time():
    """Provide mock time for testing time-dependent behavior."""
    mock_time_provider = MockTimeProvider()
    
    # Patch time.time and time.sleep
    import time
    original_time = time.time
    original_sleep = time.sleep
    
    time.time = mock_time_provider.time
    time.sleep = mock_time_provider.sleep
    
    yield mock_time_provider
    
    # Restore original functions
    time.time = original_time
    time.sleep = original_sleep


@pytest.fixture
def captured_signals():
    """Capture signals sent during test for verification."""
    captured = []
    
    import signal
    original_signal = signal.signal
    
    def mock_signal(sig, handler):
        captured.append(('register', sig, handler))
        return original_signal(sig, handler)
    
    signal.signal = mock_signal
    
    yield captured
    
    # Restore
    signal.signal = original_signal


# Pytest configuration
def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (may take several seconds)"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "edge_case: marks tests as edge case tests"
    )


def pytest_collection_modifyitems(config, items):
    """Automatically mark tests based on their location."""
    for item in items:
        # Mark integration tests
        if "integration" in item.fspath.basename:
            item.add_marker(pytest.mark.integration)
        
        # Mark edge case tests
        if "edge_case" in item.fspath.basename:
            item.add_marker(pytest.mark.edge_case)
        
        # Mark slow tests (those with certain patterns)
        if any(keyword in item.name.lower() for keyword in ['concurrent', 'timeout', 'slow']):
            item.add_marker(pytest.mark.slow)


# Custom assertions for shutdown testing
def assert_clean_shutdown(shutdown_result, exit_code_manager, expected_exit_code=None):
    """Assert that a shutdown completed cleanly."""
    assert shutdown_result is True, "Shutdown should have succeeded"
    
    if expected_exit_code:
        actual_exit_code = exit_code_manager.determine_exit_code("test")
        assert actual_exit_code == expected_exit_code, \
            f"Expected exit code {expected_exit_code}, got {actual_exit_code}"
    
    summary = exit_code_manager.get_exit_summary()
    assert summary["total_problems"] == 0, \
        f"Expected clean shutdown but found problems: {summary}"


def assert_shutdown_with_issues(shutdown_result, exit_code_manager, expected_problems=None):
    """Assert that a shutdown completed but had issues."""
    # Shutdown might succeed or fail depending on severity
    if shutdown_result is False:
        # Failed shutdown should have critical issues
        summary = exit_code_manager.get_exit_summary()
        assert summary["total_problems"] > 0, "Failed shutdown should have reported problems"
    
    if expected_problems:
        summary = exit_code_manager.get_exit_summary()
        assert summary["total_problems"] >= expected_problems, \
            f"Expected at least {expected_problems} problems, got {summary['total_problems']}"


# Add to pytest namespace for easy import
pytest.assert_clean_shutdown = assert_clean_shutdown
pytest.assert_shutdown_with_issues = assert_shutdown_with_issues
