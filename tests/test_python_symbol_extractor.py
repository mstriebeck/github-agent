"""
Unit tests for Python symbol extractor functionality.
"""

import tempfile
from pathlib import Path

import pytest

from python_symbol_extractor import (
    AbstractSymbolExtractor,
    PythonSymbolExtractor,
)
from symbol_storage import SymbolKind


class TestPythonSymbolExtractor:
    """Test the PythonSymbolExtractor class."""

    # Use python_symbol_extractor fixture from conftest.py

    def test_extract_simple_function(self, python_symbol_extractor):
        """Test extracting a simple function."""
        source = '''
def hello_world():
    """Say hello to the world."""
    print("Hello, World!")
'''
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        assert len(symbols) == 1
        assert symbols[0].name == "hello_world"
        assert symbols[0].kind == SymbolKind.FUNCTION
        assert symbols[0].line_number == 2
        assert symbols[0].docstring == "Say hello to the world."

    def test_extract_simple_class(self, python_symbol_extractor):
        """Test extracting a simple class."""
        source = '''
class TestClass:
    """A test class."""
    pass
'''
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        assert len(symbols) == 1
        assert symbols[0].name == "TestClass"
        assert symbols[0].kind == SymbolKind.CLASS
        assert symbols[0].line_number == 2
        assert symbols[0].docstring == "A test class."

    def test_extract_class_with_methods(self, python_symbol_extractor):
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
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        # Should find: class, add method, multiply method, name property,
        # create_default classmethod, is_number staticmethod
        assert len(symbols) == 6

        class_symbol = symbols[0]
        assert class_symbol.name == "Calculator"
        assert class_symbol.kind == SymbolKind.CLASS
        assert class_symbol.docstring == "A simple calculator."

        add_method = symbols[1]
        assert add_method.name == "Calculator.add"
        assert add_method.kind == SymbolKind.METHOD
        assert add_method.docstring == "Add two numbers."

        multiply_method = symbols[2]
        assert multiply_method.name == "Calculator.multiply"
        assert multiply_method.kind == SymbolKind.METHOD

        property_symbol = symbols[3]
        assert property_symbol.name == "Calculator.name"
        assert property_symbol.kind == SymbolKind.PROPERTY
        assert property_symbol.docstring == "Get calculator name."

        classmethod_symbol = symbols[4]
        assert classmethod_symbol.name == "Calculator.create_default"
        assert classmethod_symbol.kind == SymbolKind.CLASSMETHOD

        staticmethod_symbol = symbols[5]
        assert staticmethod_symbol.name == "Calculator.is_number"
        assert staticmethod_symbol.kind == SymbolKind.STATICMETHOD

    def test_extract_nested_classes(self, python_symbol_extractor):
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
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        assert len(symbols) == 5

        # Check nested naming
        outer_class = symbols[0]
        assert outer_class.name == "Outer"
        assert outer_class.kind == SymbolKind.CLASS

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

    def test_extract_nested_functions(self, python_symbol_extractor):
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
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

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

    def test_extract_variables_and_constants(self, python_symbol_extractor):
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
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

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

    def test_extract_imports(self, python_symbol_extractor):
        """Test extracting import statements."""
        source = """
import os
import sys as system
from pathlib import Path
from typing import List, Dict
from collections import defaultdict as dd
from .local_module import local_function
"""
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

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

    def test_extract_async_functions(self, python_symbol_extractor):
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
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        # Filter functions
        functions = [
            s for s in symbols if s.kind in [SymbolKind.FUNCTION, SymbolKind.METHOD]
        ]

        # Should find: handle_request (method), process_data (method), main (function)
        # Plus the import and class
        func_names = [s.name for s in functions]
        assert "AsyncHandler.handle_request" in func_names
        assert "AsyncHandler.process_data" in func_names
        assert "main" in func_names

    def test_extract_from_file(self, python_symbol_extractor):
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
            symbols = python_symbol_extractor.extract_from_file(temp_path, "test-repo")

            assert len(symbols) == 3  # function, class, method

            function_symbol = symbols[0]
            assert function_symbol.name == "test_function"
            assert function_symbol.kind == SymbolKind.FUNCTION
            assert function_symbol.file_path == temp_path
            assert function_symbol.repository_id == "test-repo"

        finally:
            Path(temp_path).unlink()

    def test_error_handling_syntax_error(self, python_symbol_extractor):
        """Test handling of syntax errors."""
        invalid_source = """
def broken_function(
    # Missing closing parenthesis
    pass
"""
        with pytest.raises(SyntaxError):
            python_symbol_extractor.extract_from_source(
                invalid_source, "test.py", "test-repo"
            )

    def test_error_handling_file_not_found(self, python_symbol_extractor):
        """Test handling of missing files."""
        with pytest.raises(FileNotFoundError):
            python_symbol_extractor.extract_from_file("nonexistent.py", "test-repo")

    def test_empty_file(self, python_symbol_extractor):
        """Test extracting from an empty file."""
        source = ""
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )
        assert len(symbols) == 0

    def test_annotated_assignments(self, python_symbol_extractor):
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
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        # Check module-level annotated assignments
        name_var = next(s for s in symbols if s.name == "name")
        assert name_var.kind == "variable"

        config_const = next(s for s in symbols if s.name == "CONFIG")
        assert config_const.kind == "constant"

    def test_scope_tracking_reset(self, python_symbol_extractor):
        """Test that scope tracking resets between extractions."""
        # First extraction
        source1 = """
class FirstClass:
    def first_method(self):
        pass
"""
        symbols1 = python_symbol_extractor.extract_from_source(
            source1, "file1.py", "repo1"
        )

        # Second extraction should not be affected by first
        source2 = """
class SecondClass:
    def second_method(self):
        pass
"""
        symbols2 = python_symbol_extractor.extract_from_source(
            source2, "file2.py", "repo2"
        )

        # Check that scopes are correct and isolated
        first_method = next(s for s in symbols1 if s.name == "FirstClass.first_method")
        assert first_method.file_path == "file1.py"
        assert first_method.repository_id == "repo1"

        second_method = next(
            s for s in symbols2 if s.name == "SecondClass.second_method"
        )
        assert second_method.file_path == "file2.py"
        assert second_method.repository_id == "repo2"

    def test_nested_imports(self, python_symbol_extractor):
        """Test extracting imports nested inside functions and methods."""
        source = """
import os  # module level

class DataProcessor:
    def process_data(self):
        import json  # nested in method
        from pathlib import Path as PathLib  # nested in method with alias
        return json.dumps({})

def helper_function():
    import sys  # nested in function
    from collections import defaultdict as dd  # nested in function with alias
    return sys.version

def outer_function():
    def inner_function():
        import re  # deeply nested
        return re.compile(r"test")
    return inner_function
"""
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        import_symbols = [s for s in symbols if s.kind == "module"]
        import_names = [s.name for s in import_symbols]

        # Module-level import
        assert "os" in import_names

        # Method-level imports
        assert "DataProcessor.process_data.json" in import_names
        assert "DataProcessor.process_data.PathLib" in import_names

        # Function-level imports
        assert "helper_function.sys" in import_names
        assert "helper_function.dd" in import_names

        # Deeply nested import
        assert "outer_function.inner_function.re" in import_names

        # Verify total count
        assert len(import_symbols) == 6

    def test_mock_extractor_functionality(self, mock_symbol_extractor):
        """Test mock extractor returns consistent results."""
        from symbol_storage import Symbol

        # Set up test data explicitly in the test
        test_symbols = [
            Symbol("test_function", SymbolKind.FUNCTION, "test.py", 1, 0, "test-repo"),
            Symbol("TestClass", SymbolKind.CLASS, "test.py", 5, 0, "test-repo"),
        ]
        mock_symbol_extractor.symbols = test_symbols

        # Mock should return predefined symbols regardless of input
        result1 = mock_symbol_extractor.extract_from_file("any_file.py", "any_repo")
        result2 = mock_symbol_extractor.extract_from_source(
            "any source", "any_file.py", "any_repo"
        )

        assert len(result1) == 2
        assert len(result2) == 2
        assert result1[0].name == "test_function"
        assert result2[0].name == "test_function"

    def test_abstract_interface_compliance(self, mock_symbol_extractor):
        """Test that both extractors implement the abstract interface."""
        assert isinstance(PythonSymbolExtractor(), AbstractSymbolExtractor)
        assert isinstance(mock_symbol_extractor, AbstractSymbolExtractor)

        # Check that all abstract methods are implemented
        extractor = PythonSymbolExtractor()
        assert hasattr(extractor, "extract_from_file")
        assert hasattr(extractor, "extract_from_source")
        assert hasattr(mock_symbol_extractor, "extract_from_file")
        assert hasattr(mock_symbol_extractor, "extract_from_source")


class TestComplexPythonConstructs:
    """Test complex Python language constructs."""

    @pytest.fixture
    def extractor(self):
        """Create a PythonSymbolExtractor for testing."""
        return PythonSymbolExtractor()

    def test_multiple_decorators(self, python_symbol_extractor):
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
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        # Should still detect property despite multiple decorators
        prop = next(s for s in symbols if s.name == "MyClass.complex_property")
        assert prop.kind == "property"

        # Should detect staticmethod despite decorators
        static = next(s for s in symbols if s.name == "MyClass.complex_static")
        assert static.kind == "staticmethod"

    def test_class_inheritance(self, python_symbol_extractor):
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
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        # Should extract all classes regardless of inheritance
        base_class = next(s for s in symbols if s.name == "BaseClass")
        assert base_class.kind == "class"

        derived_class = next(s for s in symbols if s.name == "DerivedClass")
        assert derived_class.kind == "class"

        multiple_class = next(s for s in symbols if s.name == "MultipleInheritance")
        assert multiple_class.kind == "class"

    def test_generators_and_comprehensions(self, python_symbol_extractor):
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
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        # Should extract variables and functions correctly
        var_names = [s.name for s in symbols if s.kind == "variable"]
        assert "data" in var_names
        assert "squares" in var_names
        assert "evens" in var_names

        gen_func = next(s for s in symbols if s.name == "generator_function")
        assert gen_func.kind == "function"
        assert gen_func.docstring == "A generator function."

    def test_property_setters_deleters(self, python_symbol_extractor):
        """Test extraction of property setters and deleters."""
        source = '''
class PropertyExample:
    def __init__(self):
        self._value = 0

    @property
    def value(self):
        """Get the value."""
        return self._value

    @value.setter
    def value(self, new_value):
        """Set the value."""
        self._value = new_value

    @value.deleter
    def value(self):
        """Delete the value."""
        del self._value
'''
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        # Find property-related symbols
        prop_getter = next(
            s
            for s in symbols
            if s.name == "PropertyExample.value" and s.kind == "property"
        )
        assert prop_getter.docstring == "Get the value."

        prop_setter = next(
            s
            for s in symbols
            if s.name == "PropertyExample.value" and s.kind == "setter"
        )
        assert prop_setter.docstring == "Set the value."

        prop_deleter = next(
            s
            for s in symbols
            if s.name == "PropertyExample.value" and s.kind == "deleter"
        )
        assert prop_deleter.docstring == "Delete the value."

    def test_walrus_operator(self, python_symbol_extractor):
        """Test extraction of walrus operator assignments."""
        source = """
def process_data():
    # Simple walrus operator
    if (n := len([1, 2, 3])) > 2:
        print(f"Length is {n}")

    # Nested walrus operator
    while (line := input().strip()):
        if (length := len(line)) > 10:
            print(f"Long line: {length}")

    # Multiple walrus operators in same expression
    if (a := 5) > 2 and (b := 10) < 20:
        result = a + b
"""
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        variable_names = [s.name for s in symbols if s.kind == "variable"]
        assert "process_data.n" in variable_names
        assert "process_data.line" in variable_names
        assert "process_data.length" in variable_names
        assert "process_data.a" in variable_names
        assert "process_data.b" in variable_names

    def test_context_manager_variables(self, python_symbol_extractor):
        """Test extraction of context manager variables."""
        source = """
def file_operations():
    # Simple context manager
    with open('file.txt') as f:
        content = f.read()

    # Multiple context managers
    with open('input.txt') as infile, open('output.txt') as outfile:
        data = infile.read()
        outfile.write(data)

    # Nested context managers
    with open('outer.txt') as outer:
        with open('inner.txt') as inner:
            combined = outer.read() + inner.read()

async def async_file_operations():
    # Async context manager
    async with aiofiles.open('async_file.txt') as af:
        async_content = await af.read()
"""
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        variable_names = [s.name for s in symbols if s.kind == "variable"]

        # Sync context manager variables
        assert "file_operations.f" in variable_names
        assert "file_operations.infile" in variable_names
        assert "file_operations.outfile" in variable_names
        assert "file_operations.outer" in variable_names
        assert "file_operations.inner" in variable_names

        # Async context manager variables
        assert "async_file_operations.af" in variable_names

    def test_multiple_assignment_and_unpacking(self, python_symbol_extractor):
        """Test extraction of multiple assignment and tuple unpacking."""
        source = """
def assignment_examples():
    # Simple multiple assignment
    a, b, c = 1, 2, 3

    # List unpacking
    [x, y, z] = [10, 20, 30]

    # Tuple unpacking with starred expression
    first, *middle, last = [1, 2, 3, 4, 5]

    # Nested unpacking
    (p, q), (r, s) = [(1, 2), (3, 4)]

    # Mixed patterns
    name, (age, height), *extras = ("John", (25, 180), "extra1", "extra2")

class UnpackingInClass:
    def __init__(self):
        # Instance variable unpacking
        self.x, self.y = 10, 20
"""
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        variable_names = [s.name for s in symbols if s.kind == "variable"]

        # Simple multiple assignment
        assert "assignment_examples.a" in variable_names
        assert "assignment_examples.b" in variable_names
        assert "assignment_examples.c" in variable_names

        # List unpacking
        assert "assignment_examples.x" in variable_names
        assert "assignment_examples.y" in variable_names
        assert "assignment_examples.z" in variable_names

        # Tuple unpacking with starred
        assert "assignment_examples.first" in variable_names
        assert "assignment_examples.middle" in variable_names
        assert "assignment_examples.last" in variable_names

        # Nested unpacking
        assert "assignment_examples.p" in variable_names
        assert "assignment_examples.q" in variable_names
        assert "assignment_examples.r" in variable_names
        assert "assignment_examples.s" in variable_names

        # Mixed patterns
        assert "assignment_examples.name" in variable_names
        assert "assignment_examples.age" in variable_names
        assert "assignment_examples.height" in variable_names
        assert "assignment_examples.extras" in variable_names

        # Instance variables
        assert "UnpackingInClass.__init__.x" in variable_names
        assert "UnpackingInClass.__init__.y" in variable_names

    def test_iterator_variables(self, python_symbol_extractor):
        """Test extraction of iterator variables in for loops."""
        source = """
def loop_examples():
    # Simple for loop
    for item in items:
        print(item)

    # Multiple iterator variables
    for key, value in dictionary.items():
        process(key, value)

    # Nested loops
    for i in range(10):
        for j in range(5):
            result = i * j

    # Unpacking in loop
    for (x, y), z in complex_data:
        coordinate = (x, y, z)

async def async_loop_examples():
    # Async for loop
    async for data in async_generator():
        processed = await process(data)

    # Async unpacking
    async for name, value in async_pairs():
        await store(name, value)
"""
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        variable_names = [s.name for s in symbols if s.kind == "variable"]

        # Simple for loop
        assert "loop_examples.item" in variable_names

        # Multiple iterator variables
        assert "loop_examples.key" in variable_names
        assert "loop_examples.value" in variable_names

        # Nested loops
        assert "loop_examples.i" in variable_names
        assert "loop_examples.j" in variable_names

        # Unpacking in loop
        assert "loop_examples.x" in variable_names
        assert "loop_examples.y" in variable_names
        assert "loop_examples.z" in variable_names

        # Async loops
        assert "async_loop_examples.data" in variable_names
        assert "async_loop_examples.name" in variable_names
        assert "async_loop_examples.value" in variable_names

    def test_exception_variable_binding(self, python_symbol_extractor):
        """Test extraction of exception variables in except clauses."""
        source = """
def error_handling():
    try:
        risky_operation()
    except ValueError as ve:
        handle_value_error(ve)
    except (TypeError, AttributeError) as ta:
        handle_type_attr_error(ta)
    except Exception as e:
        log_error(e)

    # Nested try-except
    try:
        outer_operation()
        try:
            inner_operation()
        except RuntimeError as re:
            handle_runtime_error(re)
    except IOError as io:
        handle_io_error(io)
"""
        symbols = python_symbol_extractor.extract_from_source(
            source, "test.py", "test-repo"
        )

        variable_names = [s.name for s in symbols if s.kind == "variable"]

        # Exception variables
        assert "error_handling.ve" in variable_names
        assert "error_handling.ta" in variable_names
        assert "error_handling.e" in variable_names
        assert "error_handling.re" in variable_names
        assert "error_handling.io" in variable_names
