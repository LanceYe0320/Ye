import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../features/chat/chat_screen.dart';
import '../../features/files/file_browser_screen.dart';
import '../../features/terminal/terminal_view_screen.dart';
import '../../features/settings/settings_screen.dart';

final _rootNavigatorKey = GlobalKey<NavigatorState>();

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    navigatorKey: _rootNavigatorKey,
    initialLocation: '/chat',
    routes: [
      StatefulShellRoute.indexedStack(
        builder: (_, __, navigationShell) => Scaffold(
          body: navigationShell,
          bottomNavigationBar: BottomNavigationBar(
            currentIndex: navigationShell.currentIndex,
            onTap: (index) => navigationShell.goBranch(
              index,
              initialLocation: index == navigationShell.currentIndex,
            ),
            items: const [
              BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: 'Chat'),
              BottomNavigationBarItem(icon: Icon(Icons.folder_outlined), label: 'Files'),
              BottomNavigationBarItem(icon: Icon(Icons.terminal), label: 'Terminal'),
              BottomNavigationBarItem(icon: Icon(Icons.settings_outlined), label: 'Settings'),
            ],
          ),
        ),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(path: '/chat', builder: (_, __) => const ChatScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/files', builder: (_, __) => const FileBrowserScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/terminal', builder: (_, __) => const TerminalViewScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/settings', builder: (_, __) => const SettingsScreen()),
          ]),
        ],
      ),
    ],
  );
});
