import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/server_config.dart';

enum UpdatePriority { low, normal, high }

class _QueuedUpdate {
  final String docId;
  final Map<String, dynamic> update;
  final UpdatePriority priority;
  final DateTime timestamp;

  _QueuedUpdate(this.docId, this.update, this.priority, this.timestamp);
}

class SyncManager {
  static const _maxQueueSize = 100;

  final String _wsBase;
  WebSocketChannel? _channel;
  final Map<String, dynamic> _state = {};
  int _version = 0;
  bool _connected = false;
  final List<_QueuedUpdate> _offlineQueue = [];
  StreamController<Map<String, dynamic>> _stateController =
      StreamController<Map<String, dynamic>>.broadcast();

  SyncManager(this._wsBase);

  Map<String, dynamic> get state => Map.unmodifiable(_state);
  bool get isConnected => _connected;
  Stream<Map<String, dynamic>> get onStateChange => _stateController.stream;

  void _ensureController() {
    if (_stateController.isClosed) {
      _stateController = StreamController<Map<String, dynamic>>.broadcast();
    }
  }

  void connect(String docId) {
    _channel?.sink.close();

    _ensureController();

    final uri = Uri.parse('$_wsBase/ws/sync');
    _channel = WebSocketChannel.connect(uri);
    _connected = true;

    _channel?.stream.listen(
      (data) {
        try {
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
        } catch (e) {
          _stateController.add({'type': 'error', 'error': e.toString()});
        }
      },
      onDone: () {
        _connected = false;
        _ensureController();
        _stateController.add({'type': 'disconnected'});
      },
      onError: (error) {
        _connected = false;
        _stateController.add({'type': 'error', 'error': error.toString()});
      },
    );

    _channel?.sink.add(jsonEncode({'type': 'subscribe', 'doc_id': docId}));
  }

  void sendUpdate(
    String docId,
    Map<String, dynamic> update, {
    UpdatePriority priority = UpdatePriority.normal,
  }) {
    final message = jsonEncode({
      'type': 'sync_update',
      'doc_id': docId,
      'update': update,
    });

    if (_connected && _channel != null) {
      _channel?.sink.add(message);
    } else {
      _mergeOrUpdate(docId, update, priority);
    }
  }

  void _mergeOrUpdate(
    String docId,
    Map<String, dynamic> update,
    UpdatePriority priority,
  ) {
    // Merge with existing queued update for the same docId (last-write-wins per key)
    for (int i = _offlineQueue.length - 1; i >= 0; i--) {
      if (_offlineQueue[i].docId == docId) {
        _offlineQueue[i].update.addAll(update);
        // Upgrade priority if new update is higher
        if (priority.index > _offlineQueue[i].priority.index) {
          _offlineQueue[i] = _QueuedUpdate(
            docId,
            _offlineQueue[i].update,
            priority,
            _offlineQueue[i].timestamp,
          );
        }
        return;
      }
    }

    if (_offlineQueue.length >= _maxQueueSize) {
      _evictOne();
    }
    _offlineQueue.add(
      _QueuedUpdate(docId, Map.from(update), priority, DateTime.now()),
    );
  }

  void _evictOne() {
    // Find the lowest-priority, oldest entry to evict
    int victimIdx = 0;
    for (int i = 1; i < _offlineQueue.length; i++) {
      final current = _offlineQueue[i];
      final victim = _offlineQueue[victimIdx];
      if (current.priority.index < victim.priority.index ||
          (current.priority == victim.priority &&
              current.timestamp.isBefore(victim.timestamp))) {
        victimIdx = i;
      }
    }
    _offlineQueue.removeAt(victimIdx);
  }

  void _flushOfflineQueue(String docId) {
    while (_offlineQueue.isNotEmpty) {
      if (!_connected || _channel == null) break;
      final item = _offlineQueue.removeAt(0);
      // Send directly to channel to avoid re-queuing if disconnect happens mid-flush
      _channel?.sink.add(jsonEncode({
        'type': 'sync_update',
        'doc_id': item.docId,
        'update': item.update,
      }));
    }
  }

  void disconnect(String docId) {
    if (_channel != null) {
      _channel?.sink.add(jsonEncode({'type': 'unsubscribe', 'doc_id': docId}));
      _channel?.sink.close();
      _channel = null;
    }
    _connected = false;
  }
}

final syncManagerProvider = Provider<SyncManager>((ref) {
  final wsBaseAsync = ref.watch(wsBaseUrlProvider);
  final wsBase = wsBaseAsync.valueOrNull ?? 'ws://localhost:8765';
  return SyncManager(wsBase);
});
