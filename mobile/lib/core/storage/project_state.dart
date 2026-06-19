import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../network/api_client.dart';

const _storage = FlutterSecureStorage();
const _projectIdKey = 'current_project_id';

final currentProjectIdProvider = StateNotifierProvider<CurrentProjectNotifier, int?>((ref) {
  return CurrentProjectNotifier();
});

class CurrentProjectNotifier extends StateNotifier<int?> {
  CurrentProjectNotifier() : super(null);

  Future<void> loadLastProject() async {
    final stored = await _storage.read(key: _projectIdKey);
    if (stored != null) {
      state = int.tryParse(stored);
    }
  }

  Future<void> setProject(int? id) async {
    state = id;
    if (id != null) {
      await _storage.write(key: _projectIdKey, value: id.toString());
    } else {
      await _storage.delete(key: _projectIdKey);
    }
  }
}

final projectsListProvider = FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final api = ref.read(apiClientProvider);
  final list = await api.getProjects();
  return list.cast<Map<String, dynamic>>();
});
