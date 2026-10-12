/// Every translation key in the app. A raw string literal is never a key.
class LangKeys {
  LangKeys._();

  static const appName = 'app_name';

  // Tasks
  static const tasksTitle = 'tasks_title';
  static const tasksHint = 'tasks_hint';
  static const tasksEmpty = 'tasks_empty';
  static const tasksEmptyActive = 'tasks_empty_active';
  static const tasksEmptyCompleted = 'tasks_empty_completed';
  static const tasksRemaining = 'tasks_remaining';
  static const addTask = 'add_task';
  static const deleteTask = 'delete_task';
  static const clearCompleted = 'clear_completed';
  static const filterAll = 'filter_all';
  static const filterActive = 'filter_active';
  static const filterCompleted = 'filter_completed';
  static const taskAdded = 'task_added';
  static const taskDeleted = 'task_deleted';
  static const completedCleared = 'completed_cleared';

  // Settings
  static const settings = 'settings';
  static const theme = 'theme';
  static const themeLight = 'theme_light';
  static const themeDark = 'theme_dark';
  static const themeSystem = 'theme_system';
  static const language = 'language';
  static const languageArabic = 'language_arabic';
  static const languageEnglish = 'language_english';

  // Errors
  static const retry = 'retry';
  static const errorEmptyTitle = 'error_empty_title';
  static const errorDuplicateTask = 'error_duplicate_task';
  static const errorTaskNotFound = 'error_task_not_found';
  static const somethingWentWrong = 'something_went_wrong';
}
