import 'package:flutter/material.dart';

import '../../../../core/extensions/context_extensions.dart';
import '../../../../core/localization/lang_keys.dart';
import '../cubit/tasks_state.dart';

/// The three filter chips. The label for each filter is the only mapping here.
class TasksFilterBar extends StatelessWidget {
  const TasksFilterBar({
    super.key,
    required this.selected,
    required this.onSelected,
  });

  final TasksFilter selected;
  final ValueChanged<TasksFilter> onSelected;

  static const Map<TasksFilter, String> _labels = <TasksFilter, String>{
    TasksFilter.all: LangKeys.filterAll,
    TasksFilter.active: LangKeys.filterActive,
    TasksFilter.completed: LangKeys.filterCompleted,
  };

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: TasksFilter.values.map((TasksFilter filter) {
        return ChoiceChip(
          selected: filter == selected,
          label: Text(context.translate(_labels[filter]!)),
          onSelected: (_) => onSelected(filter),
        );
      }).toList(growable: false),
    );
  }
}
