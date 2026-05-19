import 'package:flutter/material.dart';

class AnsiSpan {
  final String text;
  final Color? color;
  final Color? bgColor;
  final bool bold;
  final bool italic;
  final bool underline;

  const AnsiSpan({
    required this.text,
    this.color,
    this.bgColor,
    this.bold = false,
    this.italic = false,
    this.underline = false,
  });

  TextStyle toStyle() => TextStyle(
        color: color ?? const Color(0xFFCDD6F4),
        backgroundColor: bgColor,
        fontWeight: bold ? FontWeight.bold : FontWeight.normal,
        fontStyle: italic ? FontStyle.italic : FontStyle.normal,
        decoration: underline ? TextDecoration.underline : TextDecoration.none,
        fontFamily: 'monospace',
        fontSize: 13,
        height: 1.5,
      );
}

class AnsiParser {
  static const _ansiRegex = r'\x1b\[([0-9;]*)m';

  // Catppuccin Mocha palette
  static const _colors = <int, Color>{
    30: Color(0xFF45475A), // Surface1
    31: Color(0xFFF38BA8), // Red
    32: Color(0xFFA6E3A1), // Green
    33: Color(0xFFF9E2AF), // Yellow
    34: Color(0xFF89B4FA), // Blue
    35: Color(0xFFF5C2E7), // Pink
    36: Color(0xFF94E2D5), // Teal
    37: Color(0xFFBAC2DE), // Subtext1
    90: Color(0xFF585B70), // Surface2
    91: Color(0xFFF38BA8),
    92: Color(0xFFA6E3A1),
    93: Color(0xFFF9E2AF),
    94: Color(0xFF89B4FA),
    95: Color(0xFFF5C2E7),
    96: Color(0xFF94E2D5),
    97: Color(0xFFCDD6F4), // Text
  };

  static const _bgColors = <int, Color>{
    40: Color(0xFF45475A),
    41: Color(0xFFF38BA8),
    42: Color(0xFFA6E3A1),
    43: Color(0xFFF9E2AF),
    44: Color(0xFF89B4FA),
    45: Color(0xFFF5C2E7),
    46: Color(0xFF94E2D5),
    47: Color(0xFFBAC2DE),
    100: Color(0xFF585B70),
    101: Color(0xFFF38BA8),
    102: Color(0xFFA6E3A1),
    103: Color(0xFFF9E2AF),
    104: Color(0xFF89B4FA),
    105: Color(0xFFF5C2E7),
    106: Color(0xFF94E2D5),
    107: Color(0xFFCDD6F4),
  };

  List<AnsiSpan> parse(String input) {
    final spans = <AnsiSpan>[];
    var bold = false;
    var italic = false;
    var underline = false;
    Color? fg;
    Color? bg;

    final regex = RegExp(_ansiRegex);
    var lastEnd = 0;

    for (final match in regex.allMatches(input)) {
      if (match.start > lastEnd) {
        final text = input.substring(lastEnd, match.start);
        if (text.isNotEmpty) {
          spans.add(AnsiSpan(
            text: text, color: fg, bgColor: bg, bold: bold, italic: italic, underline: underline,
          ));
        }
      }

      final codes = match.group(1)!.split(';');
      for (final codeStr in codes) {
        final code = int.tryParse(codeStr) ?? 0;
        if (code == 0) {
          bold = false; italic = false; underline = false; fg = null; bg = null;
        } else if (code == 1) {
          bold = true;
        } else if (code == 3) {
          italic = true;
        } else if (code == 4) {
          underline = true;
        } else if (_colors.containsKey(code)) {
          fg = _colors[code];
        } else if (_bgColors.containsKey(code)) {
          bg = _bgColors[code];
        }
      }
      lastEnd = match.end;
    }

    if (lastEnd < input.length) {
      final text = input.substring(lastEnd);
      if (text.isNotEmpty) {
        spans.add(AnsiSpan(
          text: text, color: fg, bgColor: bg, bold: bold, italic: italic, underline: underline,
        ));
      }
    }

    return spans;
  }

  List<List<AnsiSpan>> parseLines(String input) {
    final lines = input.split('\n');
    return lines.map((line) => parse(line)).toList();
  }
}
