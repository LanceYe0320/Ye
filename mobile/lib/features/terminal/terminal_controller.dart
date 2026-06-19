import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'ansi_parser.dart';
import '../../core/network/server_config.dart';

const _maxHistory = 100;
const _historyKey = 'terminal_command_history';

class TerminalLine {
  final List<AnsiSpan> spans;
  const TerminalLine(this.spans);
}

class TerminalState {
  final List<TerminalLine> lines;
  final bool isConnected;
  final bool isRunning;
  final List<String> commandHistory;
  final int historyPointer;
  final String? error;

  const TerminalState({
    this.lines = const [],
    this.isConnected = false,
    this.isRunning = false,
    this.commandHistory = const [],
    this.historyPointer = -1,
    this.error,
  });

  TerminalState copyWith({
    List<TerminalLine>? lines,
    bool? isConnected,
    bool? isRunning,
    List<String>? commandHistory,
    int? historyPointer,
    String? error,
  }) =>
      TerminalState(
        lines: lines ?? this.lines,
        isConnected: isConnected ?? this.isConnected,
        isRunning: isRunning ?? this.isRunning,
        commandHistory: commandHistory ?? this.commandHistory,
        historyPointer: historyPointer ?? this.historyPointer,
        error: error,
      );
}

class TerminalController extends StateNotifier<TerminalState> {
  final Ref _ref;
  WebSocketChannel? _channel;
  final _parser = AnsiParser();
  StreamSubscription? _subscription;
  String? _pendingBuffer;

  TerminalController(this._ref) : super(const TerminalState());

  Future<void> connect(int projectId) async {
    if (state.isConnected) return;

    _pendingBuffer = null;
    state = state.copyWith(lines: const []);

    try {
      final wsBaseAsync = _ref.read(wsBaseUrlProvider);
      final wsBase = wsBaseAsync.valueOrNull ?? 'ws://localhost:8765';
      final uri = Uri.parse('$wsBase/ws/terminal/$projectId');
      _channel = WebSocketChannel.connect(uri);

      state = state.copyWith(isConnected: true, error: null);

      _subscription = _channel?.stream.listen(
        (data) {
          final event = jsonDecode(data as String) as Map<String, dynamic>;
          _handleEvent(event);
        },
        onError: (e) {
          state = state.copyWith(isConnected: false, isRunning: false, error: e.toString());
        },
        onDone: () {
          state = state.copyWith(isConnected: false, isRunning: false);
        },
      );
    } catch (e) {
      state = state.copyWith(isConnected: false, error: e.toString());
    }

    await _loadHistory();
  }

  void _handleEvent(Map<String, dynamic> event) {
    final type = event['type'] as String? ?? '';
    final data = event['data'] as String? ?? '';

    switch (type) {
      case 'stdout':
        _appendOutput(data);
      case 'stderr':
        _appendOutput(data, isStderr: true);
      case 'exit':
        final exitCode = event['exit_code'] as int?;
        final exitMsg = exitCode != null && exitCode != 0 ? '\n[exit code: $exitCode]' : '\n';
        _appendOutput(exitMsg);
        state = state.copyWith(isRunning: false);
      case 'error':
        _appendOutput('\nError: $data\n');
        state = state.copyWith(isRunning: false);
    }
  }

  static const _maxLines = 1000;

  void _appendOutput(String text, {bool isStderr = false}) {
    _pendingBuffer = (_pendingBuffer ?? '') + text;

    final fullText = _pendingBuffer!;
    final lines = fullText.split('\n');

    final currentLines = List<TerminalLine>.from(state.lines);
    if (lines.length > 1) {
      for (var i = 0; i < lines.length - 1; i++) {
        final lineText = lines[i];
        if (isStderr) {
          currentLines.add(TerminalLine([
            AnsiSpan(text: lineText, color: const Color(0xFFF38BA8)),
          ]));
        } else {
          currentLines.add(TerminalLine(_parser.parse(lineText)));
        }
      }
      _pendingBuffer = lines.last;
    }

    // Trim old lines to prevent memory growth
    if (currentLines.length > _maxLines) {
      currentLines.removeRange(0, currentLines.length - _maxLines);
    }

    state = state.copyWith(lines: currentLines);
  }

  void sendCommand(String command) {
    if (command.trim().isEmpty || _channel == null) return;

    final commandLines = List<TerminalLine>.from(state.lines);
    commandLines.add(TerminalLine([
      const AnsiSpan(text: '\$ ', color: Color(0xFF89B4FA)),
      AnsiSpan(text: command, color: const Color(0xFFCDD6F4), bold: true),
    ]));
    state = state.copyWith(lines: commandLines, isRunning: true);
    _pendingBuffer = '';

    _channel?.sink.add(jsonEncode({'command': command}));
    _addToHistory(command);
  }

  void sendInterrupt() {
    if (_channel == null) return;
    _channel?.sink.add(jsonEncode({'type': 'interrupt'}));
  }

  String? navigateHistory(int direction) {
    final history = state.commandHistory;
    if (history.isEmpty) return null;

    var ptr = state.historyPointer + direction;
    if (ptr < 0) {
      state = state.copyWith(historyPointer: -1);
      return null;
    }
    if (ptr >= history.length) {
      ptr = history.length - 1;
    }

    state = state.copyWith(historyPointer: ptr);
    return history[ptr];
  }

  void _addToHistory(String command) {
    final history = List<String>.from(state.commandHistory);
    if (history.isNotEmpty && history.first == command) return;
    history.insert(0, command);
    if (history.length > _maxHistory) history.removeRange(_maxHistory, history.length);
    state = state.copyWith(commandHistory: history, historyPointer: -1);
    _saveHistory(history);
  }

  Future<void> _loadHistory() async {
    final prefs = await SharedPreferences.getInstance();
    final history = prefs.getStringList(_historyKey) ?? [];
    state = state.copyWith(commandHistory: history);
  }

  Future<void> _saveHistory(List<String> history) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_historyKey, history);
  }

  void disconnect() {
    _subscription?.cancel();
    _channel?.sink.close();
    _channel = null;
    state = state.copyWith(isConnected: false);
  }

  @override
  void dispose() {
    disconnect();
    super.dispose();
  }
}

final terminalProvider = StateNotifierProvider<TerminalController, TerminalState>((ref) {
  return TerminalController(ref);
});
