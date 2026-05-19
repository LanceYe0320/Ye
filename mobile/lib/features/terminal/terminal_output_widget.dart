import 'package:flutter/material.dart';
import 'ansi_parser.dart';
import 'terminal_controller.dart';

class TerminalOutputWidget extends StatelessWidget {
  final List<TerminalLine> lines;
  final ScrollController scrollController;

  const TerminalOutputWidget({
    super.key,
    required this.lines,
    required this.scrollController,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.fromLTRB(8, 8, 8, 0),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFF11111B),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFF313244)),
      ),
      child: ListView.builder(
        controller: scrollController,
        itemCount: lines.isEmpty ? 1 : lines.length,
        itemBuilder: (_, index) {
          if (lines.isEmpty) {
            return const Padding(
              padding: EdgeInsets.symmetric(vertical: 4),
              child: Text(
                'Terminal ready. Connect and type a command.',
                style: TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 13,
                  color: Color(0xFF6C7086),
                  height: 1.5,
                ),
              ),
            );
          }
          final line = lines[index];
          if (line.spans.isEmpty) {
            return const SizedBox(height: 20);
          }
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 0.5),
            child: RichText(
              text: TextSpan(
                children: line.spans.map((span) => TextSpan(
                  text: span.text,
                  style: span.toStyle(),
                )).toList(),
              ),
            ),
          );
        },
      ),
    );
  }
}
