import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/network/api_client.dart';
import '../../core/crdt/sync_manager.dart';
import '../../core/storage/project_state.dart';

class FileBrowserScreen extends ConsumerStatefulWidget {
  const FileBrowserScreen({super.key});

  @override
  ConsumerState<FileBrowserScreen> createState() => _FileBrowserScreenState();
}

class _FileBrowserScreenState extends ConsumerState<FileBrowserScreen> {
  List<Map<String, dynamic>> _files = [];
  bool _loading = false;
  String? _fileContent;
  String? _originalContent;
  String? _filePath;
  int? _projectId;
  String _currentPath = '';
  bool _isEditing = false;
  final _editController = TextEditingController();
  StreamSubscription? _syncSubscription;

  String _syncDocId() => 'file:$_projectId:$_filePath';

  @override
  void initState() {
    super.initState();
    _loadProjects();
  }

  @override
  void dispose() {
    _syncSubscription?.cancel();
    _disconnectSync();
    _editController.dispose();
    super.dispose();
  }

  void _connectSync() {
    if (_filePath == null || _projectId == null) return;
    final sync = ref.read(syncManagerProvider);
    sync.connect(_syncDocId());
    _syncSubscription?.cancel();
    _syncSubscription = sync.onStateChange.listen((event) {
      if (event['type'] == 'update') {
        final state = event['state'] as Map<String, dynamic>?;
        if (state != null && state.containsKey('content')) {
          final remoteContent = state['content'] as String?;
          if (remoteContent != null && remoteContent != _fileContent && !_isEditing) {
            setState(() {
              _fileContent = remoteContent;
              _originalContent = remoteContent;
            });
          }
        }
      }
    });
  }

  void _disconnectSync() {
    if (_filePath != null) {
      ref.read(syncManagerProvider).disconnect(_syncDocId());
    }
    _syncSubscription?.cancel();
    _syncSubscription = null;
  }

  Future<void> _loadProjects() async {
    setState(() => _loading = true);
    try {
      final storedId = ref.read(currentProjectIdProvider);
      if (storedId != null) {
        _projectId = storedId;
        await _loadFiles('');
      } else {
        final api = ref.read(apiClientProvider);
        final projects = await api.getProjects();
        if (projects.isNotEmpty) {
          _projectId = projects.first['id'] as int;
          await ref.read(currentProjectIdProvider.notifier).setProject(_projectId);
          await _loadFiles('');
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e')));
      }
    }
    setState(() => _loading = false);
  }

  Future<void> _loadFiles(String path) async {
    if (_projectId == null) return;
    setState(() => _loading = true);
    try {
      final api = ref.read(apiClientProvider);
      _files = (await api.listFiles(_projectId!, path: path))
          .map((e) => e as Map<String, dynamic>)
          .toList();
      _fileContent = null;
      _originalContent = null;
      _filePath = null;
      _isEditing = false;
      _currentPath = path;
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e')));
      }
    }
    setState(() => _loading = false);
  }

  Future<void> _openFile(String filePath) async {
    if (_projectId == null) return;
    setState(() => _loading = true);
    try {
      final api = ref.read(apiClientProvider);
      final data = await api.readFile(_projectId!, filePath);
      _fileContent = data['content'] as String? ?? '';
      _originalContent = _fileContent;
      _filePath = filePath;
      _isEditing = false;
      _editController.text = _fileContent ?? '';
      _connectSync();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e')));
      }
    }
    setState(() => _loading = false);
  }

  Future<void> _saveFile() async {
    if (_projectId == null || _filePath == null) return;
    setState(() => _loading = true);
    try {
      final api = ref.read(apiClientProvider);
      await api.writeFile(_projectId!, _filePath!, _editController.text);
      _fileContent = _editController.text;
      _originalContent = _fileContent;
      _isEditing = false;

      ref.read(syncManagerProvider).sendUpdate(_syncDocId(), {
        'content': _fileContent,
        'updated_at': DateTime.now().toIso8601String(),
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Saved'), backgroundColor: Color(0xFFA6E3A1)),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Save failed: $e')));
      }
    }
    setState(() => _loading = false);
  }

  void _toggleEdit() {
    if (_isEditing) {
      _saveFile();
    } else {
      setState(() {
        _isEditing = true;
        _editController.text = _fileContent ?? '';
      });
    }
  }

  bool get _hasChanges => _editController.text != (_originalContent ?? '');

  void _goBack() {
    if (_isEditing) {
      setState(() => _isEditing = false);
      return;
    }
    _disconnectSync();
    if (_filePath != null) {
      _loadFiles(_currentPath);
    } else if (_currentPath.isNotEmpty) {
      final parent = _currentPath.contains('/')
          ? _currentPath.substring(0, _currentPath.lastIndexOf('/'))
          : '';
      _loadFiles(parent);
    }
  }

  @override
  Widget build(BuildContext context) {
    final fileName = _filePath?.split('/').last ?? 'Files';
    return Scaffold(
      appBar: AppBar(
        title: Text(fileName),
        leading: (_filePath != null || _currentPath.isNotEmpty)
            ? IconButton(icon: const Icon(Icons.arrow_back), onPressed: _goBack)
            : null,
        actions: _filePath != null
            ? [
                IconButton(
                  icon: Icon(_isEditing ? Icons.save : Icons.edit),
                  onPressed: _toggleEdit,
                ),
                if (_isEditing && _hasChanges)
                  TextButton(
                    onPressed: () {
                      setState(() {
                        _isEditing = false;
                        _editController.text = _originalContent ?? '';
                      });
                    },
                    child: const Text('Cancel', style: TextStyle(fontSize: 13)),
                  ),
              ]
            : null,
      ),
      floatingActionButton: _filePath == null && _projectId != null
          ? FloatingActionButton(
              onPressed: _showCreateDialog,
              child: const Icon(Icons.add),
            )
          : null,
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _fileContent != null
              ? _isEditing ? _buildEditor() : _buildFileView()
              : _buildFileList(),
    );
  }

  Widget _buildFileList() {
    if (_files.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.folder_open, size: 48, color: Color(0xFF6C7086)),
            SizedBox(height: 12),
            Text('No project connected', style: TextStyle(color: Color(0xFF6C7086))),
            SizedBox(height: 4),
            Text('Open a project on desktop first', style: TextStyle(color: Color(0xFF6C7086), fontSize: 12)),
          ],
        ),
      );
    }
    return ListView.builder(
      itemCount: _files.length,
      itemBuilder: (_, i) {
        final entry = _files[i];
        final isDir = entry['is_dir'] as bool? ?? false;
        final name = entry['name'] as String? ?? '';
        return ListTile(
          leading: Icon(
            isDir ? Icons.folder : _getFileIcon(name),
            color: isDir ? const Color(0xFFF9E2AF) : const Color(0xFF89B4FA),
          ),
          title: Text(name, style: const TextStyle(fontSize: 14)),
          subtitle: Text(
            entry['path'] as String? ?? '',
            style: const TextStyle(fontSize: 11, color: Color(0xFF6C7086)),
          ),
          trailing: isDir ? const Icon(Icons.chevron_right) : null,
          onTap: () {
            final path = entry['path'] as String? ?? '';
            if (isDir) {
              _loadFiles(path);
            } else {
              _openFile(path);
            }
          },
          onLongPress: () => _showFileOptions(name, entry['path'] as String? ?? '', isDir),
        );
      },
    );
  }

  Widget _buildFileView() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(12),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: const Color(0xFF181825),
          borderRadius: BorderRadius.circular(12),
        ),
        child: SelectableText(
          _fileContent ?? '',
          style: const TextStyle(fontFamily: 'monospace', fontSize: 13, height: 1.5),
        ),
      ),
    );
  }

  Widget _buildEditor() {
    return Padding(
      padding: const EdgeInsets.all(8),
      child: TextField(
        controller: _editController,
        maxLines: null,
        expands: true,
        textAlignVertical: TextAlignVertical.top,
        style: const TextStyle(fontFamily: 'monospace', fontSize: 13, height: 1.5),
        decoration: InputDecoration(
          filled: true,
          fillColor: const Color(0xFF181825),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: const BorderSide(color: Color(0xFF313244)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(8),
            borderSide: const BorderSide(color: Color(0xFF89B4FA)),
          ),
          contentPadding: const EdgeInsets.all(12),
        ),
      ),
    );
  }

  IconData _getFileIcon(String name) {
    final ext = name.split('.').last.toLowerCase();
    switch (ext) {
      case 'dart': case 'js': case 'ts': case 'py': case 'java':
        return Icons.code;
      case 'json': case 'yaml': case 'yml': case 'toml':
        return Icons.settings;
      case 'md': case 'txt':
        return Icons.description;
      default:
        return Icons.insert_drive_file;
    }
  }

  void _showFileOptions(String name, String path, bool isDir) {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.all(12),
              child: Text(name, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 14)),
            ),
            const Divider(height: 1),
            if (!isDir) ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('Edit'),
              onTap: () { Navigator.pop(context); _openFile(path); },
            ),
            ListTile(
              leading: const Icon(Icons.delete_outline, color: Color(0xFFF38BA8)),
              title: const Text('Delete', style: TextStyle(color: Color(0xFFF38BA8))),
              onTap: () {
                Navigator.pop(context);
                _confirmDelete(name, path);
              },
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmDelete(String name, String path) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete'),
        content: Text('Delete "$name"? This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(backgroundColor: const Color(0xFFF38BA8)),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed == true && _projectId != null) {
      try {
        final api = ref.read(apiClientProvider);
        await api.deleteFile(_projectId!, path);
        await _loadFiles(_currentPath);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Deleted'), duration: Duration(seconds: 1)),
          );
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Delete failed: $e')));
        }
      }
    }
  }

  void _showCreateDialog() {
    final nameController = TextEditingController();
    bool isFolder = false;
    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          title: const Text('Create New'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameController,
                autofocus: true,
                decoration: InputDecoration(
                  labelText: 'Name',
                  hintText: isFolder ? 'folder_name' : 'file_name.ext',
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  const Text('Type: '),
                  ChoiceChip(
                    label: const Text('File'),
                    selected: !isFolder,
                    onSelected: (_) => setDialogState(() => isFolder = false),
                  ),
                  const SizedBox(width: 8),
                  ChoiceChip(
                    label: const Text('Folder'),
                    selected: isFolder,
                    onSelected: (_) => setDialogState(() => isFolder = true),
                  ),
                ],
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
            TextButton(
              onPressed: () async {
                final name = nameController.text.trim();
                if (name.isEmpty) return;
                Navigator.pop(ctx);
                await _createEntry(name, isFolder);
              },
              child: const Text('Create'),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _createEntry(String name, bool isFolder) async {
    if (_projectId == null) return;
    if (name.contains('/') || name.contains('\\') || name.contains('..')) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Invalid name: cannot contain / \\ or ..')),
        );
      }
      return;
    }
    try {
      final api = ref.read(apiClientProvider);
      await api.createEntry(_projectId!, name, path: _currentPath, isDir: isFolder);
      await _loadFiles(_currentPath);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${isFolder ? "Folder" : "File"} created'), duration: const Duration(seconds: 1)),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Create failed: $e')));
      }
    }
  }
}
