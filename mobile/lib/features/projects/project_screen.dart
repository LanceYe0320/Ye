import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/network/api_client.dart';
import '../../core/storage/project_state.dart';

class ProjectScreen extends ConsumerStatefulWidget {
  const ProjectScreen({super.key});

  @override
  ConsumerState<ProjectScreen> createState() => _ProjectScreenState();
}

class _ProjectScreenState extends ConsumerState<ProjectScreen> {
  List<Map<String, dynamic>> _projects = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadProjects();
  }

  Future<void> _loadProjects() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = ref.read(apiClientProvider);
      _projects = (await api.getProjects()).cast<Map<String, dynamic>>();
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _createProject() async {
    final nameController = TextEditingController();
    final pathController = TextEditingController();
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('New Project'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameController,
              decoration: const InputDecoration(labelText: 'Project Name', hintText: 'my-project'),
              autofocus: true,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: pathController,
              decoration: const InputDecoration(
                labelText: 'Path',
                hintText: '/home/user/my-project',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Create'),
          ),
        ],
      ),
    );

    if (result == true) {
      final name = nameController.text.trim();
      final path = pathController.text.trim();
      if (name.isEmpty || path.isEmpty) return;
      try {
        final api = ref.read(apiClientProvider);
        await api.createProject(name, path);
        _loadProjects();
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Create failed: $e')));
        }
      }
    }
  }

  Future<void> _deleteProject(int id, String name) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete Project'),
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

    if (confirmed == true) {
      try {
        final api = ref.read(apiClientProvider);
        await api.deleteProject(id);
        _loadProjects();
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Delete failed: $e')));
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final currentProjectId = ref.watch(currentProjectIdProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Projects')),
      floatingActionButton: FloatingActionButton(
        onPressed: _createProject,
        child: const Icon(Icons.add),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.error_outline, size: 48, color: Color(0xFFF38BA8)),
                      const SizedBox(height: 12),
                      Text(_error!, style: const TextStyle(color: Color(0xFFF38BA8))),
                      const SizedBox(height: 12),
                      FilledButton(onPressed: _loadProjects, child: const Text('Retry')),
                    ],
                  ),
                )
              : _projects.isEmpty
                  ? const Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.folder_outlined, size: 48, color: Color(0xFF6C7086)),
                          SizedBox(height: 12),
                          Text('No projects yet', style: TextStyle(color: Color(0xFF6C7086))),
                          SizedBox(height: 4),
                          Text('Create one or open a project on desktop', style: TextStyle(color: Color(0xFF6C7086), fontSize: 12)),
                        ],
                      ),
                    )
                  : RefreshIndicator(
                      onRefresh: _loadProjects,
                      child: ListView.builder(
                        itemCount: _projects.length,
                        itemBuilder: (_, i) {
                          final p = _projects[i];
                          final name = p['name'] as String? ?? 'Untitled';
                          final path = p['path'] as String? ?? '';
                          final id = p['id'] as int;
                          final isActive = id == currentProjectId;
                          return Card(
                            margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                            color: isActive ? const Color(0xFF89B4FA).withOpacity(0.1) : null,
                            child: ListTile(
                              leading: Container(
                                width: 40,
                                height: 40,
                                decoration: BoxDecoration(
                                  color: isActive ? const Color(0xFF89B4FA).withOpacity(0.25) : const Color(0xFF89B4FA).withOpacity(0.15),
                                  borderRadius: BorderRadius.circular(10),
                                ),
                                child: Icon(
                                  isActive ? Icons.folder_special : Icons.folder,
                                  color: const Color(0xFF89B4FA),
                                  size: 20,
                                ),
                              ),
                              title: Row(
                                children: [
                                  Text(name, style: const TextStyle(fontWeight: FontWeight.w600)),
                                  if (isActive) ...[
                                    const SizedBox(width: 6),
                                    Container(
                                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                                      decoration: BoxDecoration(
                                        color: const Color(0xFFA6E3A1).withOpacity(0.15),
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: const Text('active', style: TextStyle(fontSize: 9, color: Color(0xFFA6E3A1))),
                                    ),
                                  ],
                                ],
                              ),
                              subtitle: Text(path, style: const TextStyle(fontSize: 11, color: Color(0xFF6C7086))),
                              trailing: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  if (!isActive)
                                    IconButton(
                                      icon: const Icon(Icons.check_circle_outline, size: 20, color: Color(0xFFA6E3A1)),
                                      onPressed: () {
                                        ref.read(currentProjectIdProvider.notifier).setProject(id);
                                        ScaffoldMessenger.of(context).showSnackBar(
                                          SnackBar(content: Text('Switched to $name'), duration: const Duration(seconds: 1)),
                                        );
                                      },
                                      tooltip: 'Set active',
                                    ),
                                  IconButton(
                                    icon: const Icon(Icons.delete_outline, color: Color(0xFFF38BA8), size: 20),
                                    onPressed: () => _deleteProject(id, name),
                                  ),
                                ],
                              ),
                            ),
                          );
                        },
                      ),
                    ),
    );
  }
}
