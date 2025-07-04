"""
Unit tests for Python symbol extractor functionality.
"""

import tempfile
from pathlib import Path

import pytest

from python_symbol_extractor import (
    AbstractSymbolExtractor,
    MockSymbolExtractor,
    PythonSymbolExtractor,
)
from symbol_storage import Symbol


class TestPythonSymbolExtractor:
    """Test the PythonSymbolExtractor class."""

    @pytest.fixture
    def extractor(self):
        """Create a PythonSymbolExtractor for testing."""
        return PythonSymbolExtractor()

    def test_extract_simple_function(self, extractor):
        """Test extracting a simple function."""
        source = '''
def hello_world():
    """Say hello to the world."""
    print("Hello, World!")
'''
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        assert len(symbols) == 1
        assert symbols[0].name == "hello_world"
        assert symbols[0].kind == "function"
        assert symbols[0].line_number == 2
        assert symbols[0].docstring == "Say hello to the world."

    def test_extract_simple_class(self, extractor):
        """Test extracting a simple class."""
        source = '''
class TestClass:
    """A test class."""
    pass
'''
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        assert len(symbols) == 1
        assert symbols[0].name == "TestClass"
        assert symbols[0].kind == "class"
        assert symbols[0].line_number == 2
        assert symbols[0].docstring == "A test class."

    def test_extract_class_with_methods(self, extractor):
        """Test extracting class with methods."""
        source = '''
class Calculator:
    """A simple calculator."""

    def add(self, a, b):
        """Add two numbers."""
        return a + b

    def multiply(self, a, b):
        return a * b

    @property
    def name(self):
        """Get calculator name."""
        return "Calculator"

    @classmethod
    def create_default(cls):
        """Create default calculator."""
        return cls()

    @staticmethod
    def is_number(value):
        """Check if value is a number."""
        return isinstance(value, (int, float))
'''
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        # Should find: class, add method, multiply method, name property,
        # create_default classmethod, is_number staticmethod
        assert len(symbols) == 6

        class_symbol = symbols[0]
        assert class_symbol.name == "Calculator"
        assert class_symbol.kind == "class"
        assert class_symbol.docstring == "A simple calculator."

        add_method = symbols[1]
        assert add_method.name == "Calculator.add"
        assert add_method.kind == "method"
        assert add_method.docstring == "Add two numbers."

        multiply_method = symbols[2]
        assert multiply_method.name == "Calculator.multiply"
        assert multiply_method.kind == "method"

        property_symbol = symbols[3]
        assert property_symbol.name == "Calculator.name"
        assert property_symbol.kind == "property"
        assert property_symbol.docstring == "Get calculator name."

        classmethod_symbol = symbols[4]
        assert classmethod_symbol.name == "Calculator.create_default"
        assert classmethod_symbol.kind == "classmethod"

        staticmethod_symbol = symbols[5]
        assert staticmethod_symbol.name == "Calculator.is_number"
        assert staticmethod_symbol.kind == "staticmethod"

    def test_extract_nested_classes(self, extractor):
        """Test extracting nested classes."""
        source = '''
class Outer:
    """Outer class."""

    class Inner:
        """Inner class."""

        def inner_method(self):
            """Inner method."""
            pass

        class DeeplyNested:
            """Deeply nested class."""
            pass

    def outer_method(self):
        """Outer method."""
        pass
'''
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        assert len(symbols) == 5

        # Check nested naming
        outer_class = symbols[0]
        assert outer_class.name == "Outer"
        assert outer_class.kind == "class"

        inner_class = symbols[1]
        assert inner_class.name == "Outer.Inner"
        assert inner_class.kind == "class"

        inner_method = symbols[2]
        assert inner_method.name == "Outer.Inner.inner_method"
        assert inner_method.kind == "method"

        deeply_nested = symbols[3]
        assert deeply_nested.name == "Outer.Inner.DeeplyNested"
        assert deeply_nested.kind == "class"

        outer_method = symbols[4]
        assert outer_method.name == "Outer.outer_method"
        assert outer_method.kind == "method"

    def test_extract_nested_functions(self, extractor):
        """Test extracting nested functions."""
        source = '''
def outer_function():
    """Outer function."""

    def inner_function():
        """Inner function."""

        def deeply_nested():
            """Deeply nested function."""
            pass

        return deeply_nested

    return inner_function

def another_function():
    """Another top-level function."""
    pass
'''
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        assert len(symbols) == 4

        outer_func = symbols[0]
        assert outer_func.name == "outer_function"
        assert outer_func.kind == "function"

        inner_func = symbols[1]
        assert inner_func.name == "outer_function.inner_function"
        assert inner_func.kind == "function"

        deeply_nested = symbols[2]
        assert deeply_nested.name == "outer_function.inner_function.deeply_nested"
        assert deeply_nested.kind == "function"

        another_func = symbols[3]
        assert another_func.name == "another_function"
        assert another_func.kind == "function"

    def test_extract_variables_and_constants(self, extractor):
        """Test extracting variables and constants."""
        source = '''
# Module-level constants and variables
MAX_SIZE = 100
API_KEY = "secret"
debug_mode = True
user_count = 0

class Config:
    """Configuration class."""

    DEFAULT_TIMEOUT = 30
    base_url = "https://api.example.com"

    def __init__(self):
        self.instance_var = "value"
        self.INSTANCE_CONSTANT = 42

def setup():
    """Setup function."""
    local_var = "local"
    LOCAL_CONSTANT = 123
'''
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        # Filter symbols by kind
        constants = [s for s in symbols if s.kind == "constant"]
        variables = [s for s in symbols if s.kind == "variable"]

        # Module-level constants
        constant_names = [s.name for s in constants]
        assert "MAX_SIZE" in constant_names
        assert "API_KEY" in constant_names

        # Module-level variables
        variable_names = [s.name for s in variables]
        assert "debug_mode" in variable_names
        assert "user_count" in variable_names

        # Class-level constants and variables
        assert "Config.DEFAULT_TIMEOUT" in constant_names
        assert "Config.base_url" in variable_names

        # Instance variables (in __init__)
        assert "Config.__init__.instance_var" in variable_names
        assert "Config.__init__.INSTANCE_CONSTANT" in constant_names

        # Local variables in function
        assert "setup.local_var" in variable_names
        assert "setup.LOCAL_CONSTANT" in constant_names

    def test_extract_imports(self, extractor):
        """Test extracting import statements."""
        source = """
import os
import sys as system
from pathlib import Path
from typing import List, Dict
from collections import defaultdict as dd
from .local_module import local_function
"""
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        module_symbols = [s for s in symbols if s.kind == "module"]
        assert len(module_symbols) == 7

        names = [s.name for s in module_symbols]
        assert "os" in names
        assert "system" in names  # alias
        assert "Path" in names
        assert "List" in names
        assert "Dict" in names
        assert "dd" in names  # alias for defaultdict
        assert "local_function" in names

    def test_extract_async_functions(self, extractor):
        """Test extracting async functions."""
        source = '''
import asyncio

class AsyncHandler:
    """Async handler class."""

    async def handle_request(self):
        """Handle async request."""
        await asyncio.sleep(1)

    async def process_data(self, data):
        """Process data asynchronously."""
        return data

async def main():
    """Main async function."""
    handler = AsyncHandler()
    await handler.handle_request()
'''
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        # Filter functions
        functions = [s for s in symbols if s.kind in ["function", "method"]]

        # Should find: handle_request (method), process_data (method), main (function)
        # Plus the import and class
        func_names = [s.name for s in functions]
        assert "AsyncHandler.handle_request" in func_names
        assert "AsyncHandler.process_data" in func_names
        assert "main" in func_names

    def test_extract_from_file(self, extractor):
        """Test extracting symbols from a real file."""
        source = '''
"""Test module docstring."""

def test_function():
    """Test function."""
    return True

class TestClass:
    """Test class."""

    def test_method(self):
        """Test method."""
        return "test"
'''

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(source)
            temp_path = f.name

        try:
            symbols = extractor.extract_from_file(temp_path, "test-repo")

            assert len(symbols) == 3  # function, class, method

            function_symbol = symbols[0]
            assert function_symbol.name == "test_function"
            assert function_symbol.kind == "function"
            assert function_symbol.file_path == temp_path
            assert function_symbol.repository_id == "test-repo"

        finally:
            Path(temp_path).unlink()

    def test_error_handling_syntax_error(self, extractor):
        """Test handling of syntax errors."""
        invalid_source = """
def broken_function(
    # Missing closing parenthesis
    pass
"""
        with pytest.raises(SyntaxError):
            extractor.extract_from_source(invalid_source, "test.py", "test-repo")

    def test_error_handling_file_not_found(self, extractor):
        """Test handling of missing files."""
        with pytest.raises(FileNotFoundError):
            extractor.extract_from_file("nonexistent.py", "test-repo")

    def test_empty_file(self, extractor):
        """Test extracting from an empty file."""
        source = ""
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")
        assert len(symbols) == 0

    def test_annotated_assignments(self, extractor):
        """Test extracting annotated assignments."""
        source = """
name: str = "John"
age: int = 30
CONFIG: dict[str, str] = {"key": "value"}

class Person:
    name: str
    age: int = 0
    SPECIES: str = "Homo sapiens"
"""
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        # Check module-level annotated assignments
        name_var = next(s for s in symbols if s.name == "name")
        assert name_var.kind == "variable"

        config_const = next(s for s in symbols if s.name == "CONFIG")
        assert config_const.kind == "constant"

    def test_scope_tracking_reset(self, extractor):
        """Test that scope tracking resets between extractions."""
        # First extraction
        source1 = """
class FirstClass:
    def first_method(self):
        pass
"""
        symbols1 = extractor.extract_from_source(source1, "file1.py", "repo1")

        # Second extraction should not be affected by first
        source2 = """
class SecondClass:
    def second_method(self):
        pass
"""
        symbols2 = extractor.extract_from_source(source2, "file2.py", "repo2")

        # Check that scopes are correct and isolated
        first_method = next(s for s in symbols1 if s.name == "FirstClass.first_method")
        assert first_method.file_path == "file1.py"
        assert first_method.repository_id == "repo1"

        second_method = next(
            s for s in symbols2 if s.name == "SecondClass.second_method"
        )
        assert second_method.file_path == "file2.py"
        assert second_method.repository_id == "repo2"


class TestMockSymbolExtractor:
    """Test the MockSymbolExtractor class."""

    def test_mock_extractor_with_predefined_symbols(self):
        """Test mock extractor returns predefined symbols."""
        test_symbols = [
            Symbol("test_func", "function", "test.py", 1, 0, "test-repo"),
            Symbol("TestClass", "class", "test.py", 5, 0, "test-repo"),
        ]

        mock = MockSymbolExtractor(test_symbols)

        # Should return the same symbols for any input
        result1 = mock.extract_from_file("any_file.py", "any_repo")
        result2 = mock.extract_from_source("any source", "any_file.py", "any_repo")

        assert len(result1) == 2
        assert len(result2) == 2
        assert result1[0].name == "test_func"
        assert result2[0].name == "test_func"

    def test_mock_extractor_empty(self):
        """Test mock extractor with no predefined symbols."""
        mock = MockSymbolExtractor()

        result = mock.extract_from_file("test.py", "test-repo")
        assert len(result) == 0

    def test_abstract_interface_compliance(self):
        """Test that both extractors implement the abstract interface."""
        assert isinstance(PythonSymbolExtractor(), AbstractSymbolExtractor)
        assert isinstance(MockSymbolExtractor(), AbstractSymbolExtractor)

        # Check that all abstract methods are implemented
        extractor = PythonSymbolExtractor()
        mock = MockSymbolExtractor()

        assert hasattr(extractor, "extract_from_file")
        assert hasattr(extractor, "extract_from_source")
        assert hasattr(mock, "extract_from_file")
        assert hasattr(mock, "extract_from_source")


class TestComplexPythonConstructs:
    """Test complex Python language constructs."""

    @pytest.fixture
    def extractor(self):
        """Create a PythonSymbolExtractor for testing."""
        return PythonSymbolExtractor()

    def test_multiple_decorators(self, extractor):
        """Test functions with multiple decorators."""
        source = '''
from functools import wraps

def decorator1(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper

def decorator2(func):
    return func

class MyClass:
    @decorator1
    @decorator2
    @property
    def complex_property(self):
        """A property with multiple decorators."""
        return self._value

    @staticmethod
    @decorator1
    def complex_static(value):
        """Static method with decorators."""
        return value
'''
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        # Should still detect property despite multiple decorators
        prop = next(s for s in symbols if s.name == "MyClass.complex_property")
        assert prop.kind == "property"

        # Should detect staticmethod despite decorators
        static = next(s for s in symbols if s.name == "MyClass.complex_static")
        assert static.kind == "staticmethod"

    def test_class_inheritance(self, extractor):
        """Test classes with inheritance."""
        source = '''
class BaseClass:
    """Base class."""

    def base_method(self):
        """Base method."""
        pass

class DerivedClass(BaseClass):
    """Derived class."""

    def derived_method(self):
        """Derived method."""
        pass

    def base_method(self):
        """Override base method."""
        super().base_method()

class MultipleInheritance(BaseClass, DerivedClass):
    """Multiple inheritance."""
    pass
'''
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        # Should extract all classes regardless of inheritance
        base_class = next(s for s in symbols if s.name == "BaseClass")
        assert base_class.kind == "class"

        derived_class = next(s for s in symbols if s.name == "DerivedClass")
        assert derived_class.kind == "class"

        multiple_class = next(s for s in symbols if s.name == "MultipleInheritance")
        assert multiple_class.kind == "class"

    def test_generators_and_comprehensions(self, extractor):
        """Test that generators and comprehensions don't interfere."""
        source = '''
data = [i for i in range(10)]
squares = {i: i**2 for i in range(5)}
evens = (i for i in range(10) if i % 2 == 0)

def generator_function():
    """A generator function."""
    for i in range(5):
        yield i * 2

class DataProcessor:
    def process_list(self):
        return [x * 2 for x in self.data]
'''
        symbols = extractor.extract_from_source(source, "test.py", "test-repo")

        # Should extract variables and functions correctly
        var_names = [s.name for s in symbols if s.kind == "variable"]
        assert "data" in var_names
        assert "squares" in var_names
        assert "evens" in var_names

        gen_func = next(s for s in symbols if s.name == "generator_function")
        assert gen_func.kind == "function"
        assert gen_func.docstring == "A generator function."
