import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/server_config.dart';

class SyncManager {
  static const _maxQueueSize = 100;

  String _wsBase;
  WebSocketChannel? _channel;
  final Map<String, dynamic> _state = {};
  int _version = 0;
  bool _connected = false;
  final List<Map<String, dynamic>> _offlineQueue = [];
  final _stateController = StreamController<Map<String, dynamic>>.broadcast();

  SyncManager(this._wsBase);

  Map<String, dynamic> get state => Map.unmodifiable(_state);
  bool get isConnected => _connected;
  Stream<Map<String, dynamic>> get onStateChange => _stateController.stream;

  void connect(String docId) {
    final uri = Uri.parse('$_wsBase/ws/sync');
    _channel = WebSocketChannel.connect(uri);
    _connected = true;

    _channel!.stream.listen(
      (data) {
        final msg = jsonDecode(data as String) as Map<String, dynamic>;
        final type = msg['type'] as String? ?? '';

        if (type == 'sync_full') {
          _state.clear();
          _state.addAll(msg['state'] as Map<String, dynamic>? ?? {});
          _version = msg['version'] as int? ?? 0;
          _stateController.add({'type': 'full', 'state': Map.from(_state)});
          _flushOfflineQueue(docId);
        } else if (type == 'sync_update') {
          _state.addAll(msg['update'] as Map<String, dynamic>? ?? {});
          _version = msg['version'] as int? ?? 0;
          _stateController.add({'type': 'update', 'state': Map.from(_state)});
        }
      },
      onDone: () {
        _connected = false;
        _stateController.add({'type': 'disconnected'});
      },
      onError: (_) {
        _connected = false;
      },
    );

    _channel!.sink.add(jsonEncode({'type': 'subscribe', 'doc_id': docId}));
  }

  void sendUpdate(String docId, Map<String, dynamic> update) {
    final message = jsonEncode({
      'type': 'sync_update',
      'doc_id': docId,
      'update': update,
    });

    if (_connected && _channel != null) {
      _channel!.sink.add(message);
    } else {
      if (_offlineQueue.length >= _maxQueueSize) {
        _offlineQueue.removeAt(0);
      }
      _offlineQueue.add({'doc_id': docId, 'update': update});
    }
  }

  void _flushOfflineQueue(String docId) {
    while (_offlineQueue.isNotEmpty) {
      final item = _offlineQueue.removeAt(0);
      sendUpdate(item['doc_id'] as String, item['update'] as Map<String, dynamic>);
    }
  }

  void disconnect(String docId) {
    if (_channel != null) {
      _channel!.sink.add(jsonEncode({'type': 'unsubscribe', 'doc_id': docId}));
      _channel!.sink.close();
    }
    _connected = false;
    _stateController.close();
  }
}

final syncManagerProvider = Provider<SyncManager>((ref) {
  final wsBaseAsync = ref.watch(wsBaseUrlProvider);
  final wsBase = wsBaseAsync.valueOrNull ?? 'ws://10.0.2.2:8765';
  return SyncManager(wsBase);
});
