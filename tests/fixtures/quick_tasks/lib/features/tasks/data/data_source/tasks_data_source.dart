import 'dart:convert';

import 'package:corereusablepackage/corereusablepackage.dart';

import '../../../../core/localization/lang_keys.dart';
import '../../../../core/utils/error_mapper.dart';
import '../models/task_model.dart';

/// The only layer that touches storage.
///
/// Backed by [AppCacheService] rather than a backend because the list is
/// per-device by design — there is no account to sync it to. Every mutation
/// rewrites the whole list and returns it, so the cubit never has to merge.
class TasksDataSource {
  const TasksDataSource(this._cache);

  final AppCacheService _cache;

  static const String _key = 'quick_tasks_items';

  Future<List<TaskModel>> fetchTasks() async {
    final String? raw = _cache.getString(_key);
    if (raw == null || raw.isEmpty) return const <TaskModel>[];

    final Object? decoded = jsonDecode(raw);
    if (decoded is! List) return const <TaskModel>[];

    final List<TaskModel> tasks = decoded
        .whereType<Map<String, dynamic>>()
        .map(TaskModel.fromJson)
        .where((TaskModel task) => task.id.isNotEmpty)
        .toList();

    return _sorted(tasks);
  }

  /// Normalizes whitespace, rejects an empty title, and refuses a duplicate
  /// case-insensitively — all three are storage concerns, not UI concerns.
  Future<List<TaskModel>> addTask(String title) async {
    final String normalized = title.trim().replaceAll(RegExp(r'\s+'), ' ');
    if (normalized.isEmpty) {
      throw const AppException(LangKeys.errorEmptyTitle);
    }

    final List<TaskModel> tasks = await fetchTasks();
    final bool exists = tasks.any(
      (TaskModel task) =>
          task.title.toLowerCase() == normalized.toLowerCase(),
    );
    if (exists) throw const AppException(LangKeys.errorDuplicateTask);

    final DateTime now = DateTime.now();
    tasks.add(
      TaskModel(
        id: now.microsecondsSinceEpoch.toString(),
        title: normalized,
        createdAt: now,
      ),
    );

    return _write(tasks);
  }

  Future<List<TaskModel>> toggleTask(String id) async {
    final List<TaskModel> tasks = await fetchTasks();
    final int index = tasks.indexWhere((TaskModel task) => task.id == id);
    if (index == -1) throw const AppException(LangKeys.errorTaskNotFound);

    tasks[index] = tasks[index].copyWith(isDone: !tasks[index].isDone);
    return _write(tasks);
  }

  Future<List<TaskModel>> deleteTask(String id) async {
    final List<TaskModel> tasks = await fetchTasks();
    final int before = tasks.length;
    tasks.removeWhere((TaskModel task) => task.id == id);
    if (tasks.length == before) {
      throw const AppException(LangKeys.errorTaskNotFound);
    }

    return _write(tasks);
  }

  Future<List<TaskModel>> clearCompleted() async {
    final List<TaskModel> tasks = await fetchTasks();
    tasks.removeWhere((TaskModel task) => task.isDone);
    return _write(tasks);
  }

  Future<List<TaskModel>> _write(List<TaskModel> tasks) async {
    final List<TaskModel> ordered = _sorted(tasks);
    await _cache.setString(
      _key,
      jsonEncode(
        ordered.map((TaskModel task) => task.toJson()).toList(growable: false),
      ),
    );
    return ordered;
  }

  /// Open tasks first, newest within each group — the order the list is read in.
  List<TaskModel> _sorted(List<TaskModel> tasks) {
    tasks.sort((TaskModel a, TaskModel b) {
      if (a.isDone != b.isDone) return a.isDone ? 1 : -1;
      return b.createdAt.compareTo(a.createdAt);
    });
    return tasks;
  }
}
