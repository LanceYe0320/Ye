import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/network/api_client.dart';
import '../../core/storage/project_state.dart';

class SearchScreen extends ConsumerStatefulWidget {
  const SearchScreen({super.key});

  @override
  ConsumerState<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends ConsumerState<SearchScreen> {
  final _controller = TextEditingController();
  List<Map<String, dynamic>> _results = [];
  bool _loading = false;
  bool _hasSearched = false;
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _search() async {
    final query = _controller.text.trim();
    if (query.isEmpty) return;

    final projectId = ref.read(currentProjectIdProvider);
    if (projectId == null) {
      setState(() => _error = 'No project selected');
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
      _hasSearched = true;
    });

    try {
      final api = ref.read(apiClientProvider);
      final raw = await api.searchCode(projectId, query);
      _results = raw.cast<Map<String, dynamic>>();
    } catch (e) {
      _error = e.toString();
    }
    if (mounted) setState(() => _loading = false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Code Search')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
            child: TextField(
              controller: _controller,
              decoration: InputDecoration(
                hintText: 'Search code...',
                prefixIcon: const Icon(Icons.search, color: Color(0xFF6C7086)),
                suffixIcon: _controller.text.isNotEmpty
                    ? IconButton(
                        icon: const Icon(Icons.clear, size: 18),
                        onPressed: () {
                          _controller.clear();
                          setState(() {
                            _results = [];
                            _hasSearched = false;
                          });
                        },
                      )
                    : null,
              ),
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _search(),
            ),
          ),
          if (_error != null)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(8),
              margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: const Color(0xFFF38BA8).withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(_error!, style: const TextStyle(color: Color(0xFFF38BA8), fontSize: 12)),
            ),
          Expanded(
            child: _loading
                ? const Center(child: CircularProgressIndicator())
                : !_hasSearched
                    ? const Center(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.search, size: 48, color: Color(0xFF6C7086)),
                            SizedBox(height: 12),
                            Text('Search your codebase', style: TextStyle(color: Color(0xFF6C7086))),
                            SizedBox(height: 4),
                            Text('Semantic search powered by embeddings', style: TextStyle(color: Color(0xFF6C7086), fontSize: 12)),
                          ],
                        ),
                      )
                    : _results.isEmpty
                        ? const Center(
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(Icons.search_off, size: 48, color: Color(0xFF6C7086)),
                                SizedBox(height: 12),
                                Text('No results found', style: TextStyle(color: Color(0xFF6C7086))),
                              ],
                            ),
                          )
                        : ListView.builder(
                            padding: const EdgeInsets.all(12),
                            itemCount: _results.length,
                            itemBuilder: (_, i) {
                              final r = _results[i];
                              final content = r['content'] as String? ?? '';
                              final meta = r['metadata'] as Map<String, dynamic>? ?? {};
                              final filePath = meta['file_path'] as String? ?? meta['path'] as String? ?? 'Unknown';
                              final distance = r['distance'] as double?;
                              final relevance = distance != null ? ((1 - distance) * 100).clamp(0, 100).toStringAsFixed(0) : null;
                              return Container(
                                margin: const EdgeInsets.only(bottom: 8),
                                decoration: BoxDecoration(
                                  color: const Color(0xFF181825),
                                  borderRadius: BorderRadius.circular(10),
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Padding(
                                      padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
                                      child: Row(
                                        children: [
                                          const Icon(Icons.code, size: 14, color: Color(0xFF89B4FA)),
                                          const SizedBox(width: 6),
                                          Expanded(
                                            child: Text(
                                              filePath,
                                              style: const TextStyle(
                                                fontSize: 12,
                                                fontWeight: FontWeight.w600,
                                                color: Color(0xFF89B4FA),
                                              ),
                                              maxLines: 1,
                                              overflow: TextOverflow.ellipsis,
                                            ),
                                          ),
                                          if (relevance != null)
                                            Container(
                                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                              decoration: BoxDecoration(
                                                color: const Color(0xFFA6E3A1).withOpacity(0.15),
                                                borderRadius: BorderRadius.circular(4),
                                              ),
                                              child: Text(
                                                '$relevance%',
                                                style: const TextStyle(fontSize: 10, color: Color(0xFFA6E3A1)),
                                              ),
                                            ),
                                        ],
                                      ),
                                    ),
                                    Container(
                                      width: double.infinity,
                                      padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
                                      child: Container(
                                        padding: const EdgeInsets.all(8),
                                        decoration: BoxDecoration(
                                          color: const Color(0xFF11111B),
                                          borderRadius: BorderRadius.circular(6),
                                        ),
                                        child: Text(
                                          content.length > 300 ? '${content.substring(0, 300)}...' : content,
                                          style: const TextStyle(
                                            fontFamily: 'monospace',
                                            fontSize: 11,
                                            height: 1.4,
                                            color: Color(0xFFCDD6F4),
                                          ),
                                          maxLines: 8,
                                          overflow: TextOverflow.ellipsis,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              );
                            },
                          ),
          ),
        ],
      ),
    );
  }
}
