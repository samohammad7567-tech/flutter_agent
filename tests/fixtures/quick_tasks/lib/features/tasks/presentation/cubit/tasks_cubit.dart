import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../../core/localization/lang_keys.dart';
import '../../../../core/utils/error_mapper.dart';
import '../../data/models/task_model.dart';
import '../../data/repos/tasks_repo.dart';
import 'tasks_state.dart';

class TasksCubit extends Cubit<TasksState> {
  TasksCubit({required this.repo}) : super(const TasksState()) {
    loadTasks();
  }

  final TasksRepo repo;

  Future<void> loadTasks() async {
    emit(state.copyWith(status: TasksStatus.loading));
    await _guard(repo.fetchTasks);
  }

  /// Reuses the load path without emitting loading, so a refresh does not flash
  /// a spinner over content already on screen.
  Future<void> refresh() => _guard(repo.fetchTasks);

  Future<void> addTask(String title) async {
    emit(state.copyWith(isSaving: true, clearError: true, clearMessage: true));
    await _guard(() => repo.addTask(title), messageKey: LangKeys.taskAdded);
  }

  Future<void> toggleTask(String id) =>
      _guard(() => repo.toggleTask(id));

  Future<void> deleteTask(String id) =>
      _guard(() => repo.deleteTask(id), messageKey: LangKeys.taskDeleted);

  Future<void> clearCompleted() => _guard(
    repo.clearCompleted,
    messageKey: LangKeys.completedCleared,
  );

  /// Tapping the active chip costs nothing — the list is already in state.
  void selectFilter(TasksFilter filter) {
    if (filter == state.filter) return;
    emit(state.copyWith(filter: filter, clearError: true, clearMessage: true));
  }

  /// Every mutation returns the whole list, so one guard covers them all.
  Future<void> _guard(
    Future<List<TaskModel>> Function() action, {
    String? messageKey,
  }) async {
    try {
      final List<TaskModel> tasks = await action();
      if (isClosed) return;

      emit(
        state.copyWith(
          status: tasks.isEmpty ? TasksStatus.empty : TasksStatus.success,
          tasks: tasks,
          messageKey: messageKey,
          isSaving: false,
          clearError: true,
          clearMessage: messageKey == null,
        ),
      );
    } on AppException catch (error) {
      if (isClosed) return;
      emit(
        state.copyWith(
          status: state.tasks.isEmpty ? TasksStatus.empty : TasksStatus.success,
          errorKey: error.key,
          isSaving: false,
          clearMessage: true,
        ),
      );
    } catch (error) {
      if (isClosed) return;
      emit(
        state.copyWith(
          status: TasksStatus.failure,
          errorKey: ErrorMapper.map(error),
          isSaving: false,
          clearMessage: true,
        ),
      );
    }
  }
}
