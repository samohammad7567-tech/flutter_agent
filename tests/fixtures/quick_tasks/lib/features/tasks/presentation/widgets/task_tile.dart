import 'package:corereusablepackage/corereusablepackage.dart';
import 'package:flutter/material.dart';

import '../../../../core/extensions/context_extensions.dart';
import '../../../../core/localization/lang_keys.dart';
import '../../data/models/task_model.dart';

/// One row in the task list. Displays and forwards; decides nothing.
class TaskTile extends StatelessWidget {
  const TaskTile({
    super.key,
    required this.task,
    required this.onToggle,
    required this.onDelete,
  });

  final TaskModel task;
  final VoidCallback onToggle;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: AppCard(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        onTap: onToggle,
        child: Row(
          children: [
            Checkbox(
              value: task.isDone,
              onChanged: (_) => onToggle(),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(6),
              ),
            ),
            Expanded(
              child: Text(
                task.title,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 15,
                  color: task.isDone ? context.mutedFg : context.foreground,
                  decoration: task.isDone ? TextDecoration.lineThrough : null,
                ),
              ),
            ),
            IconButton(
              onPressed: onDelete,
              tooltip: context.translate(LangKeys.deleteTask),
              icon: Icon(Icons.delete_outline, color: context.mutedFg),
            ),
          ],
        ),
      ),
    );
  }
}
