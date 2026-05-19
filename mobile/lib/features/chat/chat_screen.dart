import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'chat_controller.dart';
import 'tool_call_widget.dart';

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(chatProvider.notifier).loadConversations();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _send() {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    _controller.clear();
    ref.read(chatProvider.notifier).sendMessage(text);
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(chatProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('AI Chat'),
        actions: [
          IconButton(
            icon: const Icon(Icons.add_comment_outlined),
            onPressed: () => ref.read(chatProvider.notifier).createConversation(),
          ),
        ],
      ),
      body: Column(
        children: [
          // Conversation selector
          if (state.conversations.isNotEmpty)
            SizedBox(
              height: 44,
              child: ListView.builder(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                itemCount: state.conversations.length,
                itemBuilder: (_, i) {
                  final conv = state.conversations[i];
                  final isActive = state.currentConversation?.id == conv.id;
                  return Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: ChoiceChip(
                      label: Text(conv.title, style: const TextStyle(fontSize: 12)),
                      selected: isActive,
                      onSelected: (_) => ref.read(chatProvider.notifier).selectConversation(conv),
                    ),
                  );
                },
              ),
            ),

          // Messages
          Expanded(
            child: state.messages.isEmpty && !state.isLoading
                ? const Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.chat_bubble_outline, size: 48, color: Color(0xFF6C7086)),
                        SizedBox(height: 12),
                        Text('Start a conversation', style: TextStyle(color: Color(0xFF6C7086))),
                        SizedBox(height: 4),
                        Text('Ask me to read files, run commands, or write code',
                            style: TextStyle(color: Color(0xFF6C7086), fontSize: 12)),
                      ],
                    ),
                  )
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(12),
                    itemCount: state.messages.length + (state.isLoading ? 1 : 0),
                    itemBuilder: (_, i) {
                      if (i == state.messages.length) {
                        // Streaming message
                        return _MessageBubble(
                          role: 'assistant',
                          child: MarkdownBody(
                            data: state.streamingContent.isEmpty ? 'Thinking...' : state.streamingContent,
                          ),
                        );
                      }
                      final msg = state.messages[i];
                      if (msg.role == 'user') {
                        return _MessageBubble(
                          role: 'user',
                          child: Text(msg.content, style: const TextStyle(fontSize: 14)),
                        );
                      }
                      return _MessageBubble(
                        role: 'assistant',
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            MarkdownBody(data: msg.content),
                            if (msg.toolCalls != null)
                              ...msg.toolCalls!.map((tc) => ToolCallWidget(toolCall: tc)),
                          ],
                        ),
                      );
                    },
                  ),
          ),

          // Error banner
          if (state.error.isNotEmpty)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(8),
              color: Colors.red.withOpacity(0.1),
              child: Text(state.error, style: const TextStyle(color: Colors.red, fontSize: 12)),
            ),

          // Input
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
              child: Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      decoration: const InputDecoration(
                        hintText: 'Send a message...',
                        border: OutlineInputBorder(),
                        contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                      ),
                      maxLines: 3,
                      minLines: 1,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => _send(),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filled(
                    icon: state.isLoading
                        ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.arrow_upward),
                    onPressed: state.isLoading ? null : _send,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  final String role;
  final Widget child;

  const _MessageBubble({required this.role, required this.child});

  @override
  Widget build(BuildContext context) {
    final isUser = role == 'user';
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(12),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.85),
        decoration: BoxDecoration(
          color: isUser ? const Color(0xFFA6E3A1).withOpacity(0.15) : const Color(0xFF181825),
          borderRadius: BorderRadius.circular(12),
          border: isUser
              ? Border.all(color: const Color(0xFFA6E3A1).withOpacity(0.3))
              : null,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              isUser ? 'You' : 'Assistant',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: isUser ? const Color(0xFFA6E3A1) : const Color(0xFF89B4FA),
              ),
            ),
            const SizedBox(height: 4),
            child,
          ],
        ),
      ),
    );
  }
}
