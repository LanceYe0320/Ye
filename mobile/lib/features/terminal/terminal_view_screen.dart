import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/network/api_client.dart';
import 'terminal_controller.dart';
import 'terminal_input_widget.dart';
import 'terminal_output_widget.dart';

class TerminalViewScreen extends ConsumerStatefulWidget {
  const TerminalViewScreen({super.key});

  @override
  ConsumerState<TerminalViewScreen> createState() => _TerminalViewScreenState();
}

class _TerminalViewScreenState extends ConsumerState<TerminalViewScreen> {
  final _commandController = TextEditingController();
  final _scrollController = ScrollController();
  int? _projectId;

  @override
  void initState() {
    super.initState();
    _initTerminal();
  }

  @override
  void dispose() {
    _commandController.dispose();
    _scrollController.dispose();
    ref.read(terminalProvider.notifier).disconnect();
    super.dispose();
  }

  Future<void> _initTerminal() async {
    try {
      final api = ref.read(apiClientProvider);
      final projects = await api.getProjects();
      if (projects.isNotEmpty && mounted) {
        final id = projects.first['id'] as int;
        setState(() => _projectId = id);
        await ref.read(terminalProvider.notifier).connect(id);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Connection failed: $e')));
      }
    }
  }

  void _sendCommand() {
    final cmd = _commandController.text.trim();
    if (cmd.isEmpty) return;
    _commandController.clear();
    ref.read(terminalProvider.notifier).sendCommand(cmd);
    _scrollToBottom();
  }

  void _handleHistoryNavigate(int direction) {
    final result = ref.read(terminalProvider.notifier).navigateHistory(direction);
    if (result != null) {
      _commandController.text = result;
      _commandController.selection = TextSelection.collapsed(offset: result.length);
    } else if (direction == 1) {
      _commandController.clear();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 150),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final termState = ref.watch(terminalProvider);

    ref.listen<TerminalState>(terminalProvider, (_, next) {
      if (next.lines.length > (termState.lines.length)) {
        _scrollToBottom();
      }
    });

    return Scaffold(
      appBar: AppBar(
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('Terminal'),
            const SizedBox(width: 8),
            Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(
                color: termState.isConnected
                    ? const Color(0xFFA6E3A1)
                    : const Color(0xFFF38BA8),
                shape: BoxShape.circle,
              ),
            ),
          ],
        ),
        actions: [
          if (!termState.isConnected && _projectId != null)
            IconButton(
              icon: const Icon(Icons.refresh),
              onPressed: () => ref.read(terminalProvider.notifier).connect(_projectId!),
              tooltip: 'Reconnect',
            ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: TerminalOutputWidget(
              lines: termState.lines,
              scrollController: _scrollController,
            ),
          ),
          TerminalInputWidget(
            controller: _commandController,
            isConnected: termState.isConnected,
            isRunning: termState.isRunning,
            onSend: _sendCommand,
            onInterrupt: () => ref.read(terminalProvider.notifier).sendInterrupt(),
            onHistoryNavigate: _handleHistoryNavigate,
          ),
        ],
      ),
    );
  }
}
