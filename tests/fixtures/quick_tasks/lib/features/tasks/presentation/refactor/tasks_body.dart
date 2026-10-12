import 'package:corereusablepackage/corereusablepackage.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import '../../../../core/extensions/context_extensions.dart';
import '../../../../core/localization/lang_keys.dart';
import '../../data/models/task_model.dart';
import '../cubit/tasks_cubit.dart';
import '../cubit/tasks_state.dart';
import '../widgets/task_tile.dart';
import 'add_task_field.dart';
import 'tasks_filter_bar.dart';

class TasksBody extends StatelessWidget {
  const TasksBody({super.key});

  static const Map<TasksFilter, String> _emptyKeys = <TasksFilter, String>{
    TasksFilter.all: LangKeys.tasksEmpty,
    TasksFilter.active: LangKeys.tasksEmptyActive,
    TasksFilter.completed: LangKeys.tasksEmptyCompleted,
  };

  @override
  Widget build(BuildContext context) {
    final TasksCubit cubit = context.read<TasksCubit>();

    return BlocBuilder<TasksCubit, TasksState>(
      builder: (BuildContext context, TasksState state) {
        if (state.isLoading) {
          return const Center(child: CircularProgressIndicator());
        }

        if (state.hasFailed) {
          return AppErrorState(
            message: context.translate(
              state.errorKey ?? LangKeys.somethingWentWrong,
            ),
            retryLabel: context.translate(LangKeys.retry),
            onRetry: cubit.loadTasks,
          );
        }

        return Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
              child: AddTaskField(
                isSaving: state.isSaving,
                onSubmit: cubit.addTask,
              ),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Row(
                children: [
                  Expanded(
                    child: TasksFilterBar(
                      selected: state.filter,
                      onSelected: cubit.selectFilter,
                    ),
                  ),
                  if (state.hasCompleted)
                    TextButton(
                      onPressed: cubit.clearCompleted,
                      child: Text(context.translate(LangKeys.clearCompleted)),
                    ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
              child: Align(
                alignment: AlignmentDirectional.centerStart,
                child: Text(
                  context.translate(
                    LangKeys.tasksRemaining,
                    args: <String, String>{'count': '${state.activeCount}'},
                  ),
                  style: TextStyle(fontSize: 13, color: context.mutedFg),
                ),
              ),
            ),
            Expanded(
              child: state.isListEmpty
                  ? AppEmptyState(
                      message: context.translate(_emptyKeys[state.filter]!),
                      icon: Icons.checklist_rtl,
                    )
                  : RefreshIndicator(
                      onRefresh: cubit.refresh,
                      child: ListView.builder(
                        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                        itemCount: state.visibleTasks.length,
                        itemBuilder: (BuildContext context, int index) {
                          final TaskModel task = state.visibleTasks[index];
                          return TaskTile(
                            task: task,
                            onToggle: () => cubit.toggleTask(task.id),
                            onDelete: () => cubit.deleteTask(task.id),
                          );
                        },
                      ),
                    ),
            ),
          ],
        );
      },
    );
  }
}
