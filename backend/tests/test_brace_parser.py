"""Tests for the pure-Python multi-language brace parser (tree-sitter stand-in)."""
from __future__ import annotations

import pytest

from app.indexer.code_parser import index_file
from app.indexer._brace_parser import chunk_brace_language, supports_language


def _names(chunks):
    return {c.name for c in chunks if c.name}


class TestSupportsLanguage:
    def test_brace_languages_supported(self):
        assert supports_language("javascript")
        assert supports_language("typescript")
        assert supports_language("go")
        assert supports_language("rust")
        assert supports_language("java")
        assert supports_language("c")
        assert supports_language("cpp")

    def test_non_brace_not_supported(self):
        assert not supports_language("python")
        assert not supports_language("markdown")


class TestJavaScript:
    def test_named_function(self):
        code = "function foo(a, b) {\n  return a + b;\n}\n"
        chunks = chunk_brace_language("test.js", code, "javascript")
        assert "foo" in _names(chunks)
        foo = next(c for c in chunks if c.name == "foo")
        assert foo.chunk_type == "function"

    def test_arrow_function(self):
        code = "const bar = (x) => {\n  return x * 2;\n};\n"
        chunks = chunk_brace_language("test.js", code, "javascript")
        assert "bar" in _names(chunks)

    def test_class(self):
        code = "class Animal {\n  constructor(name) {\n    this.name = name;\n  }\n}\n"
        chunks = chunk_brace_language("test.js", code, "javascript")
        assert "Animal" in _names(chunks)

    def test_braces_in_strings_ignored(self):
        # A brace inside a string must NOT corrupt block boundaries.
        code = 'function tricky() {\n  var s = "}{";\n  return s;\n}\n'
        chunks = chunk_brace_language("test.js", code, "javascript")
        assert "tricky" in _names(chunks)
        tricky = next(c for c in chunks if c.name == "tricky")
        assert tricky.end_line == 4

    def test_braces_in_comments_ignored(self):
        code = (
            "function f() {\n"
            "  // a { b } c\n"
            "  /* multi { line } comment */\n"
            "  return 1;\n"
            "}\n"
        )
        chunks = chunk_brace_language("test.js", code, "javascript")
        assert "f" in _names(chunks)


class TestTypeScript:
    def test_method_with_generics(self):
        code = (
            "class Store<T> {\n"
            "  get<U>(key: string): U {\n"
            "    return null as any;\n"
            "  }\n"
            "}\n"
        )
        chunks = chunk_brace_language("test.ts", code, "typescript")
        assert "Store" in _names(chunks)


class TestGo:
    def test_func_and_struct(self):
        code = (
            "package main\n\n"
            "type User struct {\n  Name string\n}\n\n"
            "func (u *User) Greet() string {\n  return u.Name\n}\n\n"
            "func main() {\n  fmt.Println(\"hi\")\n}\n"
        )
        chunks = chunk_brace_language("main.go", code, "go")
        names = _names(chunks)
        assert "User" in names
        assert "Greet" in names
        assert "main" in names


class TestRust:
    def test_fn_and_struct(self):
        code = (
            "pub struct Config {\n    pub name: String,\n}\n\n"
            "impl Config {\n    pub fn new() -> Self {\n        Self { name: \"x\".into() }\n    }\n}\n"
        )
        chunks = chunk_brace_language("main.rs", code, "rust")
        names = _names(chunks)
        assert "Config" in names
        assert "new" in names


class TestJava:
    def test_class_and_method(self):
        code = (
            "public class Calculator {\n"
            "  public int add(int a, int b) {\n    return a + b;\n  }\n"
            "}\n"
        )
        chunks = chunk_brace_language("Calc.java", code, "java")
        names = _names(chunks)
        assert "Calculator" in names
        assert "add" in names


class TestIntegrationViaIndexFile:
    def test_index_file_dispatches_go(self):
        code = "package p\nfunc helper() {\n  return;\n}\n"
        chunks = index_file("a.go", code)
        assert "helper" in _names(chunks)
        assert chunks[0].language == "go"
        assert chunks[0].chunk_type == "function"

    def test_python_still_uses_ast(self):
        code = "def py_fn():\n    return 1\n"
        chunks = index_file("a.py", code)
        assert "py_fn" in _names(chunks)
        assert chunks[0].chunk_type == "function"

    def test_fallback_for_unknown(self):
        chunks = index_file("a.css", ".a { color: red; }\n.b {\n color: blue;\n}\n")
        # css falls back to line windows
        assert all(c.chunk_type == "block" for c in chunks)
