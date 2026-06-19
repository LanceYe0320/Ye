import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../features/auth/auth_screen.dart';
import '../../features/chat/chat_screen.dart';
import '../../features/files/file_browser_screen.dart';
import '../../features/git/git_screen.dart';
import '../../features/projects/project_screen.dart';
import '../../features/search/search_screen.dart';
import '../../features/terminal/terminal_view_screen.dart';
import '../../features/settings/settings_screen.dart';
import '../../core/storage/local_db.dart';

final _rootNavigatorKey = GlobalKey<NavigatorState>();

final authProvider = FutureProvider<bool>((ref) async {
  final token = await LocalStorage.getToken();
  return token != null && token.isNotEmpty;
});

final routerProvider = Provider<GoRouter>((ref) {
  final authAsync = ref.watch(authProvider);
  final isAuthenticated = authAsync.valueOrNull ?? false;

  return GoRouter(
    navigatorKey: _rootNavigatorKey,
    initialLocation: isAuthenticated ? '/home' : '/auth',
    redirect: (context, state) {
      final isAuthRoute = state.matchedLocation == '/auth';
      if (!isAuthenticated && !isAuthRoute) return '/auth';
      if (isAuthenticated && isAuthRoute) return '/home';
      return null;
    },
    routes: [
      GoRoute(
        path: '/auth',
        builder: (_, __) => const AuthScreen(),
      ),
      StatefulShellRoute.indexedStack(
        builder: (_, __, navigationShell) => Scaffold(
          body: navigationShell,
          bottomNavigationBar: BottomNavigationBar(
            currentIndex: navigationShell.currentIndex,
            onTap: (index) => navigationShell.goBranch(
              index,
              initialLocation: index == navigationShell.currentIndex,
            ),
            type: BottomNavigationBarType.fixed,
            items: const [
              BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: 'Chat'),
              BottomNavigationBarItem(icon: Icon(Icons.search), label: 'Search'),
              BottomNavigationBarItem(icon: Icon(Icons.folder_outlined), label: 'Files'),
              BottomNavigationBarItem(icon: Icon(Icons.terminal), label: 'Terminal'),
              BottomNavigationBarItem(icon: Icon(Icons.call_split), label: 'Git'),
              BottomNavigationBarItem(icon: Icon(Icons.widgets_outlined), label: 'Projects'),
              BottomNavigationBarItem(icon: Icon(Icons.settings_outlined), label: 'Settings'),
            ],
          ),
        ),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(path: '/home', builder: (_, __) => const ChatScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/search', builder: (_, __) => const SearchScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/files', builder: (_, __) => const FileBrowserScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/terminal', builder: (_, __) => const TerminalViewScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/git', builder: (_, __) => const GitScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/projects', builder: (_, __) => const ProjectScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/settings', builder: (_, __) => const SettingsScreen()),
          ]),
        ],
      ),
    ],
  );
});
