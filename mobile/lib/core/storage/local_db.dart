import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class LocalStorage {
  static const _storage = FlutterSecureStorage();

  static Future<String?> getToken() => _storage.read(key: 'jwt_token');
  static Future<void> setToken(String token) => _storage.write(key: 'jwt_token', value: token);
  static Future<void> deleteToken() => _storage.delete(key: 'jwt_token');

  static Future<String?> getServerUrl() => _storage.read(key: 'server_url');
  static Future<void> setServerUrl(String url) => _storage.write(key: 'server_url', value: url);
}

final localStorageProvider = Provider<LocalStorage>((ref) => LocalStorage());
