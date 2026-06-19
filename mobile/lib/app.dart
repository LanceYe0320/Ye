import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import 'core/theme/app_theme.dart';
import 'core/router/app_router.dart';

final connectivityProvider = StreamProvider<List<ConnectivityResult>>((ref) {
  return Connectivity().onConnectivityChanged;
});

class App extends ConsumerWidget {
  const App({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    final connectivityAsync = ref.watch(connectivityProvider);
    final isOffline = connectivityAsync.valueOrNull?.contains(ConnectivityResult.none) ?? false;

    return MaterialApp.router(
      title: 'AI Coding Assistant',
      theme: AppTheme.darkTheme,
      routerConfig: router,
      debugShowCheckedModeBanner: false,
      builder: (context, child) {
        return Column(
          children: [
            if (isOffline)
              Material(
                color: const Color(0xFFF38BA8),
                child: const SafeArea(
                  bottom: false,
                  child: SizedBox(
                    width: double.infinity,
                    height: 24,
                    child: Center(
                      child: Text(
                        'No internet connection',
                        style: TextStyle(color: Color(0xFF1E1E2E), fontSize: 11, fontWeight: FontWeight.w600),
                      ),
                    ),
                  ),
                ),
              ),
            Expanded(child: child ?? const SizedBox.shrink()),
          ],
        );
      },
    );
  }
}
