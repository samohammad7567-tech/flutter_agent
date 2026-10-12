/// One task as it is persisted. `id` and `createdAt` are assigned on creation
/// and stripped from nothing — this store is local, so the model round-trips
/// whole.
class TaskModel {
  const TaskModel({
    required this.id,
    required this.title,
    required this.createdAt,
    this.isDone = false,
  });

  final String id;
  final String title;
  final DateTime createdAt;
  final bool isDone;

  factory TaskModel.fromJson(Map<String, dynamic> json) => TaskModel(
    id: json['id']?.toString() ?? '',
    title: json['title']?.toString() ?? '',
    createdAt:
        DateTime.tryParse(json['created_at']?.toString() ?? '') ??
        DateTime.fromMillisecondsSinceEpoch(0),
    isDone: json['is_done'] == true,
  );

  Map<String, dynamic> toJson() => <String, dynamic>{
    'id': id,
    'title': title,
    'created_at': createdAt.toIso8601String(),
    'is_done': isDone,
  };

  TaskModel copyWith({String? title, bool? isDone}) => TaskModel(
    id: id,
    title: title ?? this.title,
    createdAt: createdAt,
    isDone: isDone ?? this.isDone,
  );
}
