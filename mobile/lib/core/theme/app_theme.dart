import 'package:flutter/material.dart';

class AppTheme {
  static const _seed = Color(0xFF89B4FA);

  static final darkTheme = ThemeData(
    brightness: Brightness.dark,
    colorSchemeSeed: _seed,
    useMaterial3: true,
    scaffoldBackgroundColor: const Color(0xFF1E1E2E),
    appBarTheme: const AppBarTheme(
      backgroundColor: Color(0xFF181825),
      foregroundColor: Color(0xFFCDD6F4),
      elevation: 0,
    ),
    cardTheme: CardThemeData(
      color: const Color(0xFF181825),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: const Color(0xFF181825),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: Color(0xFF313244)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: _seed),
      ),
    ),
    bottomNavigationBarTheme: const BottomNavigationBarThemeData(
      backgroundColor: Color(0xFF181825),
      selectedItemColor: _seed,
      unselectedItemColor: Color(0xFF6C7086),
      type: BottomNavigationBarType.fixed,
    ),
  );
}
