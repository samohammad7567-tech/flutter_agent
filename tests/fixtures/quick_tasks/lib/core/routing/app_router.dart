import 'package:go_router/go_router.dart';

import '../../features/settings/presentation/screens/settings_screen.dart';
import '../../features/tasks/presentation/screens/tasks_screen.dart';
import 'app_routes.dart';

class AppRouter {
  AppRouter._();

  static final GoRouter router = GoRouter(
    initialLocation: AppRoutes.tasks,
    routes: [
      GoRoute(
        path: AppRoutes.tasks,
        builder: (_, _) => const TasksScreen(),
      ),
      GoRoute(
        path: AppRoutes.settings,
        builder: (_, _) => const SettingsScreen(),
      ),
    ],
  );
}
