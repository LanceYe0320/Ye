import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../core/network/api_client.dart';
import '../../core/network/server_config.dart';
import '../../core/storage/local_db.dart';
import '../../core/storage/project_state.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  Map<String, dynamic> _settings = {};
  bool _loading = true;
  bool _testingConnection = false;
  bool? _connectionStatus;
  final _serverUrlController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _loadSettings();
    _loadServerUrl();
  }

  @override
  void dispose() {
    _serverUrlController.dispose();
    super.dispose();
  }

  Future<void> _loadSettings() async {
    try {
      final api = ref.read(apiClientProvider);
      _settings = await api.getSettings();
    } catch (e) {
      _settings = {'model': 'glm-5.1', 'temperature': 0.7};
    }
    setState(() => _loading = false);
  }

  Future<void> _testConnection() async {
    setState(() => _testingConnection = true);
    try {
      final api = ref.read(apiClientProvider);
      await api.healthCheck();
      _connectionStatus = true;
    } catch (_) {
      _connectionStatus = false;
    }
    setState(() => _testingConnection = false);
  }

  Future<void> _loadServerUrl() async {
    final stored = await LocalStorage.getServerUrl();
    if (stored != null) {
      _serverUrlController.text = stored;
    }
  }

  Future<void> _saveServerUrl() async {
    final url = _serverUrlController.text.trim();
    if (url.isEmpty) return;
    final uri = Uri.tryParse(url);
    if (uri == null || (!uri.scheme.startsWith('http'))) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Invalid URL — must be http:// or https://'), backgroundColor: Color(0xFFF38BA8)),
        );
      }
      return;
    }
    await LocalStorage.setServerUrl(url);
    ref.invalidate(serverUrlProvider);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Server URL saved'), duration: Duration(seconds: 1)),
      );
    }
  }

  Future<void> _updateSetting(String key, dynamic value) async {
    try {
      final api = ref.read(apiClientProvider);
      final updated = await api.updateSettings({key: value});
      setState(() => _settings = updated);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Setting saved'), duration: Duration(seconds: 1)),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Error: $e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              children: [
                _SectionHeader('Active Project'),
                Consumer(builder: (context, ref, _) {
                  final projectsAsync = ref.watch(projectsListProvider);
                  final currentId = ref.watch(currentProjectIdProvider);
                  return projectsAsync.when(
                    data: (projects) {
                      if (projects.isEmpty) {
                        return const ListTile(
                          title: Text('No projects'),
                          subtitle: Text('Create a project first'),
                        );
                      }
                      return ListTile(
                        title: const Text('Project'),
                        subtitle: Text(
                          projects.isNotEmpty
                              ? (projects.firstWhere((p) => p['id'] == currentId, orElse: () => projects.first)['name'] as String? ?? 'None')
                              : 'None',
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => _showProjectPicker(projects, currentId),
                      );
                    },
                    loading: () => const ListTile(title: Text('Loading projects...')),
                    error: (_, __) => const ListTile(title: Text('Failed to load projects')),
                  );
                }),
                _SectionHeader('LLM Configuration'),
                ListTile(
                  title: const Text('Model'),
                  subtitle: Text(_settings['model'] as String? ?? 'glm-5.1'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _showModelPicker(),
                ),
                ListTile(
                  title: const Text('Temperature'),
                  subtitle: Text('${_settings['temperature'] ?? 0.7}'),
                  trailing: SizedBox(
                    width: 150,
                    child: Slider(
                      value: (_settings['temperature'] as num?)?.toDouble() ?? 0.7,
                      min: 0.0,
                      max: 1.0,
                      divisions: 10,
                      onChanged: (v) => _updateSetting('temperature', v),
                    ),
                  ),
                ),
                _SectionHeader('Connection'),
                ListTile(
                  leading: Icon(
                    _connectionStatus == null ? Icons.cloud_off : (_connectionStatus! ? Icons.cloud_done : Icons.cloud_off),
                    color: _connectionStatus == null ? const Color(0xFF6C7086) : (_connectionStatus! ? const Color(0xFFA6E3A1) : const Color(0xFFF38BA8)),
                  ),
                  title: Text(
                    _connectionStatus == null ? 'Server Status' : (_connectionStatus! ? 'Connected' : 'Disconnected'),
                  ),
                  subtitle: Text(
                    _connectionStatus == null ? 'Tap to test connection' : (_connectionStatus! ? 'Server is reachable' : 'Cannot reach server'),
                    style: const TextStyle(fontSize: 12, color: Color(0xFF6C7086)),
                  ),
                  trailing: _testingConnection
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.refresh, size: 18),
                  onTap: _testingConnection ? null : _testConnection,
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  child: Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _serverUrlController,
                          decoration: const InputDecoration(
                            labelText: 'Server URL',
                            helperText: 'Desktop IP for Android, localhost for iOS',
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      IconButton(
                        icon: const Icon(Icons.save),
                        onPressed: _saveServerUrl,
                        tooltip: 'Save URL',
                      ),
                    ],
                  ),
                ),
                _SectionHeader('About'),
                const ListTile(
                  title: Text('AI Coding Assistant'),
                  subtitle: Text('v0.1.0 · Powered by Zhipu GLM-4'),
                ),
                const ListTile(
                  title: Text('Tech Stack'),
                  subtitle: Text('Flutter + FastAPI + SQLite'),
                ),
                _SectionHeader('Account'),
                ListTile(
                  leading: const Icon(Icons.logout, color: Color(0xFFF38BA8)),
                  title: const Text('Logout', style: TextStyle(color: Color(0xFFF38BA8))),
                  onTap: () async {
                    final confirmed = await showDialog<bool>(
                      context: context,
                      builder: (ctx) => AlertDialog(
                        title: const Text('Logout'),
                        content: const Text('Are you sure you want to logout?'),
                        actions: [
                          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
                          FilledButton(
                            onPressed: () => Navigator.pop(ctx, true),
                            style: FilledButton.styleFrom(backgroundColor: const Color(0xFFF38BA8)),
                            child: const Text('Logout'),
                          ),
                        ],
                      ),
                    );
                    if (confirmed == true) {
                      await LocalStorage.deleteToken();
                      if (context.mounted) {
                        GoRouter.of(context).go('/auth');
                      }
                    }
                  },
                ),
              ],
            ),
    );
  }

  void _showProjectPicker(List<Map<String, dynamic>> projects, int? currentId) {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(12),
              child: Text('Select Project', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            ),
            const Divider(height: 1),
            ...projects.map((p) {
              final id = p['id'] as int;
              final name = p['name'] as String? ?? '';
              final isActive = id == currentId;
              return ListTile(
                leading: Icon(
                  isActive ? Icons.radio_button_checked : Icons.radio_button_unchecked,
                  color: isActive ? const Color(0xFF89B4FA) : const Color(0xFF6C7086),
                ),
                title: Text(name, style: TextStyle(fontWeight: isActive ? FontWeight.bold : FontWeight.normal)),
                onTap: () {
                  ref.read(currentProjectIdProvider.notifier).setProject(id);
                  Navigator.pop(context);
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('Switched to $name'), duration: const Duration(seconds: 1)),
                  );
                },
              );
            }),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  void _showModelPicker() {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: ['glm-5.1', 'glm-4-flash', 'glm-4-long', 'glm-4']
              .map((model) => ListTile(
                    title: Text(model),
                    trailing: _settings['model'] == model
                        ? const Icon(Icons.check, color: Color(0xFF89B4FA))
                        : null,
                    onTap: () {
                      _updateSetting('model', model);
                      Navigator.pop(context);
                    },
                  ))
              .toList(),
        ),
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;
  const _SectionHeader(this.title);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 20, 16, 8),
      child: Text(
        title,
        style: const TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w700,
          letterSpacing: 1,
          color: Color(0xFF6C7086),
        ),
      ),
    );
  }
}
