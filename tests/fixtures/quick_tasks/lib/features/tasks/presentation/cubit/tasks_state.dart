import 'package:equatable/equatable.dart';

import '../../data/models/task_model.dart';

enum TasksStatus { loading, success, empty, failure }

enum TasksFilter { all, active, completed }

final class TasksState extends Equatable {
  const TasksState({
    this.status = TasksStatus.loading,
    this.tasks = const <TaskModel>[],
    this.filter = TasksFilter.all,
    this.errorKey,
    this.messageKey,
    this.isSaving = false,
  });

  final TasksStatus status;
  final List<TaskModel> tasks;
  final TasksFilter filter;

  /// Set when something failed; the UI translates it and shows a toast.
  final String? errorKey;

  /// Set after a successful mutation, for the same reason.
  final String? messageKey;

  final bool isSaving;

  /// The list the body renders. Filtering lives here so no widget branches.
  List<TaskModel> get visibleTasks => switch (filter) {
    TasksFilter.all => tasks,
    TasksFilter.active =>
      tasks.where((TaskModel task) => !task.isDone).toList(growable: false),
    TasksFilter.completed =>
      tasks.where((TaskModel task) => task.isDone).toList(growable: false),
  };

  int get activeCount => tasks.where((TaskModel task) => !task.isDone).length;
  int get completedCount => tasks.length - activeCount;
  bool get hasCompleted => completedCount > 0;

  bool get isLoading => status == TasksStatus.loading;
  bool get hasFailed => status == TasksStatus.failure;
  bool get isListEmpty => visibleTasks.isEmpty;

  TasksState copyWith({
    TasksStatus? status,
    List<TaskModel>? tasks,
    TasksFilter? filter,
    String? errorKey,
    String? messageKey,
    bool? isSaving,
    bool clearError = false,
    bool clearMessage = false,
  }) {
    return TasksState(
      status: status ?? this.status,
      tasks: tasks ?? this.tasks,
      filter: filter ?? this.filter,
      errorKey: clearError ? null : (errorKey ?? this.errorKey),
      messageKey: clearMessage ? null : (messageKey ?? this.messageKey),
      isSaving: isSaving ?? this.isSaving,
    );
  }

  @override
  List<Object?> get props => <Object?>[
    status,
    tasks,
    filter,
    errorKey,
    messageKey,
    isSaving,
  ];
}
