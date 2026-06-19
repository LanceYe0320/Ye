from __future__ import annotations

import ast
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    '.py': 'python',
    '.js': 'javascript',
    '.ts': 'typescript',
    '.vue': 'vue',
    '.java': 'java',
    '.go': 'go',
    '.rs': 'rust',
    '.cpp': 'cpp',
    '.c': 'c',
    '.html': 'html',
    '.css': 'css',
    '.json': 'json',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.md': 'markdown',
    '.sql': 'sql',
    '.sh': 'shell',
}

IGNORED_DIRS = {
    'node_modules', '.git', '__pycache__', '.venv', 'venv', 'env',
    'dist', 'build', '.next', '.nuxt', 'target', 'bin', 'obj',
    '.idea', '.vscode', '.tox', '.mypy_cache', '.pytest_cache',
}


@dataclass
class CodeChunk:
    file_path: str
    language: str
    content: str
    chunk_type: str  # 'function', 'class', 'method', 'module', 'block'
    name: str = ''
    start_line: int = 0
    end_line: int = 0
    metadata: dict = field(default_factory=dict)


def get_language(file_path: str) -> str | None:
    ext = Path(file_path).suffix.lower()
    return SUPPORTED_EXTENSIONS.get(ext)


def should_index(file_path: str) -> bool:
    path = Path(file_path)
    for part in path.parts:
        if part in IGNORED_DIRS:
            return False
    if path.name.startswith('.') and path.suffix not in {'.env', '.yml', '.yaml'}:
        return False
    return get_language(file_path) is not None


def chunk_python_file(file_path: str, content: str) -> list[CodeChunk]:
    chunks = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _chunk_by_lines(file_path, content, 'python', max_lines=80)

    source_lines = content.splitlines()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = node.end_lineno or start
            chunks.append(CodeChunk(
                file_path=file_path,
                language='python',
                content='\n'.join(source_lines[start - 1:end]),
                chunk_type='function',
                name=node.name,
                start_line=start,
                end_line=end,
            ))
        elif isinstance(node, ast.ClassDef):
            start = node.lineno
            end = node.end_lineno or start
            chunks.append(CodeChunk(
                file_path=file_path,
                language='python',
                content='\n'.join(source_lines[start - 1:end]),
                chunk_type='class',
                name=node.name,
                start_line=start,
                end_line=end,
            ))

    if not chunks:
        chunks = _chunk_by_lines(file_path, content, 'python', max_lines=80)

    return chunks


def _chunk_by_lines(
    file_path: str, content: str, language: str, max_lines: int = 80
) -> list[CodeChunk]:
    lines = content.splitlines()
    chunks = []
    for i in range(0, len(lines), max_lines):
        chunk_lines = lines[i:i + max_lines]
        chunks.append(CodeChunk(
            file_path=file_path,
            language=language,
            content='\n'.join(chunk_lines),
            chunk_type='block',
            start_line=i + 1,
            end_line=min(i + max_lines, len(lines)),
        ))
    return chunks


def index_file(file_path: str, content: str | None = None) -> list[CodeChunk]:
    language = get_language(file_path)
    if not language:
        return []

    if content is None:
        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Cannot read {file_path}: {e}")
            return []

    if language == "python":
        return chunk_python_file(file_path, content)

    # Brace-delimited languages (JS/TS/Go/Rust/Java/C/C++/Vue) get structural
    # chunking via the pure-Python brace parser — named function/class blocks
    # instead of fixed-size line windows. No external deps (tree-sitter-free).
    from app.indexer._brace_parser import chunk_brace_language, supports_language
    if supports_language(language):
        return chunk_brace_language(file_path, content, language)

    # Everything else (css, json, yaml, markdown, sql, shell, html) — line windows
    return _chunk_by_lines(file_path, content, language)


def index_directory(
    directory: str,
    max_workers: int = 4,
    skip_paths: set[str] | None = None,
) -> list[CodeChunk]:
    """Index all code files under a directory.

    skip_paths: optional set of relative paths (forward-slash) to SKIP. Used by
    the incremental indexer to avoid re-parsing files whose mtime hasn't
    changed since the last index.
    """
    root = Path(directory)
    skip_paths = skip_paths or set()

    # Collect file paths first (rglob itself can't be parallelized)
    file_paths: list[tuple[Path, str]] = []
    for filepath in root.rglob('*'):
        if not filepath.is_file():
            continue
        rel_path = str(filepath.relative_to(root)).replace('\\', '/')
        if not should_index(rel_path):
            continue
        if rel_path in skip_paths:
            continue
        file_paths.append((filepath, rel_path))

    all_chunks: list[CodeChunk] = []

    def _index_one(item: tuple[Path, str]) -> list[CodeChunk]:
        filepath, rel_path = item
        try:
            chunks = index_file(str(filepath))
            for chunk in chunks:
                chunk.file_path = rel_path
            return chunks
        except Exception as e:
            logger.warning(f"Error indexing {rel_path}: {e}")
            return []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_index_one, item): item for item in file_paths}
        for future in as_completed(futures):
            all_chunks.extend(future.result())

    logger.info(f"Indexed {len(all_chunks)} chunks from {len(file_paths)} files in {directory}")
    return all_chunks
