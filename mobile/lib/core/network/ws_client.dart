import 'dart:async';
import 'dart:convert';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'server_config.dart';

class WsClient {
  String _wsBase;
  WebSocketChannel? _channel;
  final _controllers = <String, StreamController<Map<String, dynamic>>>{};
  bool _connected = false;

  WsClient(this._wsBase);

  bool get isConnected => _connected;

  void updateBaseUrl(String wsBase) {
    _wsBase = wsBase;
  }

  Stream<Map<String, dynamic>> connect(String path) {
    if (_channel != null) {
      _channel?.sink.close();
      _connected = false;
    }

    final controller = StreamController<Map<String, dynamic>>.broadcast();
    final uri = Uri.parse('$_wsBase$path');
    _channel = WebSocketChannel.connect(uri);
    _connected = true;

    _channel!.stream.listen(
      (data) {
        final parsed = jsonDecode(data as String) as Map<String, dynamic>;
        controller.add(parsed);
      },
      onError: (error) {
        controller.addError(error);
        _connected = false;
      },
      onDone: () {
        _connected = false;
        controller.close();
      },
    );

    _controllers[path] = controller;
    return controller.stream;
  }

  void send(String path, Map<String, dynamic> data) {
    _channel?.sink.add(jsonEncode(data));
  }

  void disconnect() {
    _connected = false;
    _channel?.sink.close();
    for (final c in _controllers.values) {
      c.close();
    }
    _controllers.clear();
  }
}

final wsClientProvider = Provider<WsClient>((ref) {
  final wsBaseAsync = ref.watch(wsBaseUrlProvider);
  final wsBase = wsBaseAsync.valueOrNull ?? 'ws://10.0.2.2:8765';
  return WsClient(wsBase);
});
