import 'dart:async';
import 'dart:convert';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/network/api_client.dart';
import '../../core/network/ws_client.dart';
import '../../core/crdt/sync_manager.dart';

class ChatMessage {
  final int id;
  final String role;
  final String content;
  final List<ToolCallInfo>? toolCalls;
  final DateTime createdAt;

  ChatMessage({
    required this.id,
    required this.role,
    required this.content,
    this.toolCalls,
    required this.createdAt,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) {
    List<ToolCallInfo>? calls;
    if (json['tool_calls_json'] != null) {
      try {
        final list = jsonDecode(json['tool_calls_json']) as List;
        calls = list.map((e) => ToolCallInfo.fromJson(e as Map<String, dynamic>)).toList();
      } catch (_) {}
    }
    return ChatMessage(
      id: json['id'] as int,
      role: json['role'] as String,
      content: json['content'] as String? ?? '',
      toolCalls: calls,
      createdAt: DateTime.tryParse(json['created_at'] as String? ?? '') ?? DateTime.now(),
    );
  }
}

class ToolCallInfo {
  final String id;
  final String name;
  final dynamic arguments;

  ToolCallInfo({required this.id, required this.name, this.arguments});

  factory ToolCallInfo.fromJson(Map<String, dynamic> json) => ToolCallInfo(
        id: json['id'] as String,
        name: json['name'] as String,
        arguments: json['arguments'],
      );
}

class ConversationInfo {
  final int id;
  final String title;
  final String model;
  final int? projectId;

  ConversationInfo({required this.id, required this.title, required this.model, this.projectId});

  factory ConversationInfo.fromJson(Map<String, dynamic> json) => ConversationInfo(
        id: json['id'] as int,
        title: json['title'] as String? ?? '',
        model: json['model'] as String? ?? 'glm-4-plus',
        projectId: json['project_id'] as int?,
      );
}

class ChatState {
  final List<ConversationInfo> conversations;
  final ConversationInfo? currentConversation;
  final List<ChatMessage> messages;
  final bool isLoading;
  final String streamingContent;
  final String error;

  const ChatState({
    this.conversations = const [],
    this.currentConversation,
    this.messages = const [],
    this.isLoading = false,
    this.streamingContent = '',
    this.error = '',
  });

  ChatState copyWith({
    List<ConversationInfo>? conversations,
    ConversationInfo? currentConversation,
    List<ChatMessage>? messages,
    bool? isLoading,
    String? streamingContent,
    String? error,
  }) =>
      ChatState(
        conversations: conversations ?? this.conversations,
        currentConversation: currentConversation ?? this.currentConversation,
        messages: messages ?? this.messages,
        isLoading: isLoading ?? this.isLoading,
        streamingContent: streamingContent ?? this.streamingContent,
        error: error ?? '',
      );
}

class ChatNotifier extends StateNotifier<ChatState> {
  final ApiClient _api;
  final WsClient _ws;
  final SyncManager _sync;
  StreamSubscription? _syncSubscription;

  ChatNotifier(this._api, this._ws, this._sync) : super(const ChatState());

  String _syncDocId(int convId) => 'chat:$convId';

  Future<void> loadConversations() async {
    try {
      final list = await _api.getConversations();
      final convs = list.map((e) => ConversationInfo.fromJson(e as Map<String, dynamic>)).toList();
      state = state.copyWith(conversations: convs);
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  Future<void> selectConversation(ConversationInfo conv) async {
    _syncSubscription?.cancel();
    _sync.disconnect(_syncDocId(conv.id));

    state = state.copyWith(currentConversation: conv);
    try {
      final msgs = await _api.getMessages(conv.id);
      final messages = msgs.map((e) => ChatMessage.fromJson(e as Map<String, dynamic>)).toList();
      state = state.copyWith(messages: messages);

      _sync.connect(_syncDocId(conv.id));
      _syncSubscription = _sync.onStateChange.listen((event) {
        if (event['type'] == 'update' && !state.isLoading) {
          _refreshMessages();
        }
      });
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  Future<void> _refreshMessages() async {
    final conv = state.currentConversation;
    if (conv == null) return;
    try {
      final msgs = await _api.getMessages(conv.id);
      final messages = msgs.map((e) => ChatMessage.fromJson(e as Map<String, dynamic>)).toList();
      state = state.copyWith(messages: messages);
    } catch (_) {}
  }

  Future<void> createConversation({String title = 'New Conversation', int? projectId}) async {
    try {
      final data = await _api.createConversation(title: title, projectId: projectId);
      final conv = ConversationInfo.fromJson(data);
      state = state.copyWith(
        conversations: [conv, ...state.conversations],
        currentConversation: conv,
        messages: [],
      );
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  Future<void> sendMessage(String content) async {
    if (state.currentConversation == null) {
      await createConversation();
    }
    final convId = state.currentConversation!.id;

    final userMsg = ChatMessage(
      id: DateTime.now().millisecondsSinceEpoch,
      role: 'user',
      content: content,
      createdAt: DateTime.now(),
    );
    state = state.copyWith(messages: [...state.messages, userMsg], isLoading: true, streamingContent: '');

    _sync.sendUpdate(_syncDocId(convId), {
      'last_user_message': content,
      'last_message_at': DateTime.now().toIso8601String(),
    });

    final stream = _ws.connect('/ws/chat/$convId');
    _ws.send('/ws/chat/$convId', {'content': content, 'model': 'glm-4-plus'});

    String assistantContent = '';

    try {
      await for (final event in stream.timeout(const Duration(seconds: 120))) {
        final type = event['type'] as String? ?? '';

        if (type == 'text_delta') {
          assistantContent += event['text'] as String? ?? '';
          state = state.copyWith(streamingContent: assistantContent);
        } else if (type == 'done') {
          final assistantMsg = ChatMessage(
            id: DateTime.now().millisecondsSinceEpoch,
            role: 'assistant',
            content: assistantContent,
            createdAt: DateTime.now(),
          );
          state = state.copyWith(
            messages: [...state.messages, assistantMsg],
            isLoading: false,
            streamingContent: '',
          );
          _sync.sendUpdate(_syncDocId(convId), {
            'last_assistant_message': assistantContent.substring(0, assistantContent.length > 200 ? 200 : assistantContent.length),
            'message_count': state.messages.length,
          });
          _ws.disconnect();
          return;
        } else if (type == 'error') {
          state = state.copyWith(
            isLoading: false,
            error: event['text'] as String? ?? 'Unknown error',
            streamingContent: '',
          );
          _ws.disconnect();
          return;
        }
      }
    } on TimeoutException {
      state = state.copyWith(
        isLoading: false,
        error: 'Response timed out',
        streamingContent: '',
      );
      _ws.disconnect();
    } catch (e) {
      state = state.copyWith(
        isLoading: false,
        error: e.toString(),
        streamingContent: '',
      );
      _ws.disconnect();
    }
  }

  @override
  void dispose() {
    _syncSubscription?.cancel();
    final convId = state.currentConversation?.id;
    if (convId != null) {
      _sync.disconnect(_syncDocId(convId));
    }
    super.dispose();
  }
}

final chatProvider = StateNotifierProvider<ChatNotifier, ChatState>((ref) {
  return ChatNotifier(
    ref.read(apiClientProvider),
    ref.read(wsClientProvider),
    ref.read(syncManagerProvider),
  );
});
