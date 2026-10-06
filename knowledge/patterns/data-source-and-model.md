# Pattern: data source, repo, model

Source: `bilhikma/lib/features/archive/data/`.

## Data source — the only layer that touches the outside

```dart
/// The archive screen: lessons the student has saved for later.
///
/// Backed by the same local selection as the saved-lessons screen, because the
/// platform API has no favourites or downloads endpoint for students.
class ArchiveDataSource {
  const ArchiveDataSource({this.saved = const SavedLessonsDataSource()});

  final SavedLessonsDataSource saved;

  Future<List<LessonModel>> fetchSavedItems({ContentType? type}) =>
      saved.fetchSaved(type: type);
}
```

Two things to copy: the doc comment explains *why* the backing store is what it
is, not what the method does; and a data source may compose another data source,
which is how a feature reuses persistence without a repo reaching across features.

## Repo — delegation, and nothing that could be called a decision

```dart
class ArchiveRepo {
  const ArchiveRepo({this.dataSource = const ArchiveDataSource()});

  final ArchiveDataSource dataSource;

  Future<List<LessonModel>> fetchSavedItems({ContentType? type}) =>
      dataSource.fetchSavedItems(type: type);
}
```

If a repo grows an `if`, a `try`, or a loop, that logic belongs one layer down
(R9). The repo's whole value is that presentation never names a data source.

## Model — owns its serialisation

```dart
class LessonModel {
  const LessonModel({required this.id, required this.title, this.createdAt});

  factory LessonModel.fromJson(Map<String, dynamic> json) {
    return LessonModel(
      id: json['id']?.toString() ?? '',
      title: json['title']?.toString() ?? '',
      createdAt: _parseDate(json['created_at']),
    );
  }

  final String id;
  final String title;
  final DateTime? createdAt;

  /// `id` and `created_at` are owned by the backend, so they never go out.
  Map<String, dynamic> toJson() => <String, dynamic>{'title': title};
}
```

The rules that are easy to get wrong:

* **Strip `id` and `created_at` before writes.** Sending a server-owned field back
  either errors or silently overwrites it.
* **Never trust a type from JSON.** `json['id']?.toString() ?? ''` survives an id
  that arrives as an int on one endpoint and a string on another.
* **Handle both date shapes.** A Firestore `Timestamp` arrives as
  `{_seconds: ...}`; a REST endpoint sends an ISO string. One helper absorbs both:

```dart
static DateTime? _parseDate(Object? raw) {
  if (raw == null) return null;
  if (raw is DateTime) return raw;
  if (raw is int) return DateTime.fromMillisecondsSinceEpoch(raw);
  final Object? seconds = raw is Map ? raw['_seconds'] ?? raw['seconds'] : null;
  if (seconds is int) return DateTime.fromMillisecondsSinceEpoch(seconds * 1000);
  return DateTime.tryParse(raw.toString());
}
```

* **One direction is fine.** A request model with only `toJson` and a response
  model with only `fromJson` are both correct; R11 only objects when a model has
  neither.

## Enums carry their own presentation data

Filters are enums with the backend value and the display key attached, so no
widget maps an enum to a label with a `switch`:

```dart
enum ArchiveFilter {
  audios(mediaType: ContentType.audio),
  articles(mediaType: ContentType.article);

  const ArchiveFilter({required this.mediaType});

  final ContentType mediaType;

  String get label => switch (this) {
    ArchiveFilter.audios => LangKeys.audios,
    ArchiveFilter.articles => LangKeys.articles,
  };
}
```
