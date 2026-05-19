import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'server_config.dart';

final dioProvider = Provider<Dio>((ref) {
  final baseUrlAsync = ref.watch(serverUrlProvider);
  final baseUrl = baseUrlAsync.valueOrNull ?? 'http://10.0.2.2:8765';

  final dio = Dio(BaseOptions(
    baseUrl: baseUrl,
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 30),
    headers: {'Content-Type': 'application/json'},
  ));

  dio.interceptors.add(AuthInterceptor(ref));
  return dio;
});

class AuthInterceptor extends Interceptor {
  final Ref _ref;
  AuthInterceptor(this._ref);

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) async {
    const storage = FlutterSecureStorage();
    final token = await storage.read(key: 'jwt_token');
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }
}

class ApiClient {
  final Dio _dio;

  ApiClient(this._dio);

  // Conversations
  Future<List<dynamic>> getConversations() async {
    final res = await _dio.get('/api/conversations/');
    return res.data;
  }

  Future<Map<String, dynamic>> createConversation({
    String title = 'New Conversation',
    int? projectId,
    String model = 'glm-4-plus',
  }) async {
    final res = await _dio.post('/api/conversations/', data: {
      'title': title,
      'project_id': projectId,
      'model': model,
    });
    return res.data;
  }

  Future<List<dynamic>> getMessages(int conversationId) async {
    final res = await _dio.get('/api/conversations/$conversationId/messages/');
    return res.data;
  }

  Future<void> deleteConversation(int id) async {
    await _dio.delete('/api/conversations/$id');
  }

  // Projects
  Future<List<dynamic>> getProjects() async {
    final res = await _dio.get('/api/projects/');
    return res.data;
  }

  Future<Map<String, dynamic>> createProject(String name, String path) async {
    final res = await _dio.post('/api/projects/', data: {'name': name, 'path': path});
    return res.data;
  }

  // Files
  Future<List<dynamic>> listFiles(int projectId, {String path = ''}) async {
    final res = await _dio.get('/api/projects/$projectId/files/', queryParameters: {'path': path});
    return res.data;
  }

  Future<Map<String, dynamic>> readFile(int projectId, String filePath) async {
    final encoded = Uri.encodeComponent(filePath);
    final res = await _dio.get('/api/projects/$projectId/files/$encoded');
    return res.data;
  }

  Future<void> writeFile(int projectId, String filePath, String content) async {
    final encoded = Uri.encodeComponent(filePath);
    await _dio.put('/api/projects/$projectId/files/$encoded', data: {'content': content});
  }

  // Files - create
  Future<Map<String, dynamic>> createEntry(int projectId, String name, {String path = '', bool isDir = false}) async {
    final queryParams = <String, dynamic>{};
    if (path.isNotEmpty) queryParams['path'] = path;
    final res = await _dio.post('/api/projects/$projectId/files/', data: {
      'name': name,
      'is_dir': isDir,
    }, queryParameters: queryParams);
    return res.data;
  }

  // Terminal
  Future<Map<String, dynamic>> executeCommand(int projectId, String command, {int? timeout}) async {
    final res = await _dio.post('/api/projects/$projectId/terminal/execute', data: {
      'command': command,
      'timeout': timeout,
    });
    return res.data;
  }

  // Settings
  Future<Map<String, dynamic>> getSettings() async {
    final res = await _dio.get('/api/settings/');
    final data = res.data;
    if (data is Map<String, dynamic> && data.containsKey('settings')) {
      return Map<String, dynamic>.from(data['settings'] as Map);
    }
    return {};
  }

  Future<Map<String, dynamic>> updateSettings(Map<String, dynamic> settings) async {
    final res = await _dio.put('/api/settings/', data: {'settings': settings});
    final data = res.data;
    if (data is Map<String, dynamic> && data.containsKey('settings')) {
      return Map<String, dynamic>.from(data['settings'] as Map);
    }
    return settings;
  }
}

final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(ref.read(dioProvider));
});
