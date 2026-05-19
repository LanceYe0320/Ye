import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/network/api_client.dart';
import '../../core/network/server_config.dart';
import '../../core/storage/local_db.dart';

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  Map<String, dynamic> _settings = {};
  bool _loading = true;
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
      _settings = {'model': 'glm-4-plus', 'temperature': 0.7};
    }
    setState(() => _loading = false);
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
                _SectionHeader('LLM Configuration'),
                ListTile(
                  title: const Text('Model'),
                  subtitle: Text(_settings['model'] as String? ?? 'glm-4-plus'),
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
              ],
            ),
    );
  }

  void _showModelPicker() {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: ['glm-4-plus', 'glm-4-flash', 'glm-4-long', 'glm-4']
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
