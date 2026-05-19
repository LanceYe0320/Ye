import 'package:flutter/material.dart';
import '../../features/chat/chat_controller.dart';

class ToolCallWidget extends StatelessWidget {
  final ToolCallInfo toolCall;
  final bool isExpanded;

  const ToolCallWidget({super.key, required this.toolCall, this.isExpanded = false});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 6),
      decoration: BoxDecoration(
        color: const Color(0xFF11111B),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF313244)),
      ),
      child: _ToolCallExpansionTile(toolCall: toolCall),
    );
  }
}

class _ToolCallExpansionTile extends StatefulWidget {
  final ToolCallInfo toolCall;
  const _ToolCallExpansionTile({required this.toolCall});

  @override
  State<_ToolCallExpansionTile> createState() => _ToolCallExpansionTileState();
}

class _ToolCallExpansionTileState extends State<_ToolCallExpansionTile> {
  bool _expanded = false;

  IconData _toolIcon(String name) {
    if (name.contains('file') || name.contains('read') || name.contains('write')) {
      return Icons.description_outlined;
    }
    if (name.contains('command') || name.contains('run') || name.contains('terminal')) {
      return Icons.terminal;
    }
    if (name.contains('search') || name.contains('grep') || name.contains('find')) {
      return Icons.search;
    }
    return Icons.build_outlined;
  }

  String _formatArguments(dynamic args) {
    if (args == null) return '';
    if (args is String) return args;
    if (args is Map) {
      return args.entries.map((e) => '${e.key}: ${e.value}').join('\n');
    }
    return args.toString();
  }

  @override
  Widget build(BuildContext context) {
    final tc = widget.toolCall;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InkWell(
          onTap: () => setState(() => _expanded = !_expanded),
          borderRadius: BorderRadius.circular(8),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
            child: Row(
              children: [
                Icon(_toolIcon(tc.name), size: 14, color: const Color(0xFFF9E2AF)),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    tc.name,
                    style: const TextStyle(
                      color: Color(0xFF89B4FA),
                      fontSize: 12,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
                Icon(
                  _expanded ? Icons.expand_less : Icons.expand_more,
                  size: 16,
                  color: const Color(0xFF6C7086),
                ),
              ],
            ),
          ),
        ),
        if (_expanded) ...[
          const Divider(height: 1, color: Color(0xFF313244)),
          Padding(
            padding: const EdgeInsets.all(10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Arguments',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                    color: Color(0xFF6C7086),
                  ),
                ),
                const SizedBox(height: 4),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: const Color(0xFF1E1E2E),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    _formatArguments(tc.arguments),
                    style: const TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 11,
                      color: Color(0xFFCDD6F4),
                      height: 1.4,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }
}
