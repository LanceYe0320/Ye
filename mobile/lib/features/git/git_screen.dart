import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/network/api_client.dart';
import '../../core/storage/project_state.dart';

class GitScreen extends ConsumerStatefulWidget {
  const GitScreen({super.key});

  @override
  ConsumerState<GitScreen> createState() => _GitScreenState();
}

class _GitScreenState extends ConsumerState<GitScreen> {
  int? _projectId;
  Map<String, dynamic>? _status;
  List<dynamic> _log = [];
  String? _diff;
  List<dynamic> _branches = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _initGit();
  }

  Future<void> _initGit() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final storedId = ref.read(currentProjectIdProvider);
      if (storedId != null) {
        _projectId = storedId;
        await _loadAll();
      } else {
        final api = ref.read(apiClientProvider);
        final projects = await api.getProjects();
        if (projects.isNotEmpty) {
          _projectId = projects.first['id'] as int;
          await ref.read(currentProjectIdProvider.notifier).setProject(_projectId);
          await _loadAll();
        } else {
          _error = 'No project connected';
        }
      }
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _loadAll() async {
    if (_projectId == null) return;
    final api = ref.read(apiClientProvider);
    final results = await Future.wait([
      api.gitStatus(_projectId!),
      api.gitLog(_projectId!),
      api.gitDiff(_projectId!),
      api.gitBranches(_projectId!),
    ]);
    _status = results[0] as Map<String, dynamic>;
    _log = results[1] as List;
    _diff = (results[2] as Map<String, dynamic>)['diff'] as String? ?? '';
    _branches = results[3] as List;
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    try {
      await _loadAll();
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _commit() async {
    final msgController = TextEditingController();
    final result = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Commit'),
        content: TextField(
          controller: msgController,
          decoration: const InputDecoration(labelText: 'Commit message'),
          autofocus: true,
          maxLines: 3,
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Commit')),
        ],
      ),
    );

    if (result == true && _projectId != null) {
      final msg = msgController.text.trim();
      if (msg.isEmpty) return;
      try {
        final api = ref.read(apiClientProvider);
        await api.gitCommit(_projectId!, msg);
        _refresh();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Committed'), backgroundColor: Color(0xFFA6E3A1)),
          );
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Commit failed: $e')));
        }
      }
    }
  }

  Future<void> _aiCommit() async {
    if (_projectId == null) return;
    setState(() => _loading = true);
    try {
      final api = ref.read(apiClientProvider);
      final data = await api.gitCommitAi(_projectId!);
      _refresh();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('AI commit: ${data['message'] ?? 'done'}')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('AI commit failed: $e')));
      }
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _showBranchPicker() async {
    if (_projectId == null) return;
    final api = ref.read(apiClientProvider);
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(12),
              child: Text('Branches', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
            ),
            const Divider(height: 1),
            ..._branches.map((b) {
              final name = b['name'] as String? ?? '';
              final isActive = b['active'] as bool? ?? false;
              return ListTile(
                leading: Icon(
                  isActive ? Icons.circle : Icons.circle_outlined,
                  color: isActive ? const Color(0xFFA6E3A1) : const Color(0xFF6C7086),
                  size: 14,
                ),
                title: Text(name, style: TextStyle(
                  fontWeight: isActive ? FontWeight.bold : FontWeight.normal,
                )),
                trailing: isActive ? const Text('current', style: TextStyle(fontSize: 11, color: Color(0xFF6C7086))) : null,
                onTap: isActive ? null : () async {
                  Navigator.pop(context);
                  try {
                    await api.gitCheckout(_projectId!, name);
                    _refresh();
                  } catch (e) {
                    if (mounted) {
                      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Checkout failed: $e')));
                    }
                  }
                },
              );
            }),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Git'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _refresh, tooltip: 'Refresh'),
        ],
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
                      FilledButton(onPressed: _refresh, child: const Text('Retry')),
                    ],
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _refresh,
                  child: ListView(
                    padding: const EdgeInsets.all(12),
                    children: [
                      // Branch info
                      _buildCard(
                        title: 'Branch',
                        icon: Icons.call_split,
                        children: [
                          ListTile(
                            title: Text(
                              _status?['branch'] as String? ?? 'N/A',
                              style: const TextStyle(fontWeight: FontWeight.w600, color: Color(0xFF89B4FA)),
                            ),
                            trailing: const Icon(Icons.swap_horiz, size: 20),
                            onTap: _showBranchPicker,
                            contentPadding: EdgeInsets.zero,
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),

                      // Status
                      _buildCard(
                        title: 'Status',
                        icon: Icons.info_outline,
                        children: [
                          _buildStatusRow('Staged', (_status?['staged'] as List?)?.length ?? 0, const Color(0xFFA6E3A1)),
                          _buildStatusRow('Unstaged', (_status?['unstaged'] as List?)?.length ?? 0, const Color(0xFFF9E2AF)),
                          _buildStatusRow('Untracked', (_status?['untracked'] as List?)?.length ?? 0, const Color(0xFF6C7086)),
                        ],
                      ),
                      const SizedBox(height: 12),

                      // Actions
                      Row(
                        children: [
                          Expanded(
                            child: FilledButton.icon(
                              onPressed: _commit,
                              icon: const Icon(Icons.commit, size: 18),
                              label: const Text('Commit'),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: OutlinedButton.icon(
                              onPressed: _aiCommit,
                              icon: const Icon(Icons.auto_fix_high, size: 18),
                              label: const Text('AI Commit'),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 16),

                      // Recent commits
                      _buildCard(
                        title: 'Recent Commits',
                        icon: Icons.history,
                        children: _log.isEmpty
                            ? [const Text('No commits yet', style: TextStyle(color: Color(0xFF6C7086)))]
                            : _log.take(10).map((c) {
                                final rawHash = c['hash'] as String? ?? '';
                                final hash = rawHash.length > 7 ? rawHash.substring(0, 7) : rawHash;
                                final msg = c['message'] as String? ?? '';
                                final author = c['author'] as String? ?? '';
                                final date = c['date'] as String? ?? '';
                                return ListTile(
                                  contentPadding: EdgeInsets.zero,
                                  dense: true,
                                  leading: Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: const Color(0xFF89B4FA).withOpacity(0.15),
                                      borderRadius: BorderRadius.circular(4),
                                    ),
                                    child: Text(hash, style: const TextStyle(fontFamily: 'monospace', fontSize: 11, color: Color(0xFF89B4FA))),
                                  ),
                                  title: Text(msg, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13)),
                                  subtitle: Text('$author · $date', style: const TextStyle(fontSize: 10, color: Color(0xFF6C7086))),
                                );
                              }).toList(),
                      ),
                      const SizedBox(height: 12),

                      // Diff
                      if (_diff != null && _diff!.isNotEmpty) ...[
                        _buildCard(
                          title: 'Diff',
                          icon: Icons.difference,
                          children: [
                            Container(
                              width: double.infinity,
                              constraints: const BoxConstraints(maxHeight: 300),
                              padding: const EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: const Color(0xFF11111B),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: SingleChildScrollView(
                                child: Text(
                                  _diff!,
                                  style: const TextStyle(
                                    fontFamily: 'monospace',
                                    fontSize: 11,
                                    height: 1.4,
                                    color: Color(0xFFCDD6F4),
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ],
                  ),
                ),
    );
  }

  Widget _buildCard({required String title, required IconData icon, required List<Widget> children}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF181825),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 16, color: const Color(0xFF6C7086)),
              const SizedBox(width: 8),
              Text(title, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: 1, color: Color(0xFF6C7086))),
            ],
          ),
          const SizedBox(height: 8),
          ...children,
        ],
      ),
    );
  }

  Widget _buildStatusRow(String label, int count, Color color) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Container(width: 8, height: 8, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
          const SizedBox(width: 8),
          Text(label, style: const TextStyle(fontSize: 13)),
          const Spacer(),
          Text('$count', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: color)),
        ],
      ),
    );
  }
}
