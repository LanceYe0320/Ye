import ast
import logging
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


def chunk_js_ts_file(file_path: str, content: str, language: str) -> list[CodeChunk]:
    chunks = []
    lines = content.splitlines()
    current_chunk_start = 0
    brace_depth = 0
    in_function = False
    func_name = ''

    for i, line in enumerate(lines):
        stripped = line.strip()

        if any(kw in stripped for kw in ['function ', 'const ', 'let ', 'var ']):
            if '(' in stripped and ('{' in stripped or '=>' in stripped):
                if not in_function:
                    current_chunk_start = i
                    in_function = True
                    for part in stripped.replace('function', '').split('(')[0].split():
                        if part and part not in ('const', 'let', 'var', 'async', 'export', 'default'):
                            func_name = part.strip()
                            break

        if in_function:
            brace_depth += line.count('{') - line.count('}')
            if '=>' in stripped:
                brace_depth += 1

            if brace_depth <= 0 and i > current_chunk_start:
                chunks.append(CodeChunk(
                    file_path=file_path,
                    language=language,
                    content='\n'.join(lines[current_chunk_start:i + 1]),
                    chunk_type='function',
                    name=func_name,
                    start_line=current_chunk_start + 1,
                    end_line=i + 1,
                ))
                in_function = False
                func_name = ''

    if not chunks:
        chunks = _chunk_by_lines(file_path, content, language, max_lines=80)

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
            content = Path(file_path).read_text(encoding='utf-8')
        except Exception as e:
            logger.warning(f"Cannot read {file_path}: {e}")
            return []

    if language == 'python':
        return chunk_python_file(file_path, content)
    elif language in ('javascript', 'typescript'):
        return chunk_js_ts_file(file_path, content, language)
    else:
        return _chunk_by_lines(file_path, content, language)


def index_directory(directory: str) -> list[CodeChunk]:
    all_chunks = []
    root = Path(directory)

    for filepath in root.rglob('*'):
        if not filepath.is_file():
            continue
        rel_path = str(filepath.relative_to(root)).replace('\\', '/')
        if not should_index(rel_path):
            continue
        try:
            chunks = index_file(str(filepath))
            for chunk in chunks:
                chunk.file_path = rel_path
            all_chunks.extend(chunks)
        except Exception as e:
            logger.warning(f"Error indexing {rel_path}: {e}")

    logger.info(f"Indexed {len(all_chunks)} chunks from {directory}")
    return all_chunks
