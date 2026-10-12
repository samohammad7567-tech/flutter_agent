import '../data_source/tasks_data_source.dart';
import '../models/task_model.dart';

class TasksRepo {
  const TasksRepo({required this.dataSource});

  final TasksDataSource dataSource;

  Future<List<TaskModel>> fetchTasks() => dataSource.fetchTasks();

  Future<List<TaskModel>> addTask(String title) =>
      dataSource.addTask(title);

  Future<List<TaskModel>> toggleTask(String id) =>
      dataSource.toggleTask(id);

  Future<List<TaskModel>> deleteTask(String id) =>
      dataSource.deleteTask(id);

  Future<List<TaskModel>> clearCompleted() => dataSource.clearCompleted();
}
