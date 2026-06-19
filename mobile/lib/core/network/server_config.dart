import 'dart:io';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

const _storage = FlutterSecureStorage();
const _serverUrlKey = 'server_url';

String get _defaultHost {
  if (Platform.isAndroid) return '10.0.2.2';
  return 'localhost';
}

const _defaultPort = '8765';

Future<String> _getStoredUrl() async {
  final stored = await _storage.read(key: _serverUrlKey);
  if (stored != null && stored.isNotEmpty) return stored;
  return 'http://${_defaultHost}:$_defaultPort';
}

final serverUrlProvider = FutureProvider<String>((ref) => _getStoredUrl());

final httpBaseUrlProvider = FutureProvider<String>((ref) async {
  final url = await ref.watch(serverUrlProvider.future);
  return url;
});

final wsBaseUrlProvider = FutureProvider<String>((ref) async {
  final url = await ref.watch(serverUrlProvider.future);
  if (url.startsWith('https://')) {
    return 'wss://${url.substring(8)}';
  } else if (url.startsWith('http://')) {
    return 'ws://${url.substring(7)}';
  }
  return 'ws://$url';
});
