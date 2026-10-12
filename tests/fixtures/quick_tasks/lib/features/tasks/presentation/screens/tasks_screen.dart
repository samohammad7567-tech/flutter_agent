import 'package:corereusablepackage/corereusablepackage.dart';
import 'package:flutter/material.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/di/service_locator.dart';
import '../../../../core/extensions/context_extensions.dart';
import '../../../../core/localization/lang_keys.dart';
import '../../../../core/routing/app_routes.dart';
import '../cubit/tasks_cubit.dart';
import '../cubit/tasks_state.dart';
import '../refactor/tasks_body.dart';

class TasksScreen extends StatelessWidget {
  const TasksScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return BlocProvider<TasksCubit>(
      create: (_) => getIt<TasksCubit>(),
      child: Scaffold(
        appBar: AppBar(
          title: Text(context.translate(LangKeys.tasksTitle)),
          actions: [
            IconButton(
              onPressed: () => context.push(AppRoutes.settings),
              tooltip: context.translate(LangKeys.settings),
              icon: const Icon(Icons.settings_outlined),
            ),
          ],
        ),
        body: SafeArea(
          child: BlocListener<TasksCubit, TasksState>(
            listenWhen: (TasksState previous, TasksState current) =>
                current.errorKey != previous.errorKey ||
                current.messageKey != previous.messageKey,
            listener: (BuildContext context, TasksState state) {
              final String? key = state.errorKey ?? state.messageKey;
              if (key == null) return;

              showToast(
                context,
                context.translate(key),
                type: state.errorKey != null
                    ? ToastType.error
                    : ToastType.success,
              );
            },
            child: const TasksBody(),
          ),
        ),
      ),
    );
  }
}
