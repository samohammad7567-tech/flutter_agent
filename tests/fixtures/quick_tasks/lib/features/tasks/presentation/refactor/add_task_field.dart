import 'package:corereusablepackage/corereusablepackage.dart';
import 'package:flutter/material.dart';

import '../../../../core/extensions/context_extensions.dart';
import '../../../../core/localization/lang_keys.dart';

/// Owns only the controller. Validation and duplicate rejection belong to the
/// data source, so this forwards the raw text and clears on submit.
class AddTaskField extends StatefulWidget {
  const AddTaskField({super.key, required this.isSaving, required this.onSubmit});

  final bool isSaving;
  final ValueChanged<String> onSubmit;

  @override
  State<AddTaskField> createState() => _AddTaskFieldState();
}

class _AddTaskFieldState extends State<AddTaskField> {
  final TextEditingController _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit() {
    final String text = _controller.text;
    if (text.trim().isEmpty) return;
    widget.onSubmit(text);
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: AppTextField(
            controller: _controller,
            hint: context.translate(LangKeys.tasksHint),
            prefixIcon: Icons.add_task,
            onChanged: (_) {},
          ),
        ),
        const SizedBox(width: 10),
        AppButton(
          label: context.translate(LangKeys.addTask),
          expand: false,
          isLoading: widget.isSaving,
          onPressed: _submit,
        ),
      ],
    );
  }
}
