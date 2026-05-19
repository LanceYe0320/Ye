import 'package:flutter/material.dart';

class TerminalInputWidget extends StatelessWidget {
  final TextEditingController controller;
  final bool isConnected;
  final bool isRunning;
  final VoidCallback onSend;
  final VoidCallback onInterrupt;
  final ValueChanged<int> onHistoryNavigate;

  const TerminalInputWidget({
    super.key,
    required this.controller,
    required this.isConnected,
    required this.isRunning,
    required this.onSend,
    required this.onInterrupt,
    required this.onHistoryNavigate,
  });

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Container(
        margin: const EdgeInsets.fromLTRB(8, 4, 8, 8),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: const Color(0xFF181825),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: const Color(0xFF313244)),
        ),
        child: Row(
          children: [
            _buildStatusDot(),
            const SizedBox(width: 8),
            const Text(
              '\$ ',
              style: TextStyle(
                fontFamily: 'monospace',
                color: Color(0xFF89B4FA),
                fontSize: 14,
              ),
            ),
            Expanded(
              child: TextField(
                controller: controller,
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 14,
                  color: Color(0xFFCDD6F4),
                ),
                decoration: const InputDecoration(
                  hintText: 'Enter command...',
                  hintStyle: TextStyle(color: Color(0xFF585B70)),
                  border: InputBorder.none,
                  isDense: true,
                  contentPadding: EdgeInsets.symmetric(vertical: 6),
                ),
                textInputAction: TextInputAction.go,
                onSubmitted: (_) => onSend(),
                enabled: isConnected,
              ),
            ),
            if (isRunning)
              IconButton(
                icon: const Icon(Icons.stop, color: Color(0xFFF38BA8), size: 20),
                onPressed: onInterrupt,
                tooltip: 'Ctrl+C',
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
              )
            else
              IconButton(
                icon: Icon(
                  Icons.play_arrow,
                  color: isConnected ? const Color(0xFFA6E3A1) : const Color(0xFF585B70),
                  size: 20,
                ),
                onPressed: isConnected ? onSend : null,
                tooltip: 'Run',
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
              ),
            IconButton(
              icon: const Icon(Icons.keyboard_arrow_up, size: 18, color: Color(0xFF6C7086)),
              onPressed: () => onHistoryNavigate(-1),
              tooltip: 'Previous command',
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
            ),
            IconButton(
              icon: const Icon(Icons.keyboard_arrow_down, size: 18, color: Color(0xFF6C7086)),
              onPressed: () => onHistoryNavigate(1),
              tooltip: 'Next command',
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(minWidth: 28, minHeight: 28),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildStatusDot() {
    final color = isConnected
        ? (isRunning ? const Color(0xFFF9E2AF) : const Color(0xFFA6E3A1))
        : const Color(0xFFF38BA8);
    return Container(
      width: 8,
      height: 8,
      decoration: BoxDecoration(
        color: color,
        shape: BoxShape.circle,
      ),
    );
  }
}
